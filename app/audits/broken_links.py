"""
Broken Link Checker
--------------------
Flags any crawled page that returned a 4xx/5xx status, plus any
outbound <a href> link (internal or external) that resolves to an error.
Mirrors the '404' rows seen repeatedly in the GTmetrix waterfall
(e.g. product_thumb.php?... returning 404).
"""
from __future__ import annotations
import requests
from bs4 import BeautifulSoup

from app.config import settings
from app.models import PageRecord, Issue

_checked_cache: dict[str, int | None] = {}


import time

def _check_status(url: str, retry: bool = True) -> int | None:
    if url in _checked_cache:
        return _checked_cache[url]
    try:
        resp = requests.head(
            url, timeout=5, allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
        )
        if resp.status_code >= 400:
            resp = requests.get(
                url, timeout=5, allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}, stream=True,
            )
        _checked_cache[url] = resp.status_code
        return resp.status_code
    except requests.RequestException:
        if retry:
            time.sleep(1)
            return _check_status(url, retry=False)
        _checked_cache[url] = None
        return None


def run(pages: list[PageRecord], check_outbound_links: bool = True) -> list[Issue]:
    issues: list[Issue] = []

    # 1. Pages that themselves failed to load.
    for page in pages:
        if page.error == "Blocked by robots.txt":
            issues.append(Issue(
                category="Broken Links",
                issue_type="blocked_by_robots_txt",
                severity="medium",
                page_url=page.url,
                message="Crawling blocked by robots.txt",
                details="This URL cannot be crawled or indexed.",
            ))
        elif page.error:
            issues.append(Issue(
                category="Broken Links",
                issue_type="broken_internal_link",
                severity="critical",
                page_url=page.url,
                message="Page failed to load",
                details=page.error,
            ))
        elif page.status_code and page.status_code != 200:
            if 300 <= page.status_code < 400:
                issues.append(Issue(
                    category="Broken Links",
                    issue_type="redirect_chain",
                    severity="low",
                    page_url=page.url,
                    message=f"Page redirected (HTTP {page.status_code})",
                ))
            else:
                severity = "critical" if page.status_code >= 500 else "medium"
                issue_type = "access_denied" if page.status_code in (401, 403) else "broken_internal_link"
                
                issues.append(Issue(
                    category="Broken Links",
                    issue_type=issue_type,
                    severity=severity,
                    page_url=page.url,
                    message=f"Page returned HTTP {page.status_code}",
                ))

    # 2. Links referenced on each page (checked with HEAD/GET, deduplicated via cache).
    if check_outbound_links:
        import concurrent.futures
        # Collect references: target_url -> (tag_type, set(source_page_urls))
        outbound_refs: dict[str, tuple[str, set[str]]] = {}
        for page in pages:
            if not page.html:
                continue
            soup = BeautifulSoup(page.html, "lxml")
            for tag, attr in (("a", "href"), ("img", "src"), ("script", "src"), ("link", "href")):
                for el in soup.find_all(tag, **{attr: True}):
                    target = el[attr].strip()
                    if not target or target.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                        continue
                    if not target.startswith("http"):
                        continue  # normalization/dedup for relative URLs is handled by the crawler pass
                    
                    if target not in outbound_refs:
                        outbound_refs[target] = (tag, set())
                    outbound_refs[target][1].add(page.url)

        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_target = {executor.submit(_check_status, target): target for target in outbound_refs.keys()}
            for future in concurrent.futures.as_completed(future_to_target):
                target = future_to_target[future]
                try:
                    status = future.result()
                except Exception:
                    status = None

                if status is None or status >= 400:
                    tag, source_pages = outbound_refs[target]
                    is_anti_bot = status in (403, 429)
                    severity = "low" if is_anti_bot else "medium"
                    issue_type = "external_link_blocked" if is_anti_bot else "broken_external_link"
                    
                    status_str = f"HTTP {status} (Anti-Bot/Access Denied)" if is_anti_bot else ('no response' if status is None else f'HTTP {status}')
                    
                    # Report one finding per URL, listing the number of affected pages
                    issues.append(Issue(
                        category="Broken Links",
                        issue_type=issue_type,
                        severity=severity,
                        page_url=list(source_pages)[0],  # Give the first affected page as reference
                        message=f"Broken resource ({tag}): {status_str}",
                        details=f"Target: {target} (Found on {len(source_pages)} pages)",
                    ))

    return issues
