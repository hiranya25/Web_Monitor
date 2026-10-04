"""
Social Profile Presence Check
-----------------------------
Scans the page HTML (specifically the homepage) for outbound links to major social networks
and checks for the presence of tracking pixels like Facebook Pixel.
Reports them as findings.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup

from app.models import PageRecord, Issue
from app.config import settings

def run(pages: list[PageRecord]) -> tuple[list[Issue], dict]:
    issues: list[Issue] = []
    social_data = {
        "Facebook": {"found": False, "url": None},
        "Instagram": {"found": False, "url": None},
        "LinkedIn": {"found": False, "url": None},
        "YouTube": {"found": False, "url": None},
        "X/Twitter": {"found": False, "url": None},
        "Facebook Pixel": {"found": False, "url": None}
    }

    # Usually, we only care about the homepage having social links, or we check if the site overall has them.
    # We will check all pages, but to avoid spam, we might only report missing links once.
    # For a yes/no check, we'll scan the homepage (or the base URL).
    
    homepage = next((p for p in pages if p.url == settings.SITE_BASE_URL), None)
    if not homepage or not homepage.html:
        return issues, social_data
        
    soup = BeautifulSoup(homepage.html, "lxml")
    
    # 1. Check outbound links for social profiles
    social_platforms = {
        "Facebook": r"facebook\.com",
        "Instagram": r"instagram\.com",
        "LinkedIn": r"linkedin\.com",
        "YouTube": r"youtube\.com",
        "X/Twitter": r"twitter\.com|x\.com"
    }
    
    found_profiles = {}
    
    for a in soup.find_all("a", href=True):
        href = a["href"]
        for platform, pattern in social_platforms.items():
            if re.search(pattern, href, re.IGNORECASE):
                if platform not in found_profiles:
                    found_profiles[platform] = href
                    
    for platform, pattern in social_platforms.items():
        if platform in found_profiles:
            social_data[platform]["found"] = True
            social_data[platform]["url"] = found_profiles[platform]
        else:
            issues.append(Issue(
                category="Social", issue_type=f"missing_{platform.lower().replace('/', '_')}_link", severity="low", page_url=homepage.url,
                message=f"Missing {platform} profile link on homepage",
                how_to_fix=f"Add a link to your {platform} profile in the header or footer to build trust and social proof."
            ))

    # 2. Check for Facebook Pixel
    # FB Pixel typically contains 'connect.facebook.net/en_US/fbevents.js' or 'fbq('
    pixel_found = False
    for script in soup.find_all("script"):
        src = script.get("src", "")
        content = script.string or ""
        if "fbevents.js" in src or "fbq(" in content:
            pixel_found = True
            break
            
    if pixel_found:
        social_data["Facebook Pixel"]["found"] = True
        social_data["Facebook Pixel"]["url"] = "Detected"
    else:
        issues.append(Issue(
            category="Social", issue_type="missing_fb_pixel", severity="low", page_url=homepage.url,
            message="No Facebook Pixel tracking detected",
            how_to_fix="If you plan to run Facebook or Instagram ads, install the Meta Pixel to track conversions and build retargeting audiences."
        ))

    return issues, social_data
