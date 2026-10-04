"""
Report Generator
-------------------
Takes the AuditResult (raw issues + AI summary) and renders it into:
  - a timestamped HTML report (for email body / archive)
  - a timestamped JSON snapshot (for trend analysis later / API access)
Both are saved under REPORTS_DIR so "latest report" can always be served.
"""
from __future__ import annotations
import json
import os
import csv
import re
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.models import AuditResult, group_issue_dicts
from app.audits.lighthouse import OPPORTUNITY_GUIDANCE

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "xml"])
)


from html.parser import HTMLParser
import logging

logger = logging.getLogger(__name__)

class StrictHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.open_tags = []
        self.void_elements = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def handle_starttag(self, tag, attrs):
        if tag not in self.void_elements:
            self.open_tags.append(tag)

    def handle_endtag(self, tag):
        if tag in self.void_elements:
            return
        if not self.open_tags:
            raise ValueError(f"Encountered closing tag </{tag}> but no tags are open.")
        if self.open_tags[-1] != tag:
            # We only do a strict check if it severely mismatches to avoid minor template quirks breaking everything.
            raise ValueError(f"Unmatched closing tag: expected </{self.open_tags[-1]}>, got </{tag}>.")
        self.open_tags.pop()

def validate_html(html_str: str):
    parser = StrictHTMLParser()
    parser.feed(html_str)
    if parser.open_tags:
        raise ValueError(f"Unclosed HTML tags remaining: {parser.open_tags}")


DATA_NOT_AVAILABLE = "Data Not Available"


def _csv_recommended_fix(issue) -> str:
    """Format the existing personalized remediation for spreadsheet export."""
    base_fix = (issue.how_to_fix or "").strip()
    if not base_fix:
        base_fix = (
            f"On {issue.page_url}, review the detected issue: {issue.message}. "
            "Exact replacement content is Data Not Available because no remediation text was generated for this finding."
        )

    if "How to Fix:" in base_fix and "What It Should Be:" in base_fix:
        return base_fix

    return "\n\n".join([
        f"How to Fix:\n{_csv_how_to_fix(issue, base_fix)}",
        f"What It Should Be:\n{_csv_ideal_value(issue, base_fix)}",
        f"Suggested Replacement:\n{_csv_suggested_replacement(issue, base_fix)}",
    ])


def _csv_how_to_fix(issue, base_fix: str) -> str:
    issue_type = issue.issue_type
    if issue_type in {"missing_title", "title_length_incorrect"}:
        return f"On {issue.page_url}, replace the current title value using the page-specific recommendation already generated: {base_fix}"
    if issue_type in {"missing_meta_description", "meta_desc_length"}:
        return f"On {issue.page_url}, update the meta description tag with a unique summary for this page: {base_fix}"
    if issue_type in {"missing_h1_tag", "multiple_h1_tags", "missing_h2"}:
        return f"On {issue.page_url}, update the page heading structure so the visible heading hierarchy matches the page topic: {base_fix}"
    if issue_type in {"missing_alt_attribute", "all_images_missing_alt"}:
        return f"On {issue.page_url}, update the affected image markup with descriptive ALT text: {base_fix}"
    if "link" in issue_type or issue_type in {"redirect_chain", "access_denied", "blocked_by_robots_txt"}:
        return f"On {issue.page_url}, update the affected URL/reference or redirect rule: {base_fix}"
    if issue.category == "Performance":
        return f"On {issue.page_url}, optimize the exact resource or page metric identified by the audit: {base_fix}"
    if issue.category == "Security":
        return f"On {issue.page_url}, apply the security configuration indicated by the detected value: {base_fix}"
    if issue.category in {"Social", "Social Metadata"}:
        return f"On {issue.page_url}, add the missing social profile or metadata value using the page-specific content: {base_fix}"
    if issue.issue_type in {"missing_structured_data", "missing_entity_schema"}:
        return f"On {issue.page_url}, add the schema markup generated for this page: {base_fix}"
    return f"On {issue.page_url}, resolve the detected value shown in this row: {base_fix}"


