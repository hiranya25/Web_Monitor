import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from app.models import Issue, PageRecord

def run(pages: list[PageRecord], base_url: str) -> list[Issue]:
    issues = []
    
    # 1. llms.txt check
    llms_url = urljoin(base_url, "/llms.txt")
    has_llms = False
    try:
        r = requests.head(llms_url, timeout=5)
        has_llms = (r.status_code == 200)
    except Exception:
        pass
        
    if not has_llms:
        issues.append(Issue(
            category="LLM/GEO",
            issue_type="missing_llms_txt",
            severity="medium",
            page_url=llms_url,
            message="Missing llms.txt file",
            details="Adding an llms.txt file helps generative AI engines understand your site content."
        ))

    # 2. Organization/Person schema (check homepage)
    homepage = next((p for p in pages if p.url == base_url or p.url == base_url + "/"), None)
    if homepage and homepage.html:
        soup = BeautifulSoup(homepage.html, "lxml")
        schemas = soup.find_all("script", type="application/ld+json")
        has_org_person = False
        for s in schemas:
            if s.string and any(t in s.string for t in ["Organization", "Person"]):
                has_org_person = True
                break
                
        if not has_org_person:
            issues.append(Issue(
                category="LLM/GEO",
                issue_type="missing_entity_schema",
                severity="medium",
                page_url=homepage.url,
                message="Missing Organization or Person schema",
                details="Entity schema is critical for Knowledge Graphs used by LLMs to answer queries."
            ))
            
    # 3. Content accessibility (JS dependence)
    for page in pages:
        if not page.html or page.error or (page.status_code and page.status_code >= 400):
            continue
        soup = BeautifulSoup(page.html, "lxml")
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.extract()
        text = soup.get_text(separator=" ", strip=True)
        if len(text) < 300: # Very thin content, likely heavily JS-dependent or blank
            issues.append(Issue(
                category="LLM/GEO",
                issue_type="thin_static_content",
                severity="low",
                page_url=page.url,
                message="Thin static HTML content (Possible JS dependency)",
                details="Page has very little text in raw HTML. Non-rendering LLM crawlers may fail to read your content if it relies on client-side rendering."
            ))
            
    return issues
