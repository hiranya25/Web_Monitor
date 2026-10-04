import playwright.sync_api

from app.audits import broken_links, performance
from app.config import settings
from app.crawler import WebsiteCrawler, _looks_like_file
from app.models import PageRecord


class _FakeResponse:
    def __init__(self, url, status_code=200, content_type="application/pdf", body=b"%PDF-1.4"):
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        self.content = body
        self.text = body.decode("latin-1")

    def close(self):
        pass


def _crawler_returning(monkeypatch, response):
    crawler = WebsiteCrawler(base_url="https://www.example.com")
    monkeypatch.setattr(crawler.session, "get", lambda url, **kwargs: response)
    return crawler


def test_looks_like_file():
    assert _looks_like_file("https://www.amipi.com/downloads/application.pdf")
    assert _looks_like_file("https://www.amipi.com/downloads/AML.PDF?v=2")
    assert not _looks_like_file("https://www.amipi.com/diamonds/")
    assert not _looks_like_file("https://www.amipi.com/certified.php")


def test_pdf_url_skips_browser_and_is_not_an_error(monkeypatch):
    monkeypatch.setattr(settings, "USE_PLAYWRIGHT_FOR_JS", True)
    url = "https://www.example.com/downloads/application.pdf"
    crawler = _crawler_returning(monkeypatch, _FakeResponse(url))
    monkeypatch.setattr(crawler, "_fetch_with_playwright", lambda u: (_ for _ in ()).throw(AssertionError("browser used")))

    record = crawler._fetch(url)

    assert record.status_code == 200
    assert record.error is None
    assert record.is_non_html_document


def test_browser_abort_on_pdf_without_extension_falls_back_to_http_result(monkeypatch):
    # Chromium raises net::ERR_ABORTED when navigating to a direct PDF response.
    def _aborting_playwright():
        raise RuntimeError('Page.goto: net::ERR_ABORTED at https://www.example.com/download?id=7')

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", _aborting_playwright)
    url = "https://www.example.com/download?id=7"
    crawler = _crawler_returning(monkeypatch, _FakeResponse(url))

    record = crawler._fetch_with_playwright(url)

    assert record.status_code == 200
    assert record.error is None
    assert record.content_type == "application/pdf"


def test_browser_failure_still_reported_when_http_fetch_also_fails(monkeypatch):
    def _aborting_playwright():
        raise RuntimeError("net::ERR_CONNECTION_REFUSED")

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", _aborting_playwright)
    crawler = WebsiteCrawler(base_url="https://www.example.com")

    def _failing_get(url, **kwargs):
        import requests
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(crawler.session, "get", _failing_get)

    record = crawler._fetch_with_playwright("https://www.example.com/page")

    assert record.error == "net::ERR_CONNECTION_REFUSED"


def test_pdf_documents_produce_no_broken_link_or_performance_issues():
    pdf = PageRecord(
        url="https://www.example.com/downloads/aml.pdf",
        status_code=200,
        content_type="application/pdf",
        response_time_ms=8000,
        size_bytes=6 * 1024 * 1024,
    )

    assert broken_links.run([pdf], check_outbound_links=False) == []
    assert performance.run([pdf]) == []


def test_missing_pdf_is_still_reported_as_broken():
    missing = PageRecord(
        url="https://www.example.com/downloads/old.pdf",
        status_code=404,
        content_type="text/html",
    )

    issues = broken_links.run([missing], check_outbound_links=False)

    assert [i.message for i in issues] == ["Page returned HTTP 404"]
