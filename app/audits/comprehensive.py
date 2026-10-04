"""Additional checks used by the detailed management report."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.models import Issue, PageRecord


def run(pages: list[PageRecord]) -> list[Issue]:
    issues: list[Issue] = []
    for page in pages:
        if not page.html or page.error or (page.status_code and page.status_code >= 400):
            continue
        soup = BeautifulSoup(page.html, "lxml")

        # Social discovery metadata
        if not soup.find("meta", attrs={"property": "og:title"}):
            issues.append(Issue(category="Social Metadata", issue_type="missing_og_title", severity="low", page_url=page.url, message="Missing Open Graph title", details="Add og:title for reliable social previews."))
        if not soup.find("meta", attrs={"property": "og:description"}):
            issues.append(Issue(category="Social Metadata", issue_type="missing_og_desc", severity="low", page_url=page.url, message="Missing Open Graph description", details="Add og:description using the page's unique value proposition."))
        if not soup.find("meta", attrs={"name": re.compile(r"^twitter:card$", re.I)}):
            issues.append(Issue(category="Social Metadata", issue_type="missing_twitter_card", severity="low", page_url=page.url, message="Missing Twitter/X card metadata", details="Add twitter:card and related sharing tags."))

        # Accessibility fundamentals visible in static markup
        html_tag = soup.find("html")
        if not html_tag or not html_tag.get("lang"):
            issues.append(Issue(category="Accessibility", issue_type="missing_lang_attr", severity="medium", page_url=page.url, message="Document language is not declared", details="Add a valid lang attribute to <html>."))
        unnamed = [a for a in soup.find_all("a") if not a.get_text(" ", strip=True) and not a.get("aria-label") and not a.find("img", alt=True)]
        if unnamed:
            issues.append(Issue(category="Accessibility", issue_type="unnamed_links", severity="medium", page_url=page.url, message=f"{len(unnamed)} links have no accessible name", details="Add visible link text or an aria-label."))
        form_controls = soup.find_all(["input", "select", "textarea"])
        unlabeled = []
        for control in form_controls:
            if control.name == "input" and control.get("type", "text").lower() in {"hidden", "submit", "button", "image"}:
                continue
            cid = control.get("id")
            if not control.get("aria-label") and not control.get("aria-labelledby") and not (cid and soup.find("label", attrs={"for": cid})):
                unlabeled.append(control)
        if unlabeled:
            issues.append(Issue(category="Accessibility", issue_type="unlabeled_form_controls", severity="medium", page_url=page.url, message=f"{len(unlabeled)} form controls lack labels", details="Associate each control with a label or aria-label."))

        # Content quality signals
        main = soup.find("main") or soup.find("body") or soup
        words = len(re.findall(r"\b[\w'-]+\b", main.get_text(" ", strip=True)))
        if words < 150:
            issues.append(Issue(category="Content", issue_type="thin_content", severity="medium", page_url=page.url, message=f"Thin page content: approximately {words} words", details="Add useful, intent-focused copy, FAQs, and internal links."))
        if not soup.find_all("h2"):
            issues.append(Issue(category="Content", issue_type="missing_h2", severity="low", page_url=page.url, message="No H2 subheadings found", details="Organize the page with descriptive H2 sections."))

        # URL consistency
        parsed = urlparse(page.url)
        if "//" in parsed.path:
            issues.append(Issue(category="URL Structure", issue_type="repeated_slashes", severity="medium", page_url=page.url, message="URL contains repeated slashes", details="Redirect to one normalized URL and update internal links."))
        if any(ch.isupper() for ch in parsed.path):
            issues.append(Issue(category="URL Structure", issue_type="uppercase_url", severity="low", page_url=page.url, message="URL contains uppercase characters", details="Use lowercase canonical URLs consistently."))

        # Browser security policy signals (markup-level; headers are collected separately later)
        if soup.find(src=re.compile(r"^http://", re.I)) or soup.find(href=re.compile(r"^http://", re.I)):
            issues.append(Issue(category="Security", issue_type="mixed_content_refs", severity="critical", page_url=page.url, message="HTTP resource referenced from an HTTPS page", details="Serve every asset over HTTPS and remove mixed-content references."))
    return issues
