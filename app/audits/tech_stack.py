"""
Technology Stack & Infrastructure Fingerprinting
----------------------------------------------
Detects web server, CMS, libraries, and checks basic DNS infrastructure (DMARC/SPF).
"""
from __future__ import annotations
import re
import socket
import subprocess
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app.models import PageRecord, Issue
from app.config import settings

def _get_txt_records(domain: str) -> list[str]:
    try:
        # Use dig to get TXT records, falling back nicely if dig is missing
        result = subprocess.run(["dig", "+short", "TXT", domain], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return [line.strip('"') for line in result.stdout.splitlines()]
    except Exception:
        pass
    return []

def run(pages: list[PageRecord]) -> tuple[list[Issue], dict]:
    issues: list[Issue] = []
    
    tech_data = {
        "web_server": "Unknown",
        "hosting_ip": "Unknown",
        "cms": "Unknown",
        "libraries": [],
        "spf_record": False,
        "dmarc_record": False
    }

    homepage = next((p for p in pages if p.url == settings.SITE_BASE_URL), None)
    if not homepage:
        return issues, tech_data
        
    parsed_url = urlparse(settings.SITE_BASE_URL)
    domain = parsed_url.netloc.replace("www.", "")

    # 1. Web Server (from headers)
    try:
        resp = requests.head(settings.SITE_BASE_URL, timeout=10)
        server = resp.headers.get("Server", "Unknown")
        if server:
            tech_data["web_server"] = server
    except Exception:
        pass

    # 2. Hosting IP
    try:
        ip = socket.gethostbyname(parsed_url.netloc)
        tech_data["hosting_ip"] = ip
    except Exception:
        pass

    # 3. DNS TXT records for SPF and DMARC
    txt_records = _get_txt_records(domain)
    for txt in txt_records:
        if "v=spf1" in txt:
            tech_data["spf_record"] = True
            
    dmarc_records = _get_txt_records(f"_dmarc.{domain}")
    for txt in dmarc_records:
        if "v=DMARC1" in txt:
            tech_data["dmarc_record"] = True

    if not tech_data["spf_record"]:
        issues.append(Issue(
            category="Security", issue_type="missing_spf", severity="medium", page_url=settings.SITE_BASE_URL,
            message="Missing SPF Record in DNS",
            how_to_fix="Add an SPF TXT record to your DNS to prevent email spoofing and improve deliverability."
        ))
        
    if not tech_data["dmarc_record"]:
        issues.append(Issue(
            category="Security", issue_type="missing_dmarc", severity="low", page_url=settings.SITE_BASE_URL,
            message="Missing DMARC Record in DNS",
            how_to_fix="Add a DMARC TXT record to specify how receivers should handle emails failing SPF/DKIM checks."
        ))

    # 4. CMS and JS Libraries (from homepage HTML)
    if homepage.html:
        soup = BeautifulSoup(homepage.html, "lxml")
        
        # Check for common CMS signatures
        generator = soup.find("meta", attrs={"name": "generator"})
        if generator and generator.get("content"):
            tech_data["cms"] = generator.get("content")
        elif "wp-content" in homepage.html:
            tech_data["cms"] = "WordPress"
        elif "cdn.shopify.com" in homepage.html:
            tech_data["cms"] = "Shopify"
        elif "wix.com" in homepage.html:
            tech_data["cms"] = "Wix"
        elif "squarespace" in homepage.html:
            tech_data["cms"] = "Squarespace"
            
        # Check for libraries
        libs = set()
        for script in soup.find_all("script", src=True):
            src = script["src"].lower()
            if "jquery" in src: libs.add("jQuery")
            if "bootstrap" in src: libs.add("Bootstrap")
            if "react" in src: libs.add("React")
            if "vue" in src: libs.add("Vue.js")
            if "angular" in src: libs.add("Angular")
            if "gtag" in src or "google-analytics" in src: libs.add("Google Analytics")
            if "gtm.js" in src: libs.add("Google Tag Manager")
            
        for link in soup.find_all("link", rel="stylesheet", href=True):
            href = link["href"].lower()
            if "bootstrap" in href: libs.add("Bootstrap CSS")
            if "tailwind" in href: libs.add("Tailwind CSS")
            if "fontawesome" in href or "font-awesome" in href: libs.add("Font Awesome")
            
        tech_data["libraries"] = sorted(list(libs))

    return issues, tech_data
