"""Turns raw crawl findings into an auditable, management-ready report model."""
from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.models import Issue, PageRecord


CATEGORY_GUIDANCE = {
    "Broken Links": ("Crawlability & trust", "Repair the source URL or update references to the final 200-status destination."),
    "Metadata": ("Search relevance and click-through rate", "Create unique titles, descriptions, canonicals, and one clear H1 per indexable page."),
    "ALT Tags": ("Accessibility and image search", "Add concise, descriptive ALT text; use empty ALT only for decorative images."),
    "SEO": ("Indexation and rich search results", "Implement sitemap, robots, canonical, and appropriate Schema.org markup."),
    "Performance": ("User experience, conversion, and Core Web Vitals", "Reduce server time, defer non-critical JavaScript, compress media, and cache assets."),
    "Accessibility": ("Inclusive use and WCAG alignment", "Correct semantic and accessible-name issues, then validate with keyboard and screen-reader testing."),
    "Social Metadata": ("Reliable previews and referral engagement", "Add unique Open Graph and Twitter/X card tags."),
    "Content": ("Organic relevance and customer confidence", "Expand thin landing pages with useful copy, FAQs, headings, and contextual internal links."),
    "URL Structure": ("Duplicate prevention and crawl efficiency", "Normalize URL casing and slashes, enforce one canonical version, and redirect alternatives."),
    "Security": ("Visitor safety and browser trust", "Remove mixed content and deploy protective response headers after compatibility testing."),
    "Backlinks": ("Domain authority and external trust", "Earn high-quality referring domains and prune toxic backlinks."),
    "LLM/GEO": ("Generative Engine Optimization", "Add an llms.txt file, ensure Entity schema is present, and make content accessible to non-rendering bots."),
}


def _grade(score: int) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 55 else "F"


def _page_row(page: PageRecord) -> dict:
    soup = BeautifulSoup(page.html, "lxml") if page.html else None
    title = soup.title.get_text(" ", strip=True) if soup and soup.title else ""
    desc_tag = soup.find("meta", attrs={"name": "description"}) if soup else None
    return {
        "url": page.url, "status_code": page.status_code, "content_type": page.content_type,
        "response_time_ms": page.response_time_ms, "size_kb": round(page.size_bytes / 1024, 1),
        "depth": page.depth, "title": title,
        "meta_description": desc_tag.get("content", "").strip() if desc_tag else "",
        "h1_count": len(soup.find_all("h1")) if soup else 0,
        "image_count": len(soup.find_all("img")) if soup else 0,
        "word_count": len((soup.get_text(" ", strip=True) if soup else "").split()),
        "error": page.error,
    }


def calculate_overall_score(categories: list[dict]) -> tuple[int, str]:
    if not categories:
        return 100, _grade(100)
    
    weights = {
        "Performance": 2.0,
        "Metadata": 2.0,
        "Accessibility": 2.0,
        "URL Structure": 1.0,
        "Content": 1.0,
        "SEO": 1.0,
    }
    
    total_score = 0.0
    total_weight = 0.0
    for cat in categories:
        if cat["name"] == "Backlinks":
            continue # Exclude mock backlinks from the technical overall score, or include it if desired. We will include it.
        weight = weights.get(cat["name"], 1.0)
        total_score += cat["score"] * weight
        total_weight += weight
        
    overall = int(round(total_score / total_weight)) if total_weight > 0 else 100
    
    # Safety clamp: must be between min and max of constituent categories
    scores = [c["score"] for c in categories if c["name"] != "Backlinks"]
    if scores:
        min_score = min(scores)
        max_score = max(scores)
        overall = max(min_score, min(max_score, overall))
    
    return overall, _grade(overall)

