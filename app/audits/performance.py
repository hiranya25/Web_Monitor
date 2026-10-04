"""
Performance Analyzer
-----------------------
Lightweight, no-external-API performance checks based on what the crawler
already measured: response time and payload size. Mirrors the "Total size
was 3.71MB" / "77 resources found" style findings from the GTmetrix report,
without requiring a full headless-Chrome Lighthouse run.

Thresholds are intentionally aligned with the attached GTmetrix/PageSpeed
benchmarks (e.g. TTFB, total page size).
"""
from __future__ import annotations
from bs4 import BeautifulSoup

from app.models import PageRecord, Issue

RESPONSE_TIME_WARN_MS = 1000     # "good" TTFB is well under 1s
RESPONSE_TIME_CRITICAL_MS = 3000
PAGE_SIZE_WARN_BYTES = 2 * 1024 * 1024   # 2MB
PAGE_SIZE_CRITICAL_BYTES = 5 * 1024 * 1024  # 5MB (amipi.com sample was ~3.7MB)


def run(pages: list[PageRecord]) -> list[Issue]:
    issues: list[Issue] = []

    for page in pages:
        if page.error or (page.status_code and page.status_code >= 400):
            continue

        # --- Response time ---
        if page.response_time_ms >= RESPONSE_TIME_CRITICAL_MS:
            issues.append(Issue(
                category="Performance", issue_type="slow_response_time", severity="critical", page_url=page.url,
                message=f"Very slow response time: {page.response_time_ms:.0f}ms",
            ))
        elif page.response_time_ms >= RESPONSE_TIME_WARN_MS:
            issues.append(Issue(
                category="Performance", issue_type="slow_response_time", severity="medium", page_url=page.url,
                message=f"Slow response time: {page.response_time_ms:.0f}ms",
            ))

        # --- Payload size ---
        if page.size_bytes >= PAGE_SIZE_CRITICAL_BYTES:
            issues.append(Issue(
                category="Performance", issue_type="large_payload_size", severity="critical", page_url=page.url,
                message=f"Very large page payload: {page.size_bytes / 1024 / 1024:.2f}MB",
            ))
        elif page.size_bytes >= PAGE_SIZE_WARN_BYTES:
            issues.append(Issue(
                category="Performance", issue_type="large_payload_size", severity="medium", page_url=page.url,
                message=f"Large page payload: {page.size_bytes / 1024 / 1024:.2f}MB",
            ))

        # --- Resource count / render-blocking hints ---
        if page.html:
            soup = BeautifulSoup(page.html, "lxml")
            scripts = soup.find_all("script", src=True)
            stylesheets = soup.find_all("link", rel="stylesheet")
            render_blocking = [
                s for s in scripts
                if not s.get("async") and not s.get("defer")
            ]
            if len(render_blocking) > 5:
                issues.append(Issue(
                    category="Performance", issue_type="render_blocking_scripts", severity="medium", page_url=page.url,
                    message=f"{len(render_blocking)} render-blocking <script> tags (no async/defer)",
                ))
            total_resources = len(scripts) + len(stylesheets) + len(soup.find_all("img"))
            if total_resources > 100:
                issues.append(Issue(
                    category="Performance", issue_type="high_resource_count", severity="low", page_url=page.url,
                    message=f"High resource count on page: {total_resources} (scripts/CSS/images)",
                ))

    return issues
