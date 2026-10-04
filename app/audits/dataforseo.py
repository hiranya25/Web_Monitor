"""
Shared DataForSEO REST helpers.

DataForSEO authenticates with HTTP Basic auth. For compatibility with the
existing deployment config, SEO_API_KEY may contain "login:password".
Separate DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD values are also supported.
"""
from __future__ import annotations

import logging
import base64
from urllib.parse import urlparse

import requests

from app.config import settings

logger = logging.getLogger("dataforseo")

API_BASE = "https://api.dataforseo.com/v3"
PLACEHOLDER_PARTS = {
    "your_dataforseo_login",
    "your_dataforseo_password",
    "your_base64_basic_token",
    "your_api_key_here",
}


def normalize_domain(domain: str) -> str:
    """Return a DataForSEO domain target without protocol or leading www."""
    if not domain:
        return ""
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    host = parsed.netloc or parsed.path
    return host.lower().removeprefix("www.").strip("/")


def _is_placeholder(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return not normalized or normalized in PLACEHOLDER_PARTS or normalized.startswith("your_")


def _valid_auth_pair(login: str, password: str) -> bool:
    return not _is_placeholder(login) and not _is_placeholder(password)


def get_auth() -> tuple[str, str] | None:
    login = getattr(settings, "DATAFORSEO_LOGIN", "")
    password = getattr(settings, "DATAFORSEO_PASSWORD", "")
    if _valid_auth_pair(login, password):
        return login, password

    api_key = getattr(settings, "SEO_API_KEY", "")
    if ":" in api_key:
        login, password = api_key.split(":", 1)
        if _valid_auth_pair(login, password):
            return login, password

    try:
        decoded = base64.b64decode(api_key, validate=True).decode("utf-8")
        if ":" in decoded:
            login, password = decoded.split(":", 1)
            if _valid_auth_pair(login, password):
                return login, password
    except Exception:
        pass

    if api_key and not _is_placeholder(api_key):
        logger.warning(
            "SEO_API_KEY is set, but DataForSEO requires login:password or Base64 Basic credentials."
        )
    return None


def post(path: str, payload: dict, timeout: int = 30) -> dict | None:
    auth = get_auth()
    if not auth:
        return None

    try:
        resp = requests.post(
            f"{API_BASE}{path}",
            auth=auth,
            json=[payload],
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            logger.warning("DataForSEO HTTP error %s for %s", resp.status_code, path)
            return None

        data = resp.json()
        if data.get("status_code") != 20000:
            logger.warning(
                "DataForSEO API error for %s: %s %s",
                path,
                data.get("status_code"),
                data.get("status_message"),
            )
            return None
        return data
    except Exception as exc:
        logger.error("DataForSEO request failed for %s: %s", path, exc)
        return None


def first_result(data: dict | None) -> dict:
    if not isinstance(data, dict):
        return {}
    tasks = data.get("tasks") or []
    if not tasks:
        return {}
    task = tasks[0] if isinstance(tasks[0], dict) else {}
    if task.get("status_code") != 20000:
        logger.warning(
            "DataForSEO task error: %s %s",
            task.get("status_code"),
            task.get("status_message"),
        )
        return {}
    result = task.get("result") or []
    return result[0] if result and isinstance(result[0], dict) else {}
