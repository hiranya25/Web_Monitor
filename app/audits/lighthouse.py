"""
Lighthouse Integration
----------------------
Calls the Google PageSpeed Insights API (which runs Lighthouse lab data)
to retrieve real Core Web Vitals (LCP, INP, CLS, TBT, Speed Index, FCP).
Handles both Mobile and Desktop viewports and exposes any available
performance opportunities for the advanced report appendix.
"""
from __future__ import annotations
import logging
import requests

from app.config import settings
from app.models import Issue

logger = logging.getLogger("lighthouse")

OPPORTUNITY_GUIDANCE = {
    "unused-javascript": {
        "title": "Unused JavaScript",
        "why_it_matters": "Unused JavaScript increases transfer size, parsing time, and main-thread work.",
        "recommended_fix": "Remove unused scripts, split bundles by route, defer non-critical code, and load features only when needed.",
        "expected_improvement": "Lower JS transfer, faster parsing, reduced TBT, and improved LCP on script-heavy pages.",
        "difficulty": "Medium",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["LCP", "TBT"],
    },
    "unused-css-rules": {
        "title": "Unused CSS",
        "why_it_matters": "Unused CSS blocks rendering and adds unnecessary bytes before the page can paint.",
        "recommended_fix": "Remove unused selectors, split critical CSS, and load non-critical styles after first render.",
        "expected_improvement": "Reduced render-blocking CSS and faster FCP/LCP.",
        "difficulty": "Medium",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["FCP", "LCP"],
    },
    "uses-long-cache-ttl": {
        "title": "Cache Policy / Efficient Cache Lifetime",
        "why_it_matters": "Short cache lifetimes force repeat visitors to re-download static assets.",
        "recommended_fix": "Add long-lived cache-control headers for versioned CSS, JS, images, and font assets.",
        "expected_improvement": "Faster repeat visits and reduced network transfer.",
        "difficulty": "Easy",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["FCP", "LCP"],
    },
    "critical-request-chains": {
        "title": "Critical Request Chains",
        "why_it_matters": "Long dependency chains delay discovery of render-critical resources.",
        "recommended_fix": "Inline critical CSS, preload key assets, remove blocking dependencies, and flatten request chains.",
        "expected_improvement": "Earlier rendering and improved FCP/LCP.",
        "difficulty": "Hard",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["FCP", "LCP"],
    },
    "network-dependency-tree": {
        "title": "Network Dependency Analysis",
        "why_it_matters": "A complex dependency tree delays important requests and amplifies latency.",
        "recommended_fix": "Prioritize critical assets, remove unnecessary dependencies, and preload late-discovered resources.",
        "expected_improvement": "Shorter critical path and faster content rendering.",
        "difficulty": "Hard",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["FCP", "LCP"],
    },
    "uses-responsive-images": {
        "title": "Properly Sized Images",
        "why_it_matters": "Oversized images waste bandwidth and delay LCP, especially on mobile.",
        "recommended_fix": "Serve responsive image sizes with srcset/sizes and avoid sending desktop-sized assets to small screens.",
        "expected_improvement": "Lower image transfer and faster LCP.",
        "difficulty": "Medium",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["LCP"],
    },
    "modern-image-formats": {
        "title": "Next-Generation Image Formats (WebP/AVIF)",
        "why_it_matters": "Legacy image formats are often larger than WebP or AVIF equivalents.",
        "recommended_fix": "Serve WebP or AVIF versions with JPEG/PNG fallbacks where needed.",
        "expected_improvement": "Reduced image bytes and faster visual loading.",
        "difficulty": "Medium",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["LCP"],
    },
    "offscreen-images": {
        "title": "Offscreen Image Deferral (Lazy Loading)",
        "why_it_matters": "Below-the-fold images compete with above-the-fold content for bandwidth.",
        "recommended_fix": "Lazy-load offscreen images while keeping the LCP image eager and high priority.",
        "expected_improvement": "Fewer initial requests and faster first viewport rendering.",
        "difficulty": "Easy",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["LCP"],
    },
    "font-display": {
        "title": "font-display Optimization",
        "why_it_matters": "Web fonts can hide text while downloading, delaying readable content.",
        "recommended_fix": "Use font-display: swap or optional and preload only critical font files.",
        "expected_improvement": "Text appears sooner and perceived performance improves.",
        "difficulty": "Easy",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["FCP", "LCP"],
    },
    "legacy-javascript": {
        "title": "Legacy JavaScript Serving",
        "why_it_matters": "Legacy JavaScript sends extra code to modern browsers and increases parse/compile work.",
        "recommended_fix": "Ship modern bundles with module/nomodule or modern build targets.",
        "expected_improvement": "Smaller JavaScript payloads and reduced main-thread work.",
        "difficulty": "Medium",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["TBT"],
    },
    "dom-size": {
        "title": "Excessive DOM Size",
        "why_it_matters": "Large DOMs increase style calculation, layout work, memory use, and interaction latency.",
        "recommended_fix": "Reduce repeated markup, paginate or virtualize long lists, and simplify nested layout structures.",
        "expected_improvement": "Less main-thread work and better interaction responsiveness.",
        "difficulty": "Hard",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["TBT"],
    },
    "mainthread-work-breakdown": {
        "title": "Main Thread Work Breakdown",
        "why_it_matters": "Heavy main-thread work delays rendering and blocks user input.",
        "recommended_fix": "Reduce script execution, split long tasks, move expensive work off-thread, and simplify layout work.",
        "expected_improvement": "Reduced TBT and faster interaction readiness.",
        "difficulty": "Hard",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["TBT"],
    },
    "long-tasks": {
        "title": "Avoid Long Main-thread Tasks",
        "why_it_matters": "Long tasks block the browser from responding quickly to user input.",
        "recommended_fix": "Split long tasks, defer non-critical JavaScript, and reduce expensive synchronous work.",
        "expected_improvement": "Lower TBT and smoother interaction readiness.",
        "difficulty": "Hard",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["TBT"],
    },
    "bootup-time": {
        "title": "Total Blocking Time Contributors",
        "why_it_matters": "Expensive JavaScript boot-up blocks the main thread during load.",
        "recommended_fix": "Trim third-party scripts, defer non-critical JavaScript, and break large bundles into smaller chunks.",
        "expected_improvement": "Lower TBT and faster interactive readiness.",
        "difficulty": "Hard",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["TBT"],
    },
    "render-blocking-resources": {
        "title": "Render Blocking Resources",
        "why_it_matters": "Blocking CSS and synchronous scripts delay first paint and LCP.",
        "recommended_fix": "Inline critical CSS, defer scripts, preload critical resources, and remove unused blocking files.",
        "expected_improvement": "Faster FCP and LCP.",
        "difficulty": "Medium",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["FCP", "LCP"],
    },
    "uses-text-compression": {
        "title": "Enable Text Compression",
        "why_it_matters": "Uncompressed text assets increase transfer size for HTML, CSS, and JavaScript.",
        "recommended_fix": "Enable Brotli or gzip compression for text-based resources.",
        "expected_improvement": "Reduced data transfer and faster downloads.",
        "difficulty": "Easy",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["FCP", "LCP"],
    },
    "unminified-css": {
        "title": "Minify CSS",
        "why_it_matters": "Unminified CSS sends unnecessary bytes and can slow render-blocking stylesheets.",
        "recommended_fix": "Minify CSS in the build pipeline and serve compressed production assets.",
        "expected_improvement": "Reduced CSS transfer size and faster render start.",
        "difficulty": "Easy",
        "seo_impact": "Low",
        "performance_impact": "Low",
        "metric_refs": ["FCP", "LCP"],
    },
    "unminified-javascript": {
        "title": "Minify JavaScript",
        "why_it_matters": "Unminified JavaScript increases transfer size and parse cost.",
        "recommended_fix": "Minify JavaScript in the production build and remove source-only code from served bundles.",
        "expected_improvement": "Reduced JS transfer and parse time.",
        "difficulty": "Easy",
        "seo_impact": "Low",
        "performance_impact": "Medium",
        "metric_refs": ["TBT"],
    },
    "third-party-summary": {
        "title": "Third-party Code Impact",
        "why_it_matters": "Third-party scripts can block the main thread and add network latency outside your release control.",
        "recommended_fix": "Remove unused vendors, delay tags until consent/interaction, and load low-priority tags asynchronously.",
        "expected_improvement": "Reduced main-thread blocking and fewer competing network requests.",
        "difficulty": "Medium",
        "seo_impact": "Low",
        "performance_impact": "High",
        "metric_refs": ["TBT"],
    },
    "total-byte-weight": {
        "title": "Avoid Enormous Network Payloads",
        "why_it_matters": "Large total transfer size slows page load and hurts users on slower connections.",
        "recommended_fix": "Compress assets, remove unused code, optimize images, and audit third-party payloads.",
        "expected_improvement": "Lower page weight and faster load time.",
        "difficulty": "Medium",
        "seo_impact": "Medium",
        "performance_impact": "High",
        "metric_refs": ["LCP"],
    },
    "server-response-time": {
        "title": "Reduce Server Response Time",
        "why_it_matters": "Slow server response delays every render milestone that depends on the HTML document.",
        "recommended_fix": "Add server-side caching, optimize database queries, tune hosting, and use edge caching where appropriate.",
        "expected_improvement": "Lower TTFB and faster FCP/LCP.",
        "difficulty": "Hard",
        "seo_impact": "High",
        "performance_impact": "High",
        "metric_refs": ["FCP", "LCP"],
    },
    "largest-contentful-paint-element": {
        "title": "Optimize LCP Element",
        "why_it_matters": "The LCP element controls the largest visible content milestone.",
        "recommended_fix": "Prioritize the LCP image/text, avoid lazy-loading it, preload it when appropriate, and reduce render blockers.",
        "expected_improvement": "Faster LCP and better user-perceived loading.",
        "difficulty": "Medium",
        "seo_impact": "High",
        "performance_impact": "High",
        "metric_refs": ["LCP"],
    },
    "layout-shifts": {
        "title": "Reduce CLS",
        "why_it_matters": "Layout shifts create visual instability and can hurt Page Experience.",
        "recommended_fix": "Reserve image/ad/embed dimensions, avoid injecting content above existing content, and stabilize fonts.",
        "expected_improvement": "Lower CLS and a more stable user experience.",
        "difficulty": "Medium",
        "seo_impact": "Medium",
        "performance_impact": "Medium",
        "metric_refs": ["CLS"],
    },
}


