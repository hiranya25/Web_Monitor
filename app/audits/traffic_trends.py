"""Organic traffic and ranking trends using DataForSEO Labs."""
from __future__ import annotations
import logging
from app.config import settings
from app.audits import dataforseo

logger = logging.getLogger("traffic_trends")

def _to_int(value) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _parse_domain_rank_response(data: dict | None) -> dict | None:
    result = dataforseo.first_result(data)
    items = result.get("items") or []
    if not items or not isinstance(items[0], dict):
        return None

    metrics = items[0].get("metrics") or {}
    organic = metrics.get("organic") or {}
    return {
        "estimated_traffic": _to_int(organic.get("etv")),
        "ranking_keywords": _to_int(organic.get("count")),
        "data_source": "DataForSEO Labs Google (US)",
    }

def fetch_traffic_data(domain: str) -> dict | None:
    target = dataforseo.normalize_domain(domain)
    data = dataforseo.post(
        "/dataforseo_labs/google/domain_rank_overview/live",
        {
            "target": target,
            "location_code": settings.DATAFORSEO_LOCATION_CODE,
            "language_code": settings.DATAFORSEO_LANGUAGE_CODE,
            "limit": 1,
        },
    )
    traffic_data = _parse_domain_rank_response(data)
    if data and traffic_data is None:
        logger.warning("DataForSEO Labs API returned an unexpected response shape")
    return traffic_data
