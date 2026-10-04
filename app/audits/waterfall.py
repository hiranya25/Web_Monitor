"""
Resource-Level Waterfall Analysis
---------------------------------
Analyzes the network requests captured by Playwright to identify:
- 404s on static assets (images, scripts, fonts)
- Large third-party scripts
- Total transfer size by type
"""
from __future__ import annotations
from urllib.parse import urlparse

from app.models import PageRecord, Issue
from app.config import settings

def _is_third_party(url: str, base_url: str) -> bool:
    parsed_url = urlparse(url)
    parsed_base = urlparse(base_url)
    if not parsed_url.netloc:
        return False
    # Simple check: if domain doesn't match base domain exactly, consider it 3rd party.
    # In reality, we might want to strip subdomains, but this is a good start.
    base_domain = parsed_base.netloc.replace("www.", "")
    url_domain = parsed_url.netloc.replace("www.", "")
    return base_domain not in url_domain

def run(pages: list[PageRecord]) -> list[Issue]:
    issues: list[Issue] = []

    for page in pages:
        if not page.resources:
            continue
            
        # Group resources by type
        sizes_by_type = {"script": 0, "stylesheet": 0, "image": 0, "font": 0, "document": 0, "other": 0}
        
        for res in page.resources:
            url = res["url"]
            rtype = res.get("type", "other")
            size = res.get("size_bytes", 0)
            status = res.get("status")
            
            # Categorize type
            cat_type = "other"
            if rtype in ("script", "stylesheet", "image", "font", "document"):
                cat_type = rtype
            sizes_by_type[cat_type] += size
            
            # Check for broken resources (404)
            if status == 404:
                issues.append(Issue(
                    category="Performance", issue_type="broken_resource", severity="medium", page_url=page.url,
                    message=f"Broken resource request (404) on page",
                    details=f"Resource: {url}",
                    how_to_fix="Ensure all scripts, images, and fonts linked on the page exist and return a 200 OK."
                ))
            
            # Check for large third-party scripts (>100KB)
            if rtype == "script" and _is_third_party(url, settings.SITE_BASE_URL):
                if size > 100 * 1024:
                    issues.append(Issue(
                        category="Performance", issue_type="large_third_party_script", severity="low", page_url=page.url,
                        message=f"Large third-party script loaded: {size / 1024:.1f}KB",
                        details=f"URL: {url}",
                        how_to_fix="Consider deferring this script, hosting it locally, or removing it if unused."
                    ))

        # Check for heavy asset categories
        if sizes_by_type["script"] > 1024 * 1024: # > 1MB of JS
            issues.append(Issue(
                category="Performance", issue_type="heavy_js_payload", severity="medium", page_url=page.url,
                message=f"Heavy JavaScript payload: {sizes_by_type['script'] / 1024 / 1024:.1f}MB",
                how_to_fix="Minify and bundle JavaScript. Remove unused JS and defer non-critical scripts."
            ))
            
        if sizes_by_type["image"] > 3 * 1024 * 1024: # > 3MB of Images
            issues.append(Issue(
                category="Performance", issue_type="heavy_image_payload", severity="medium", page_url=page.url,
                message=f"Heavy image payload: {sizes_by_type['image'] / 1024 / 1024:.1f}MB",
                how_to_fix="Compress images using WebP/AVIF. Implement lazy loading for images below the fold."
            ))

    return issues
