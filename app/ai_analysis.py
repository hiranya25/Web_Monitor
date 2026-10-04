"""
AI Analysis Layer — powered by NVIDIA Nemotron API
(OpenAI-compatible: https://integrate.api.nvidia.com/v1,
 model: nvidia/nemotron-3-ultra-550b-a55b)

Takes the raw list of Issues produced by the audit modules and asks the
model to:
  1. Write a short, plain-English executive summary.
  2. Re-classify / confirm severity (critical / medium / low) per issue.
  3. Produce a prioritized top-N action list with concrete recommendations.

The rest of the pipeline (crawler, audits, report generator, email) works
fine even if this call fails or no API key is set — AI analysis is treated
as an enrichment step, not a hard dependency.
"""
from __future__ import annotations
import json
import logging
import httpx
from openai import OpenAI

from app.config import settings
from app.models import Issue

logger = logging.getLogger("ai_analysis")

SYSTEM_PROMPT = """You are a senior technical SEO and web performance expert.
Analyze the following website health audit.

1. Write a 3-4 sentence plain-English executive summary a non-technical manager can understand.
2. Re-check the severity of each issue category is reasonable (critical / medium / low).
3. Produce a "top_priorities" list of at most 8 items: the highest-impact fixes first, each with
   a one-line recommendation. Ensure there are NO duplicate issue types in this list.

Respond ONLY with valid JSON in exactly this shape, no extra commentary:
{
  "executive_summary": "...",
  "top_priorities": [
    {"issue": "...", "why_it_matters": "...", "recommendation": "..."}
  ]
}
"""


def _client() -> OpenAI | None:
    if not settings.AI_API_KEY:
        logger.warning("AI_API_KEY not set — skipping AI analysis.")
        return None
    # 3-minute timeout so the pipeline never hangs on a slow AI response
    return OpenAI(
        base_url=settings.AI_API_BASE,
        api_key=settings.AI_API_KEY,
        http_client=httpx.Client(timeout=httpx.Timeout(180.0, connect=30.0))
    )


def analyze(issues: list[Issue], site: str, pages_crawled: int) -> dict | None:
    """Calls NVIDIA Nemotron to summarize/prioritize findings.
    Returns a dict (see SYSTEM_PROMPT schema) or falls back to rule-based summary."""
    client = _client()
    if client is None:
        return _fallback_summary(issues, pages_crawled, site)

    # Group by issue_type to keep the payload strictly minimal and avoid context limits
    by_issue_type = {}
    for issue in issues:
        by_issue_type.setdefault(issue.issue_type, []).append(issue)

    sample_payload = {
        "site": site,
        "pages_crawled": pages_crawled,
        "total_issues": len(issues),
        "unique_issue_types": len(by_issue_type),
        "issue_samples": [
            {
                "issue_type": itype,
                "category": items[0].category,
                "severity": items[0].severity,
                "count": len(items),
                "example_message": items[0].message
            }
            for itype, items in by_issue_type.items()
        ]
    }

    import time
    for attempt in range(3):
        try:
            logger.info("Calling NVIDIA Nemotron API for AI analysis (attempt %d/3)...", attempt + 1)
            completion = client.chat.completions.create(
                model=settings.AI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(sample_payload)},
                ],
                temperature=0.3,
                top_p=0.9,
                max_tokens=2048,
                stream=True,
            )

            content_parts = []
            for chunk in completion:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content is not None:
                    content_parts.append(delta.content)

            content = "".join(content_parts).strip()
            content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(content)
        except Exception as exc:  # noqa: BLE001
            logger.error("AI analysis call failed (attempt %d/3): %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(2 ** attempt)  # Exponential backoff: 1s, 2s
            else:
                logger.error("AI analysis exhausted retries. Falling back to rule-based.")
                return _fallback_summary(issues, pages_crawled, site)



def _fallback_summary(issues: list[Issue], pages_crawled: int, site: str) -> dict:
    """Rule-based summary used if the AI call is unavailable/fails,
    so the pipeline (and weekly email) never breaks."""
    from app.detailed_analysis import CATEGORY_GUIDANCE

    counts = {"critical": 0, "medium": 0, "low": 0}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1

    score = max(0, 100 - counts["critical"] * 5 - counts["medium"] * 2 - counts["low"] * 1)
    top = sorted(issues, key=lambda i: {"critical": 0, "medium": 1, "low": 2}[i.severity])[:8]

    top_priorities = []
    seen_types = set()
    for i in top:
        if i.issue_type in seen_types:
            continue
        seen_types.add(i.issue_type)
        impact, default_fix = CATEGORY_GUIDANCE.get(i.category, ("Website quality", "Review and resolve."))
        recommendation = i.details if i.details and i.category in {"Accessibility", "Content", "Security", "URL Structure", "Social Metadata"} else default_fix
        top_priorities.append({
            "issue": i.message,
            "why_it_matters": impact,
            "recommendation": recommendation
        })
        if len(top_priorities) >= 8:
            break

    unique_issue_count = len({i.issue_type for i in issues})
    
    return {
        "executive_summary": f"The crawl analyzed {pages_crawled} pages and identified {unique_issue_count} distinct issues "
                             f"across {len(issues)} total page instances. "
                             f"{counts['critical']} findings are critical. "
                             f"Address the top priorities to improve stability and UX.",
        "overall_health_score": str(score),
        "top_priorities": top_priorities,
    }