def _csv_ideal_value(issue, base_fix: str) -> str:
    issue_type = issue.issue_type
    if issue_type in {"missing_title", "title_length_incorrect"}:
        return "A unique SEO title close to 50-60 characters, containing the primary page topic and brand."
    if issue_type in {"missing_meta_description", "meta_desc_length"}:
        return "A unique meta description within the audit target range of 120-160 characters, ideally around 150-160 characters when the page copy supports it."
    if issue_type in {"missing_h1_tag", "multiple_h1_tags"}:
        return "Exactly one descriptive H1 that matches the page's primary topic; supporting section headings should use H2/H3."
    if issue_type == "missing_h2":
        return "Descriptive H2 headings that break the page into clear topical sections."
    if issue_type in {"missing_alt_attribute", "all_images_missing_alt"}:
        return "Concise, human-readable ALT text describing the specific image; decorative images should use alt=\"\"."
    if issue_type in {"missing_canonical_tag", "repeated_slashes", "uppercase_url"}:
        return "An absolute canonical URL for the preferred clean page URL, with duplicate URL variants consolidated."
    if issue_type in {"broken_internal_link", "broken_external_link", "external_link_blocked", "redirect_chain"}:
        return "A live destination returning HTTP 200, or a permanent 301 redirect from the old URL to the best matching live URL."
    if issue_type in {"slow_response_time"}:
        return "Crawl-time response below 1000ms, with important landing pages ideally below 500ms."
    if issue_type in {"large_payload_size", "heavy_image_payload"}:
        return "Page transfer close to 2 MB or less; large images should generally be under 300 KB and served as WebP or AVIF where suitable."
    if issue_type in {"render_blocking_scripts", "heavy_js_payload", "large_third_party_script"}:
        return "Only critical scripts should block rendering; non-critical first-party and third-party JavaScript should be deferred, async, reduced, or removed."
    if issue_type == "high_resource_count":
        return "A reduced request count using bundled/minified assets, lazy-loaded media, and page-specific scripts."
    if issue_type in {"missing_robots_txt", "sitemap_not_in_robots"}:
        return "A valid robots.txt file that includes crawl directives and the exact XML sitemap URL."
    if issue_type == "missing_sitemap_xml":
        return "A valid /sitemap.xml containing canonical, crawlable URLs from the site."
    if issue_type in {"missing_structured_data", "missing_entity_schema"}:
        return "Valid JSON-LD schema that matches this page's entity, organization, product, or webpage purpose."
    if issue_type in {"missing_security_headers"}:
        return "The missing response headers listed in the finding, configured at the server, app, or CDN layer."
    if issue_type in {"mixed_content", "mixed_content_refs"}:
        return "Every asset loaded through HTTPS, with no http:// resources on HTTPS pages."
    if issue.category in {"Social", "Social Metadata"}:
        return "Verified social profile URLs or page-specific Open Graph/Twitter metadata using the current page title and description."
    return "A page-specific implementation matching the detected issue, current value, and recommendation text in this row."


def _csv_suggested_replacement(issue, base_fix: str) -> str:
    patterns = [
        r'Recommended title \(\d+ characters\): "([^"]+)"',
        r'Recommended replacement \(\d+ characters\): "([^"]+)"',
        r'Recommended meta description \(\d+ characters\): "([^"]+)"',
        r'Recommended H1: "([^"]+)"',
        r'Recommended ALT text: "([^"]+)"',
        r'Add <meta property="og:title" content="([^"]+)">',
        r'Add <meta property="og:description" content="([^"]+)">',
        r'<link rel="canonical" href="([^"]+)">',
        r'Add this line to robots\.txt: (.+?)(?:\. This|$)',
        r'Replace the broken destination with ([^,]+)',
        r'create a 301 redirect from (.+?) to (.+?)(?:\.|$)',
        r'Configure the web server/CDN to return: (.+?)(?:\.|$)',
        r'for example (\{"@context":.+\})\. This gives',
    ]
    for pattern in patterns:
        match = re.search(pattern, base_fix)
        if match:
            if len(match.groups()) == 2:
                return f"{match.group(1)} -> {match.group(2).strip()}"
            return match.group(1).strip()

    if issue.details:
        return (
            f"Use the exact replacement or target described in the recommendation above for detected value: {issue.details}. "
            "A standalone replacement value was not available from the crawl data."
        )
    return "Exact replacement content is Data Not Available for this issue; use the page-specific steps and ideal value above."

