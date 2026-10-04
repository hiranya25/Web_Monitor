from app.models import Issue, PageRecord
from app import ai_remediation
from app.ai_remediation import enrich_issues_with_remediation

def test_enrich_issues_reconstruction():
    # Simulate a raw finding dict that contains all the fields, including issue_type
    sample_finding = {
        "category": "SEO",
        "issue_type": "missing_robots_txt",
        "severity": "medium",
        "page_url": "https://example.com",
        "message": "robots.txt is missing",
        "details": None
    }
    
    # 1. Ensure we can build an Issue from this dict without raising an error
    # Because Issue requires explicit kwargs, this works properly.
    issue = Issue(**sample_finding)
    assert issue.issue_type == "missing_robots_txt"
    
    # 2. Enrich the issue with remediation (simulating the pipeline)
    enriched_list = enrich_issues_with_remediation([issue])
    enriched_issue = enriched_list[0]
    
    # 3. Confirm it didn't raise and the values are correct
    assert enriched_issue.issue_type == "missing_robots_txt"
    assert "https://example.com/robots.txt" in enriched_issue.how_to_fix
    assert "Sitemap:" in enriched_issue.how_to_fix
    
    # 4. Confirm it doesn't mutate the original
    assert issue.how_to_fix is None


def test_enrich_issues_uses_page_specific_context():
    page = PageRecord(
        url="https://example.com/about",
        html="""
        <html><head><title>About Us</title></head>
        <body>
          <h1>Industrial Automation Solutions</h1>
          <p>Example Company designs control panels, automation systems, and engineering services for manufacturers.</p>
          <img src="/images/control-panel.jpg">
        </body></html>
        """,
    )
    title_issue = Issue(
        category="Metadata",
        issue_type="title_length_incorrect",
        severity="low",
        page_url=page.url,
        message="Title length is 8 chars (recommended 50-60)",
        details="About Us",
    )
    alt_issue = Issue(
        category="ALT Tags",
        issue_type="missing_alt_attribute",
        severity="low",
        page_url=page.url,
        message="Image missing ALT attribute",
        details="/images/control-panel.jpg",
    )

    enriched = enrich_issues_with_remediation([title_issue, alt_issue], pages=[page])

    assert "https://example.com/about" in enriched[0].how_to_fix
    assert "Current title" in enriched[0].how_to_fix
    assert "Recommended replacement" in enriched[0].how_to_fix
    assert "/images/control-panel.jpg" in enriched[1].how_to_fix
    assert "Recommended ALT text" in enriched[1].how_to_fix


def test_enrich_issues_reuses_page_context(monkeypatch):
    page = PageRecord(url="https://example.com/about", html="<html><body><h1>About</h1></body></html>")
    issues = [
        Issue(
            category="Metadata",
            issue_type="missing_meta_description",
            severity="medium",
            page_url=page.url,
            message="Missing meta description",
        ),
        Issue(
            category="SEO",
            issue_type="missing_canonical_tag",
            severity="medium",
            page_url=page.url,
            message="Missing canonical tag",
        ),
    ]

    original = ai_remediation._extract_context
    calls = []

    def counted_extract_context(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(ai_remediation, "_extract_context", counted_extract_context)

    enriched = enrich_issues_with_remediation(issues, pages=[page])

    assert len(enriched) == 2
    assert len(calls) == 1
