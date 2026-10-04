from app.audits.backlinks import _parse_backlink_response
from app.audits import dataforseo


def test_parse_se_ranking_summary_response():
    data = {
        "status_code": 20000,
        "tasks": [
            {
                "status_code": 20000,
                "result": [
                    {
                        "target": "amipi.com",
                        "backlinks": 1458,
                        "referring_domains": 90,
                    }
                ],
            }
        ],
    }

    assert _parse_backlink_response(data) == {
        "total_backlinks": 1458,
        "referring_domains": 90,
        "data_source": "DataForSEO Backlinks",
    }


def test_parse_legacy_flat_response_shape():
    data = {
        "backlinks_count": "42",
        "referring_domains": "7",
    }

    assert _parse_backlink_response(data) == {
        "total_backlinks": 42,
        "referring_domains": 7,
        "data_source": "DataForSEO Backlinks",
    }


def test_parse_unexpected_response_returns_none():
    assert _parse_backlink_response({"summary": []}) is None


def test_dataforseo_ignores_placeholder_credentials(monkeypatch):
    monkeypatch.setattr(dataforseo.settings, "DATAFORSEO_LOGIN", "")
    monkeypatch.setattr(dataforseo.settings, "DATAFORSEO_PASSWORD", "")
    monkeypatch.setattr(
        dataforseo.settings,
        "SEO_API_KEY",
        "your_dataforseo_login:your_dataforseo_password",
    )

    assert dataforseo.get_auth() is None


def test_dataforseo_accepts_login_password(monkeypatch):
    monkeypatch.setattr(dataforseo.settings, "DATAFORSEO_LOGIN", "login")
    monkeypatch.setattr(dataforseo.settings, "DATAFORSEO_PASSWORD", "password")
    monkeypatch.setattr(dataforseo.settings, "SEO_API_KEY", "")

    assert dataforseo.get_auth() == ("login", "password")
