from __future__ import annotations
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from app.models import PageRecord, Issue

def run(pages: list[PageRecord]) -> list[Issue]:
    issues: list[Issue] = []
    
    # Track mixed content
    for page in pages:
        if not page.html or not page.url.startswith("https://"):
            continue
            
        soup = BeautifulSoup(page.html, "lxml")
        mixed_content = []
        for tag in soup.find_all(["img", "script", "link", "iframe"]):
            src = tag.get("src") or tag.get("href")
            if src and isinstance(src, str) and src.startswith("http://"):
                mixed_content.append(src)
                
        if mixed_content:
            issues.append(Issue(
                category="Security",
                issue_type="mixed_content",
                severity="critical",
                page_url=page.url,
                message=f"Mixed Content: {len(mixed_content)} insecure HTTP resources loaded on HTTPS page.",
                details="Update resource URLs to use https:// or protocol-relative paths."
            ))
            
    # Check security headers on the home page (or first valid page)
    valid_page = next((p for p in pages if p.status_code == 200), None)
    if valid_page:
        try:
            resp = requests.head(valid_page.url, timeout=5)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            
            missing_headers = []
            if "strict-transport-security" not in headers:
                missing_headers.append("HSTS")
            if "x-content-type-options" not in headers:
                missing_headers.append("X-Content-Type-Options")
            if "x-frame-options" not in headers and "content-security-policy" not in headers:
                missing_headers.append("X-Frame-Options or CSP frame-ancestors")
                
            if missing_headers:
                issues.append(Issue(
                    category="Security",
                    issue_type="missing_security_headers",
                    severity="medium",
                    page_url=valid_page.url,
                    message=f"Missing Security Headers: {', '.join(missing_headers)}",
                    details="Implement missing headers to protect against clickjacking, MIME-sniffing, and downgrade attacks."
                ))
        except Exception:
            pass
            
    return issues
