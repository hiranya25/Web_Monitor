import pytest
from app.issue_diff import compute_diff

def test_compute_diff():
    # Legacy snapshot representing an old run (before issue_type was fully adopted)
    old_snapshot = {
        "issues": [
            {
                "category": "Metadata", 
                "page_url": "https://example.com/about", 
                "message": "Missing meta description",
                # no issue_type present in old snapshot
            },
            {
                "category": "Metadata", 
                "page_url": "https://example.com/contact", 
                "message": "Missing <title> tag",
                # no issue_type present in old snapshot
            },
            {
                "category": "Performance", 
                "page_url": "https://example.com", 
                "message": "Very slow response time: 2776ms", 
                # no issue_type present in old snapshot
            }
        ]
    }
    
    # New snapshot representing the current run
    new_snapshot = {
        "issues": [
            {
                "category": "Metadata",
                "page_url": "https://example.com/about",
                "message": "Missing meta description",
                "issue_type": "missing_meta_description" 
                # This should match the legacy one! -> PERSISTING
            },
            {
                "category": "Performance",
                "page_url": "https://example.com/products",
                "message": "Very slow response time: 3100ms",
                "issue_type": "slow_response_time",
                "severity": "critical"
                # This was NOT in the old snapshot -> NEW
            }
            # The contact page title tag is missing in the new snapshot -> FIXED
        ]
    }
    
    diff_result = compute_diff(new_snapshot["issues"], [old_snapshot])
    
    assert diff_result["has_previous"] is True
    
    fixed_urls = [i["page_url"] for i in diff_result["fixed"]]
    new_urls = [i["page_url"] for i in diff_result["new"]]
    persisting_urls = [i["page_url"] for i in diff_result["persisting"]]
    
    # Assert counts
    assert len(diff_result["fixed"]) == 2  # The contact page title, and the homepage performance
    assert len(diff_result["new"]) == 1    # The products page performance
    assert len(diff_result["persisting"]) == 1 # The about page meta description
    
    # Ensure zero overlap by URL. Issue dicts themselves are not hashable.
    assert not set(fixed_urls).intersection(set(new_urls))
    assert not set(fixed_urls).intersection(set(persisting_urls))
    assert not set(new_urls).intersection(set(persisting_urls))
    
    # Explicitly check what was assigned where
    assert "https://example.com/contact" in fixed_urls
    assert "https://example.com" in fixed_urls
    assert "https://example.com/products" in new_urls
    assert "https://example.com/about" in persisting_urls