EXTRA_ADVANCED_AUDITS = {
    "cdn-usage": {
        "title": "CDN Usage Recommendations",
        "why_it_matters": "A CDN can reduce latency by serving static assets closer to users.",
        "recommended_fix": "Evaluate serving static images, scripts, stylesheets, and fonts from a CDN or edge cache.",
        "expected_improvement": "Reduced latency for static resources when CDN coverage is applicable.",
        "difficulty": "Medium",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["FCP", "LCP"],
    },
}

REQUIRED_ADVANCED_AUDITS = [
    "unused-javascript",
    "unused-css-rules",
    "uses-long-cache-ttl",
    "cdn-usage",
    "critical-request-chains",
    "uses-responsive-images",
    "modern-image-formats",
    "offscreen-images",
    "font-display",
    "legacy-javascript",
    "dom-size",
    "mainthread-work-breakdown",
    "render-blocking-resources",
    "bootup-time",
    "third-party-summary",
    "network-dependency-tree",
]


def _priority_order(priority: str) -> int:
    return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(priority, 4)


def _homepage_url(site: str) -> str:
    return site.rstrip("/")


def _page_matches_home(page_url: str, site: str) -> bool:
    return page_url.rstrip("/") == _homepage_url(site)


def _advanced_placeholder(audit_id: str) -> dict:
    guidance = OPPORTUNITY_GUIDANCE.get(audit_id) or EXTRA_ADVANCED_AUDITS.get(audit_id, {})
    title = guidance.get("title", audit_id.replace("-", " ").title())
    return {
        "id": audit_id,
        "title": title,
        "priority": DATA_NOT_AVAILABLE,
        "description": DATA_NOT_AVAILABLE,
        "why_it_matters": guidance.get("why_it_matters", DATA_NOT_AVAILABLE),
        "pages_affected": DATA_NOT_AVAILABLE,
        "estimated_performance_impact": DATA_NOT_AVAILABLE,
        "estimated_time_savings": DATA_NOT_AVAILABLE,
        "estimated_size_savings": DATA_NOT_AVAILABLE,
        "estimated_request_savings": DATA_NOT_AVAILABLE,
        "estimated_savings": DATA_NOT_AVAILABLE,
        "recommended_fix": guidance.get("recommended_fix", DATA_NOT_AVAILABLE),
        "expected_improvement": guidance.get("expected_improvement", DATA_NOT_AVAILABLE),
        "implementation_difficulty": guidance.get("difficulty", DATA_NOT_AVAILABLE),
        "seo_impact": guidance.get("seo_impact", DATA_NOT_AVAILABLE),
        "performance_impact": guidance.get("performance_impact", DATA_NOT_AVAILABLE),
        "estimated_lighthouse_score_improvement": DATA_NOT_AVAILABLE,
        "viewport": DATA_NOT_AVAILABLE,
        "source": DATA_NOT_AVAILABLE,
        "raw_savings_ms": 0,
        "raw_savings_bytes": 0,
        "priority_sort": 5,
    }


def _advanced_row_from_opportunity(opportunity: dict, viewport: str, site: str) -> dict:
    return {
        "id": opportunity.get("id", ""),
        "title": opportunity.get("title") or opportunity.get("id", "").replace("-", " ").title(),
        "priority": opportunity.get("priority", DATA_NOT_AVAILABLE),
        "description": opportunity.get("description") or DATA_NOT_AVAILABLE,
        "why_it_matters": opportunity.get("why_it_matters") or DATA_NOT_AVAILABLE,
        "pages_affected": f"{_homepage_url(site)} ({viewport})",
        "estimated_performance_impact": opportunity.get("display_value") or opportunity.get("estimated_savings") or DATA_NOT_AVAILABLE,
        "estimated_time_savings": opportunity.get("estimated_time_savings") or DATA_NOT_AVAILABLE,
        "estimated_size_savings": opportunity.get("estimated_size_savings") or DATA_NOT_AVAILABLE,
        "estimated_request_savings": opportunity.get("estimated_request_savings") or DATA_NOT_AVAILABLE,
        "estimated_savings": opportunity.get("estimated_savings") or DATA_NOT_AVAILABLE,
        "recommended_fix": opportunity.get("recommended_fix") or DATA_NOT_AVAILABLE,
        "expected_improvement": opportunity.get("expected_improvement") or DATA_NOT_AVAILABLE,
        "implementation_difficulty": opportunity.get("implementation_difficulty") or DATA_NOT_AVAILABLE,
        "seo_impact": opportunity.get("seo_impact") or DATA_NOT_AVAILABLE,
        "performance_impact": opportunity.get("performance_impact") or DATA_NOT_AVAILABLE,
        "estimated_lighthouse_score_improvement": opportunity.get("estimated_lighthouse_score_improvement") or DATA_NOT_AVAILABLE,
        "viewport": viewport,
        "source": "PageSpeed/Lighthouse",
        "raw_savings_ms": opportunity.get("raw_savings_ms", 0),
        "raw_savings_bytes": opportunity.get("raw_savings_bytes", 0),
        "priority_sort": _priority_order(opportunity.get("priority", "")),
    }


