"""
Image ALT Attribute Checker
-----------------------------
Flags <img> elements with a missing or empty alt attribute.
The SEOptimer report showed amipi.com had 49 images with 1 missing an
attribute — this module generalizes that check across every crawled page.
"""
from __future__ import annotations
from bs4 import BeautifulSoup

from app.models import PageRecord, Issue


def run(pages: list[PageRecord]) -> list[Issue]:
    issues: list[Issue] = []

    for page in pages:
        if not page.html or (page.status_code and page.status_code >= 400):
            continue
        soup = BeautifulSoup(page.html, "lxml")
        images = soup.find_all("img")
        missing = [img for img in images if not img.get("alt", "").strip()]
        
        src = "(no src)"
        for img in missing:
            src = img.get("src") or img.get("data-src") or "(no src)"
            issues.append(Issue(
                category="ALT Tags",
                issue_type="missing_alt_attribute",
                severity="low",
                page_url=page.url,
                message="Image missing ALT attribute",
                details=src,
            ))

        if images and len(missing) == len(images) and len(images) > 0:
            issues.append(Issue(
                category="ALT Tags",
                issue_type="all_images_missing_alt",
                severity="medium" if src and any(x in src.lower() for x in [".png", ".jpg", ".jpeg", ".webp"]) else "low",
                page_url=page.url,
                message=f"All {len(images)} images on this page are missing ALT attributes",
            ))

    return issues
