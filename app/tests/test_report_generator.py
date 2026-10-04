import pytest
from app import report_generator
from app.report_generator import generate
from app.models import AuditResult, Issue

def test_html_autoescaping_and_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(report_generator.settings, "REPORTS_DIR", str(tmp_path))

    # Setup fixture with known HTML tags in fix-text
    issue = Issue(
        category="Accessibility",
        issue_type="unlabeled_form_controls",
        severity="critical",
        page_url="https://example.com",
        message="Form control missing label",
        details="ID: email_input",
        how_to_fix="Associate each <input>, <select> with a <label> (for/id) or aria-label"
    )
    
    result = AuditResult(
        site="https://example.com",
        pages_crawled=1,
        started_at="2026-07-07T12:00:00Z",
        finished_at="2026-07-07T12:01:00Z",
        issues=[issue],
        stats={"broken_pages": 0, "total_resources": 10},
        analysis={
            "overall_health_score": 85,
            "category_scores": [
                {"name": "Accessibility", "score": 85, "grade": "B", "total": 1, "affected_pages": 1, "impact": "High", "recommendation": "Fix it"}
            ],
            "action_plan": [
                {
                    "priority": "0-30 days",
                    "issue": "Fix inputs",
                    "severity": "critical",
                    "why_it_matters": "Accessibility",
                    "recommended_action": "Use <label>",
                    "affected_count": 1,
                    "sample_urls": ["https://example.com"]
                }
            ],
            "top_priorities": [],
            "executive_summary": "Test summary",
            "performance_kpis": {
                "average_response_ms": 100,
                "median_response_ms": 90,
                "p95_response_ms": 150,
                "slow_pages": 0,
                "average_page_kb": 50,
                "largest_page_kb": 100
            },
            "scope": {"status_codes": "200: 1"},
            "methodology": "Test methodology",
            "limitations": ["Test limitation"]
        },
        ai_summary={
            "executive_summary": "AI Summary",
            "overall_health_score": "85",
            "top_priorities": []
        },
        page_details=[
            {"url": "https://example.com", "status_code": 200, "response_time_ms": 100, "size_kb": 50, "word_count": 200, "h1_count": 1, "title": "Home"}
        ]
    )
    
    diff = {"has_previous": False, "fixed": [], "new": [issue.to_dict()], "critical": [issue.to_dict()], "persisting": []}
    
    # Generate HTML
    out = generate(result, diff)
    html = out["html"]
    
    # 1. Assert autoescaping worked: literal tags should be escaped
    assert "&lt;input&gt;" in html
    assert "&lt;select&gt;" in html
    assert "&lt;label&gt;" in html
    assert "<input>" not in html.split("Associate each ")[1] # Ensure the actual phrase is escaped
    
    # 2. Assert all sections are present (not truncated mid-render)
    assert "1. Executive Summary" in html
    assert "7. Prioritized Remediation Plan" in html
    assert "16. Methodology &amp; Limitations" in html