def _format_bytes(num_bytes: float | int | None) -> str | None:
    if not num_bytes:
        return None
    value = float(num_bytes)
    if value >= 1024 * 1024:
        return f"{value / 1024 / 1024:.1f} MB"
    return f"{value / 1024:.0f} KB"


def _format_ms(num_ms: float | int | None) -> str | None:
    if not num_ms:
        return None
    value = float(num_ms)
    if value >= 1000:
        return f"{value / 1000:.1f}s"
    return f"{value:.0f}ms"


def _priority(score: float | None, savings_ms: float, savings_bytes: float) -> str:
    if (score is not None and score <= 0.1) or savings_ms >= 2000 or savings_bytes >= 1024 * 1024:
        return "Critical"
    if (score is not None and score <= 0.5) or savings_ms >= 1000 or savings_bytes >= 500 * 1024:
        return "High"
    if (score is not None and score <= 0.8) or savings_ms >= 250 or savings_bytes >= 100 * 1024:
        return "Medium"
    return "Low"


def _priority_sort(priority: str) -> int:
    return {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}.get(priority, 4)


def _extract_opportunities(audits: dict) -> list[dict]:
    opportunities = []
    for audit_id, guidance in OPPORTUNITY_GUIDANCE.items():
        audit = audits.get(audit_id)
        if not audit:
            continue

        details = audit.get("details") or {}
        savings_ms = float(details.get("overallSavingsMs") or 0)
        savings_bytes = float(details.get("overallSavingsBytes") or 0)
        display_value = audit.get("displayValue") or ""
        score = audit.get("score")
        has_signal = score is None or score < 1 or savings_ms or savings_bytes or display_value
        if not has_signal:
            continue

        savings_parts = [_format_ms(savings_ms), _format_bytes(savings_bytes)]
        savings_display = " / ".join(part for part in savings_parts if part)
        if not savings_display and display_value.lower().startswith("potential savings"):
            savings_display = display_value.replace("Potential savings of ", "")

        priority = _priority(score, savings_ms, savings_bytes)
        opportunities.append({
            "id": audit_id,
            "title": audit.get("title") or guidance["title"],
            "priority": priority,
            "priority_rank": _priority_sort(priority),
            "score": score,
            "description": audit.get("description") or guidance["title"],
            "why_it_matters": guidance["why_it_matters"],
            "recommended_fix": guidance["recommended_fix"],
            "expected_improvement": guidance["expected_improvement"],
            "implementation_difficulty": guidance["difficulty"],
            "seo_impact": guidance["seo_impact"],
            "performance_impact": guidance["performance_impact"],
            "metric_refs": guidance["metric_refs"],
            "estimated_time_savings": _format_ms(savings_ms) or "Data Not Available",
            "estimated_size_savings": _format_bytes(savings_bytes) or "Data Not Available",
            "estimated_request_savings": "Data Not Available",
            "estimated_savings": savings_display or display_value or "Data Not Available",
            "display_value": display_value or "Data Not Available",
            "raw_savings_ms": savings_ms,
            "raw_savings_bytes": savings_bytes,
            "estimated_lighthouse_score_improvement": "Data Not Available",
        })

    return sorted(
        opportunities,
        key=lambda item: (
            item["priority_rank"],
            -(item["raw_savings_ms"] or 0),
            -(item["raw_savings_bytes"] or 0),
            item["title"],
        ),
    )

