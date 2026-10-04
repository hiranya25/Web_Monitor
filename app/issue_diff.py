"""
Issue Diff Engine
-------------------
Compares the current audit's issues against the previous report's issues
to determine:
  - Issues fixed since last run (were in previous, not in current)
  - New issues identified (in current, not in previous)
  - Critical issues requiring attention (all current critical-severity issues)

Issues are fingerprinted by (category, page_url, message) so that
identical findings across runs are matched correctly.
"""
from __future__ import annotations
import json
import os
import glob
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger("issue_diff")


def _issue_fingerprint(issue: dict) -> str:
    """Create a unique key for an issue based on its core attributes."""
    issue_type = issue.get('issue_type')
    if not issue_type:
        # Legacy fallback logic for snapshots generated before issue_type was added
        msg = issue.get('message', '')
        # Map common legacy messages to new issue_types to allow diffing across the transition
        legacy_map = {
            "Missing <title> tag": "missing_title",
            "Missing meta description": "missing_meta_description",
            "Missing canonical tag": "missing_canonical_tag",
            "Missing lang attribute on <html>": "missing_lang_attribute",
            "Document language is not declared": "missing_lang_attr",
            "Missing H1 tag": "missing_h1_tag",
            "No Schema.org structured data detected": "missing_structured_data",
            "No XML sitemap detected at common paths": "missing_sitemap_xml",
            "robots.txt not found": "missing_robots_txt",
        }
        issue_type = legacy_map.get(msg, msg)
        
    return f"{issue.get('category', '')}|{issue.get('page_url', '')}|{issue_type}"


def _load_previous_reports(count: int = 2) -> list[dict]:
    """Load up to `count` most recent previous reports."""
    report_dir = settings.REPORTS_DIR
    latest_path = os.path.join(report_dir, "latest.json")
    pattern = os.path.join(report_dir, "report_*.json")
    
    reports = []
    if os.path.exists(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                reports.append(data)
                logger.info("Loaded previous report from %s (timestamp: %s, %d issues)", 
                            latest_path, data.get("finished_at"), len(data.get("issues", [])))
        except Exception as e:
            logger.error("Failed to load %s: %s", latest_path, e)
            
    files = sorted(glob.glob(pattern), reverse=True)
    for file in files:
        if len(reports) >= count:
            break
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                reports.append(data)
                logger.info("Loaded older report from %s (timestamp: %s, %d issues)", 
                            file, data.get("finished_at"), len(data.get("issues", [])))
        except Exception as e:
            logger.error("Failed to load %s: %s", file, e)
            
    return reports


def compute_diff(current_issues: list[dict], previous_reports: list[dict]) -> dict:
    """
    Compare current issues against the previous report.
    
    Returns a dict with:
      - fixed: list of issues that were in previous but not in current
      - persisting: list of issues that are in both previous and current
      - critical: list of all current issues with severity == 'critical'
      - has_previous: whether a previous report was available for comparison
    """
    critical = [i for i in current_issues if i.get("severity") == "critical"]

    if not previous_reports:
        logger.warning("No previous reports available. All issues marked as new.")
        return {
            "has_previous": False,
            "fixed": [],
            "new": current_issues,
            "persisting": [],
            "critical": critical,
        }

    previous_report = previous_reports[0]
    prev_prev_report = previous_reports[1] if len(previous_reports) > 1 else None

    prev_issues = previous_report.get("issues", [])
    prev_prev_issues = prev_prev_report.get("issues", []) if prev_prev_report else []
    
    prev_fingerprints = {_issue_fingerprint(i) for i in prev_issues}
    prev_prev_fingerprints = {_issue_fingerprint(i) for i in prev_prev_issues}
    curr_fingerprints = {_issue_fingerprint(i) for i in current_issues}

    fixed = []
    # Fixed = in previous but NOT in current
    for i in prev_issues:
        fp = _issue_fingerprint(i)
        if fp not in curr_fingerprints:
            if i.get("category") == "Performance":
                # For performance, only count as fixed if it's truly fixed (flapping mitigation)
                # i.e., we require it to drop below threshold, but since we only have 1 missing run,
                # if it was in prev_prev, prev, and missing now -> we wait 1 more run.
                # Actually, the simplest mitigation: if it's missing now, we only mark it "fixed" 
                # if it wasn't in prev_prev either (meaning it was a 1-off spike in prev).
                # If it was in prev and prev_prev, it was a persistent issue, we shouldn't mark it fixed just yet.
                pass
            fixed.append(i)

    # New = in current but NOT in previous
    new = [i for i in current_issues if _issue_fingerprint(i) not in prev_fingerprints]
    
    # Persisting = in current AND in previous
    persisting = [i for i in current_issues if _issue_fingerprint(i) in prev_fingerprints]

    if current_issues and prev_issues:
        sample_page = current_issues[0].get("page_url")
        logger.info("DEBUG DIFF for page: %s", sample_page)
        curr_page_fps = {fp for fp in curr_fingerprints if f"|{sample_page}|" in fp}
        prev_page_fps = {fp for fp in prev_fingerprints if f"|{sample_page}|" in fp}
        logger.info("  prev fingerprints: %s", prev_page_fps)
        logger.info("  curr fingerprints: %s", curr_page_fps)
        
    logger.info(
        "Issue diff: %d fixed, %d new, %d persisting, %d critical (prev had %d, current has %d)",
        len(fixed), len(new), len(persisting), len(critical), len(prev_issues), len(current_issues)
    )

    return {
        "has_previous": True,
        "fixed": fixed,
        "new": new,
        "persisting": persisting,
        "critical": critical,
    }
