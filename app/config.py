"""
Central configuration for the AI Website Health Monitor.
All values are loaded from environment variables (.env file) so nothing
sensitive (API keys, SMTP credentials) is hard-coded.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_list(name: str) -> list[str]:
    val = os.getenv(name, "")
    return [item.strip() for item in val.split(",") if item.strip()]


class Settings:
    # ---- Target site ----
    SITE_BASE_URL: str = os.getenv("SITE_BASE_URL", "https://www.amipi.com").rstrip("/")
    MAX_PAGES: int = int(os.getenv("MAX_PAGES", "200"))
    CRAWL_DELAY_SECONDS: float = float(os.getenv("CRAWL_DELAY_SECONDS", "0.5"))
    USE_PLAYWRIGHT_FOR_JS: bool = _get_bool("USE_PLAYWRIGHT_FOR_JS", True)
    CHECK_OUTBOUND_LINKS: bool = _get_bool("CHECK_OUTBOUND_LINKS", True)
    CHECK_OUTBOUND_LINKS_ON_MOBILE: bool = _get_bool("CHECK_OUTBOUND_LINKS_ON_MOBILE", False)
    REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
    USER_AGENT: str = os.getenv(
        "USER_AGENT",
        "AIWebsiteHealthMonitor/1.0 (+internal audit bot; contact: hiranya10@gmail.com)",
    )

    # ---- AI API (NVIDIA Nemotron) ----
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")
    AI_API_BASE: str = os.getenv("AI_API_BASE", "https://integrate.api.nvidia.com/v1")
    AI_MODEL: str = os.getenv("AI_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

    # ---- Google PageSpeed Insights ----
    PAGESPEED_API_KEY: str = os.getenv("PAGESPEED_API_KEY", "")

    # ---- External SEO Data (Optional) ----
    SEO_API_KEY: str = os.getenv("SEO_API_KEY", "")
    DATAFORSEO_LOGIN: str = os.getenv("DATAFORSEO_LOGIN", "")
    DATAFORSEO_PASSWORD: str = os.getenv("DATAFORSEO_PASSWORD", "")
    DATAFORSEO_LOCATION_CODE: int = int(os.getenv("DATAFORSEO_LOCATION_CODE", "2840"))
    DATAFORSEO_LANGUAGE_CODE: str = os.getenv("DATAFORSEO_LANGUAGE_CODE", "en")

    # ---- Email ----
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_TIMEOUT: int = int(os.getenv("SMTP_TIMEOUT", "120"))
    SMTP_USE_SSL: bool = _get_bool("SMTP_USE_SSL", os.getenv("SMTP_PORT", "587") == "465")
    SMTP_USE_STARTTLS: bool = _get_bool("SMTP_USE_STARTTLS", not SMTP_USE_SSL)
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    EMAIL_FROM: str = os.getenv("EMAIL_FROM", "")
    EMAIL_RECIPIENTS: list[str] = _get_list("EMAIL_RECIPIENTS")

    # ---- Scheduler ----
    WEEKLY_CRON: str = os.getenv("WEEKLY_CRON", "0 6 * * MON")
    WEEKLY_CRON_TIMEZONE: str = os.getenv("WEEKLY_CRON_TIMEZONE", "America/New_York")
    SCHEDULER_TEST_MODE: bool = _get_bool("SCHEDULER_TEST_MODE", False)

    # ---- Playwright ----
    PLAYWRIGHT_CHROMIUM_ARGS: list[str] = _get_list("PLAYWRIGHT_CHROMIUM_ARGS")

    # ---- Storage ----
    REPORTS_DIR: str = os.getenv("REPORTS_DIR", "reports")


settings = Settings()