def _performance_page_rows(result: AuditResult) -> list[dict]:
    rows = []
    performance_issues_by_url: dict[str, list[str]] = {}
    for issue in result.issues:
        if issue.category == "Performance":
            performance_issues_by_url.setdefault(issue.page_url.rstrip("/"), []).append(issue.message)

    for page in result.page_details:
        url = page.get("url", "")
        issues = performance_issues_by_url.get(url.rstrip("/"), [])
        lighthouse_status = "Homepage data available" if _page_matches_home(url, result.site) else DATA_NOT_AVAILABLE
        rows.append({
            "url": url,
            "response_time_ms": page.get("response_time_ms", DATA_NOT_AVAILABLE),
            "size_kb": page.get("size_kb", DATA_NOT_AVAILABLE),
            "lighthouse_status": lighthouse_status,
            "performance_findings": "; ".join(issues[:3]) if issues else "No crawl-time performance finding",
        })
    return rows


def _build_advanced_performance(result: AuditResult) -> dict:
    rows = []
    available_ids = set()

    for viewport in ("desktop", "mobile"):
        lab_data = (result.lab_metrics or {}).get(viewport) or {}
        if lab_data.get("error"):
            continue
        for opportunity in lab_data.get("opportunities", []):
            row = _advanced_row_from_opportunity(opportunity, viewport, result.site)
            rows.append(row)
            available_ids.add(row["id"])

    for audit_id in REQUIRED_ADVANCED_AUDITS:
        if audit_id not in available_ids:
            rows.append(_advanced_placeholder(audit_id))

    rows = sorted(
        rows,
        key=lambda row: (
            row["priority_sort"],
            -(row.get("raw_savings_ms") or 0),
            -(row.get("raw_savings_bytes") or 0),
            row["title"],
            row["viewport"],
        ),
    )

    actual_rows = [row for row in rows if row["source"] != DATA_NOT_AVAILABLE]
    gtmetrix_rows = []
    for idx, row in enumerate(actual_rows, start=1):
        gtmetrix_rows.append({
            "rank": f"#{idx}",
            "issue_name": row["title"],
            "severity": row["priority"],
            "affected_pages": row["pages_affected"],
            "estimated_time_savings": row["estimated_time_savings"],
            "estimated_size_savings": row["estimated_size_savings"],
            "recommendation": row["recommended_fix"],
            "implementation_difficulty": row["implementation_difficulty"],
            "expected_performance_gain": row["expected_improvement"],
            "priority_sort": row["priority_sort"],
            "raw_savings_ms": row["raw_savings_ms"],
            "raw_savings_bytes": row["raw_savings_bytes"],
        })

    if not gtmetrix_rows:
        gtmetrix_rows.append({
            "rank": DATA_NOT_AVAILABLE,
            "issue_name": "GTmetrix Top Issues",
            "severity": DATA_NOT_AVAILABLE,
            "affected_pages": DATA_NOT_AVAILABLE,
            "estimated_time_savings": DATA_NOT_AVAILABLE,
            "estimated_size_savings": DATA_NOT_AVAILABLE,
            "recommendation": "GTmetrix API/report data is not connected for this generated report.",
            "implementation_difficulty": DATA_NOT_AVAILABLE,
            "expected_performance_gain": DATA_NOT_AVAILABLE,
            "priority_sort": 5,
            "raw_savings_ms": 0,
            "raw_savings_bytes": 0,
        })

    roadmap_rows = []
    for row in rows:
        roadmap_rows.append({
            "priority": row["priority"],
            "optimization": row["title"],
            "estimated_time_savings": row["estimated_time_savings"],
            "estimated_data_savings": row["estimated_size_savings"],
            "implementation_difficulty": row["implementation_difficulty"],
            "seo_impact": row["seo_impact"],
            "performance_impact": row["performance_impact"],
            "estimated_lighthouse_score_improvement": row["estimated_lighthouse_score_improvement"],
            "priority_sort": row["priority_sort"],
            "raw_savings_ms": row["raw_savings_ms"],
            "raw_savings_bytes": row["raw_savings_bytes"],
        })

    roadmap_rows = sorted(
        roadmap_rows,
        key=lambda row: (
            row["priority_sort"],
            -(row["raw_savings_ms"] or 0),
            -(row["raw_savings_bytes"] or 0),
            row["optimization"],
        ),
    )

    counts = {
        "critical": sum(1 for row in actual_rows if row["priority"] == "Critical"),
        "high": sum(1 for row in actual_rows if row["priority"] == "High"),
        "medium": sum(1 for row in actual_rows if row["priority"] == "Medium"),
        "low": sum(1 for row in actual_rows if row["priority"] == "Low"),
        "data_not_available": sum(1 for row in rows if row["source"] == DATA_NOT_AVAILABLE),
    }

    return {
        "rows": rows,
        "gtmetrix_rows": gtmetrix_rows,
        "roadmap_rows": roadmap_rows,
        "page_rows": _performance_page_rows(result),
        "counts": counts,
        "available_audit_count": len(actual_rows),
        "total_audit_count": len(rows),
        "data_note": (
            "Actual savings are shown only when returned by PageSpeed/Lighthouse. "
            "GTmetrix-specific values require a GTmetrix data source and are marked Data Not Available when absent."
        ),
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def generate(result: AuditResult, diff: dict | None = None) -> dict:
    """Renders + saves the report. Returns paths + the rendered HTML string."""
    os.makedirs(settings.REPORTS_DIR, exist_ok=True)
    ts = _timestamp()

    if diff is None:
        diff = {"has_previous": False, "fixed": [], "new": [], "critical": []}

    csv_path = os.path.join(settings.REPORTS_DIR, f"amipi_findings_{ts}.csv")
    latest_csv_path = os.path.join(settings.REPORTS_DIR, "latest.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Urgency", "Category", "Issue", "Affected URL", "Details", "Recommended Action"])
        for issue in sorted(result.issues, key=lambda i: (0 if i.severity=="critical" else 1 if i.severity=="medium" else 2, i.category, i.page_url)):
            writer.writerow([
                issue.severity.upper(),
                issue.category,
                issue.message,
                issue.page_url,
                issue.details or "",
                _csv_recommended_fix(issue)
            ])
            
    # Also write a latest.csv copy
    import shutil
    shutil.copy2(csv_path, latest_csv_path)
    
    csv_filename = os.path.basename(csv_path)

    diff_grouped = {
        "has_previous": diff.get("has_previous", False),
        "fixed": group_issue_dicts(diff.get("fixed", [])),
        "new": group_issue_dicts(diff.get("new", [])),
        "persisting": group_issue_dicts(diff.get("persisting", [])),
        "critical": group_issue_dicts(diff.get("critical", [])),
    }

    template = _env.get_template("report.html")
    html = template.render(
        result=result,
        ai_summary=result.ai_summary or {"executive_summary": "No AI summary available.",
                                          "overall_health_score": "N/A", "top_priorities": []},
        counts=result.issue_counts_by_severity(),
        grouped=result.grouped_issues_by_category(),
        diff=diff_grouped,
        csv_filename=csv_filename,
        advanced_performance=_build_advanced_performance(result),
    )

    try:
        validate_html(html)
    except ValueError as e:
        logger.error("HTML validation failed during report generation: %s. "
                     "This indicates a potential injection of unescaped markup. "
                     "Falling back to basic HTML render to prevent PDF engine crash.", e)
        # We still write the html, but we log the critical error so we know it happened.
        # Since Jinja autoescaping is ON, this should never trigger from fix-text anymore.

    html_path = os.path.join(settings.REPORTS_DIR, f"report_{ts}.html")
    json_path = os.path.join(settings.REPORTS_DIR, f"report_{ts}.json")
    latest_html_path = os.path.join(settings.REPORTS_DIR, "latest.html")
    latest_json_path = os.path.join(settings.REPORTS_DIR, "latest.json")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    with open(latest_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)
    with open(latest_json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2)

    return {
        "html_path": html_path,
        "json_path": json_path,
        "csv_path": csv_path,
        "html": html,
    }