def build(pages: list[PageRecord], issues: list[Issue]) -> tuple[dict, list[dict]]:
    by_category: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        by_category[issue.category].append(issue)

    categories = []
    for name, items in sorted(by_category.items(), key=lambda pair: (-sum(i.severity == "critical" for i in pair[1]), -len(pair[1]))):
        counts = Counter(i.severity for i in items)
        affected = len({i.page_url for i in items})
        
        # Weighted formula with capped deductions to prevent a single repeated template issue from dragging to F
        # Critical = max 25pts per distinct issue type
        # Medium = max 10pts per distinct issue type
        # Low = max 3pts per distinct issue type
        penalty = 0
        
        # Group by issue type first
        issues_by_type = defaultdict(list)
        for issue in items:
            issues_by_type[issue.issue_type].append(issue)
            
        for itype, type_items in issues_by_type.items():
            sev = type_items[0].severity
            count = len(type_items)
            if sev == "critical":
                penalty += min(25, 10 + (count * 2))
            elif sev == "medium":
                penalty += min(10, 3 + count)
            else:
                penalty += min(3, count)
                
        penalty = min(85, penalty) # Lowest score is 15
        score = int(max(0, 100 - penalty))
        
        impact, recommendation = CATEGORY_GUIDANCE.get(name, ("Website quality", "Review and resolve the affected URLs."))
        categories.append({
            "name": name, "score": score, "grade": _grade(score), "total": len(items),
            "critical": counts["critical"], "medium": counts["medium"], "low": counts["low"],
            "affected_pages": affected, "impact": impact, "recommendation": recommendation,
            "examples": [i.to_dict() for i in items[:8]],
        })

    # Mock Backlinks section removed as per requirements.

    action_items = []
    seen = set()
    severity_rank = {"critical": 0, "medium": 1, "low": 2}
    for issue in sorted(issues, key=lambda i: (severity_rank.get(i.severity, 3), i.category, i.message)):
        key = (issue.category, issue.message)
        if key in seen:
            continue
        seen.add(key)
        similar = [x for x in issues if x.category == issue.category and x.message == issue.message]
        impact, default_fix = CATEGORY_GUIDANCE.get(issue.category, ("Website quality", "Review and resolve."))
        action_items.append({
            "priority": "0–30 days" if issue.severity == "critical" else "30–60 days" if issue.severity == "medium" else "60–90 days",
            "severity": issue.severity, "category": issue.category, "issue": issue.message,
            "why_it_matters": impact, "recommended_action": issue.details if issue.details and issue.category in {"Accessibility", "Content", "Security", "URL Structure", "Social Metadata"} else default_fix,
            "affected_count": len({x.page_url for x in similar}), "sample_urls": list(dict.fromkeys(x.page_url for x in similar))[:5],
        })
        if len(action_items) >= 30:
            break

    times = sorted(p.response_time_ms for p in pages if not p.error)
    sizes = sorted(p.size_bytes for p in pages if not p.error)
    status_counts = Counter(str(p.status_code or "error") for p in pages)
    page_details = [_page_row(p) for p in pages]
    
    overall_score, overall_grade = calculate_overall_score(categories)
    
    analysis = {
        "overall_score": overall_score,
        "overall_grade": overall_grade,
        "methodology": "Breadth-first internal crawl with static HTML inspection, response timing, payload measurement, technical SEO, metadata, accessibility, content, URL, and performance checks. Note: Scoring is derived from an internal crawl methodology and is not directly equivalent to third-party audit tool scores.",
        "scope": {"pages": len(pages), "max_depth": max((p.depth for p in pages), default=0), "status_codes": dict(status_counts), "host": urlparse(pages[0].url).netloc if pages else ""},
        "performance_kpis": {
            "average_response_ms": round(sum(times) / len(times), 1) if times else 0,
            "median_response_ms": round(times[len(times)//2], 1) if times else 0,
            "p95_response_ms": round(times[min(len(times)-1, int(len(times)*.95))], 1) if times else 0,
            "slow_pages": sum(t >= 1000 for t in times),
            "average_page_kb": round((sum(sizes) / len(sizes)) / 1024, 1) if sizes else 0,
            "largest_page_kb": round(max(sizes) / 1024, 1) if sizes else 0,
        },
        "category_scores": categories,
        "action_plan": action_items,
        "limitations": [
            "Performance values are server-response and HTML payload measurements, not a Lighthouse lab run; LCP, CLS, INP, and TBT require browser instrumentation.",
            "Accessibility checks cover detectable markup only and do not replace keyboard, screen-reader, contrast, or WCAG conformance testing.",
            "Backlink authority, rankings, and traffic require external search-provider data and are not inferred by this crawler.",
        ],
    }
    return analysis, page_details
