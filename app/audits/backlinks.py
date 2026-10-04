"""Detailed backlink analysis using DataForSEO Backlinks Summary."""
from __future__ import annotations

import logging

from app.audits import dataforseo

logger = logging.getLogger("backlinks")


def _to_int(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _first_present(data: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in data:
            return _to_int(data[key])
    return 0


def _summary_payload(data) -> dict:
    if not isinstance(data, dict):
        return {}

    result = dataforseo.first_result(data)
    if result:
        return result

    summary = data.get("summary")
    if isinstance(summary, list):
        if not summary:
            return {}
        first = summary[0]
        return first if isinstance(first, dict) else {}
    if isinstance(summary, dict):
        return summary

    return data


def _parse_backlink_response(data) -> dict | None:
    summary = _summary_payload(data)
    if not summary:
        return None

    total_backlinks = _first_present(
        summary,
        ("total_backlinks", "backlinks_count", "backlinks"),
    )
    referring_domains = _first_present(
        summary,
        ("referring_domains", "refdomains", "referring_domains_count"),
    )

    return {
        "total_backlinks": total_backlinks,
        "referring_domains": referring_domains,
        "data_source": "DataForSEO Backlinks",
    }


def fetch_backlink_data(domain: str) -> dict | None:
    target = dataforseo.normalize_domain(domain)
    data = dataforseo.post(
        "/backlinks/summary/live",
        {
            "target": target,
            "include_subdomains": True,
            "exclude_internal_backlinks": True,
            "backlinks_status_type": "live",
            "internal_list_limit": 10,
        },
    )
    backlink_data = _parse_backlink_response(data)
    if data and backlink_data is None:
        logger.warning("DataForSEO Backlinks API returned an unexpected response shape")
    return backlink_data