def fetch_pagespeed_data(url: str, strategy: str) -> dict | None:
    if not settings.PAGESPEED_API_KEY or settings.PAGESPEED_API_KEY == "your_api_key_here":
        logger.warning(f"PAGESPEED_API_KEY not configured properly (current: {settings.PAGESPEED_API_KEY}). Skipping Lighthouse lab data.")
        return {"error": "API Key missing or invalid"}
    
    api_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": url,
        "strategy": strategy.upper(),  # 'DESKTOP' or 'MOBILE'
        "key": settings.PAGESPEED_API_KEY,
        "category": "performance"
    }
    
    import time
    for attempt in range(3):
        try:
            resp = requests.get(api_url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTPError on PageSpeed API {strategy} (Attempt {attempt+1}): {e.response.status_code} - {e.response.text}")
            if e.response.status_code in [400, 401, 403, 404, 429]: # Non-retriable auth/bad request/rate limit errors
                return {"error": f"API Error: HTTP {e.response.status_code}"}
            time.sleep(2 ** attempt)
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error on PageSpeed API {strategy} (Attempt {attempt+1}): {e}")
            time.sleep(2 ** attempt)
            
    return {"error": "Max retries exceeded or connection timed out"}

def extract_metrics(data: dict) -> dict:
    if not data or "error" in data:
        return {"error": data.get("error", "Unknown error")}
        
    if "lighthouseResult" not in data:
        return {"error": "Invalid response format"}
    
    audits = data["lighthouseResult"]["audits"]
    
    def get_metric(key: str) -> dict:
        audit = audits.get(key, {})
        return {
            "score": audit.get("score"),
            "value": audit.get("displayValue"),
            "numeric_value": audit.get("numericValue")
        }

    return {
        "score": data["lighthouseResult"]["categories"]["performance"]["score"] * 100,
        "LCP": get_metric("largest-contentful-paint"),
        "CLS": get_metric("cumulative-layout-shift"),
        "TBT": get_metric("total-blocking-time"),
        "SpeedIndex": get_metric("speed-index"),
        "FCP": get_metric("first-contentful-paint"),
        "INP": get_metric("interactive"), # Fallback to interactive if INP missing
        "opportunities": _extract_opportunities(audits),
    }

def run_for_url(url: str) -> dict:
    """Runs Lighthouse for both mobile and desktop and returns the lab metrics."""
    metrics = {
        "desktop": {},
        "mobile": {}
    }
    
    desktop_data = fetch_pagespeed_data(url, "desktop")
    if desktop_data:
        metrics["desktop"] = extract_metrics(desktop_data)
        
    mobile_data = fetch_pagespeed_data(url, "mobile")
    if mobile_data:
        metrics["mobile"] = extract_metrics(mobile_data)
        
    return metrics
