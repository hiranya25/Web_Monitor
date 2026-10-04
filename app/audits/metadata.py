"""
Metadata & On-Page SEO Analyzer
--------------------------------
Checks title length, meta description, canonical tag, lang attribute,
and heading structure — the same checks SEOptimer/Ubersuggest flagged
manually for amipi.com (missing canonical, missing lang attribute,
title outside the 50-60 char range, etc.).
"""
from __future__ import annotations
from bs4 import BeautifulSoup

from app.models import PageRecord, Issue

TITLE_MIN, TITLE_MAX = 50, 60
META_DESC_MIN, META_DESC_MAX = 120, 160


def run(pages: list[PageRecord]) -> list[Issue]:
    issues: list[Issue] = []

    for page in pages:
        if not page.html or (page.status_code and page.status_code >= 400):
            continue
        soup = BeautifulSoup(page.html, "lxml")

        # --- Title tag ---
        title_tag = soup.find("title")
        title_text = title_tag.get_text(strip=True) if title_tag else ""
        if not title_text:
            issues.append(Issue(category="Metadata", issue_type="missing_title", severity="critical", page_url=page.url, message="Missing <title> tag"))
        elif not (TITLE_MIN <= len(title_text) <= TITLE_MAX):
            issues.append(Issue(
                category="Metadata", issue_type="title_length_incorrect", severity="low", page_url=page.url,
                message=f"Title length is {len(title_text)} chars (recommended {TITLE_MIN}-{TITLE_MAX})",
                details=title_text,
            ))

        # --- Meta description ---
        meta_desc = soup.find("meta", attrs={"name": "description"})
        desc_content = meta_desc.get("content", "").strip() if meta_desc else ""
        if not desc_content:
            issues.append(Issue(category="Metadata", issue_type="missing_meta_description", severity="medium", page_url=page.url, message="Missing meta description"))
        elif not (META_DESC_MIN <= len(desc_content) <= META_DESC_MAX):
            issues.append(Issue(
                category="Metadata", issue_type="meta_desc_length", severity="low", page_url=page.url,
                message=f"Meta description length is {len(desc_content)} chars (recommended {META_DESC_MIN}-{META_DESC_MAX})",
            ))

        # --- Canonical tag ---
        canonical = soup.find("link", attrs={"rel": "canonical"})
        if not canonical or not canonical.get("href"):
            issues.append(Issue(category="Metadata", issue_type="missing_canonical_tag", severity="medium", page_url=page.url, message="Missing canonical tag"))

        # --- Lang attribute ---
        html_tag = soup.find("html")
        if not html_tag or not html_tag.get("lang"):
            issues.append(Issue(category="Metadata", issue_type="missing_lang_attribute", severity="low", page_url=page.url, message="Missing lang attribute on <html>"))

        # --- H1 usage ---
        h1_tags = soup.find_all("h1")
        if len(h1_tags) == 0:
            issues.append(Issue(category="Metadata", issue_type="missing_h1_tag", severity="medium", page_url=page.url, message="Missing H1 tag"))
        elif len(h1_tags) > 1:
            issues.append(Issue(category="Metadata", issue_type="multiple_h1_tags", severity="low", page_url=page.url, message=f"Multiple H1 tags found ({len(h1_tags)})"))

    return issues
