"""
Pipeline Orchestrator
------------------------
Runs the full audit end-to-end:
  crawl -> run all audit modules -> AI analysis -> generate report -> email

This is what both the FastAPI "/audit/run" endpoint and the weekly
scheduler call.
"""
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone

from app.audits import alt_tags, broken_links, metadata, performance, seo_checks, security, llm_readability
from app.config import settings
from app.crawler import WebsiteCrawler
from app.audits import comprehensive
from app.detailed_analysis import build as build_detailed_analysis
from app.ai_analysis import analyze
from app.ai_remediation import enrich_issues_with_remediation
from app.report_generator import generate
from app.email_service import send_report_with_attachments
from app.pdf_generator import html_to_pdf
from app.issue_diff import compute_diff, _load_previous_reports
from app.models import AuditResult
from app.audits import lighthouse
from app.audits import waterfall
from app.audits import social
from app.audits import tech_stack
from app.audits import backlinks
from app.audits import traffic_trends
from urllib.parse import urlparse

logger = logging.getLogger("pipeline")


def run_full_audit(send_email: bool = True) -> AuditResult:
    started_at = datetime.now(timezone.utc).isoformat()
    logger.info("Starting audit for %s", settings.SITE_BASE_URL)

    # 0. Load previous reports BEFORE we overwrite latest.json
    previous_reports = _load_previous_reports()

    def _run_stage(label: str, func):
        start = time.perf_counter()
        logger.info("Starting stage: %s", label)
        result = func()
        logger.info("Finished stage: %s (%.1fs)", label, time.perf_counter() - start)
        return result

    # Helper to run all audits on a set of pages
    def _run_audits(pages, pass_name: str, check_outbound_links: bool) -> tuple[list, dict]:
        logger.info(
            "Running %s audit modules on %d pages (outbound link checks: %s)",
            pass_name,
            len(pages),
            "on" if check_outbound_links else "off",
        )
        found_issues = []
        found_issues += _run_stage(
            f"{pass_name}: broken links/resources",
            lambda: broken_links.run(pages, check_outbound_links=check_outbound_links),
        )
        found_issues += _run_stage(f"{pass_name}: metadata", lambda: metadata.run(pages))
        found_issues += _run_stage(f"{pass_name}: alt tags", lambda: alt_tags.run(pages))
        
        seo_issues, seo_data = _run_stage(
            f"{pass_name}: SEO checks",
            lambda: seo_checks.run(pages, base_url=settings.SITE_BASE_URL),
        )
        found_issues += seo_issues
        
        found_issues += _run_stage(f"{pass_name}: performance", lambda: performance.run(pages))
        found_issues += _run_stage(f"{pass_name}: waterfall", lambda: waterfall.run(pages))
        found_issues += _run_stage(f"{pass_name}: comprehensive", lambda: comprehensive.run(pages))
        found_issues += _run_stage(f"{pass_name}: security", lambda: security.run(pages))
        found_issues += _run_stage(
            f"{pass_name}: LLM readability",
            lambda: llm_readability.run(pages, base_url=settings.SITE_BASE_URL),
        )
        
        # Social run handles its own issues, but we also want the data. 
        # We'll just run it outside this helper for the desktop pass to capture the data.
        logger.info("%s audit modules produced %d issues.", pass_name, len(found_issues))
        return found_issues, seo_data

    # 1. Crawl & Audit (Desktop Pass)
    pages_desktop = _run_stage("desktop crawl", lambda: WebsiteCrawler(viewport="desktop").crawl())
    logger.info("Crawled %d desktop pages", len(pages_desktop))
    issues_desktop, keyword_data = _run_audits(
        pages_desktop,
        pass_name="desktop",
        check_outbound_links=settings.CHECK_OUTBOUND_LINKS,
    )
    
    # Run social and tech stack audits only on desktop
    social_issues, social_data = _run_stage("desktop: social", lambda: social.run(pages_desktop))
    tech_issues, tech_data = _run_stage("desktop: tech stack", lambda: tech_stack.run(pages_desktop))
    
    issues_desktop += social_issues
    issues_desktop += tech_issues
    
    for issue in issues_desktop:
        issue.viewport = "desktop"

    # 2. Crawl & Audit (Mobile Pass)
    pages_mobile = _run_stage("mobile crawl", lambda: WebsiteCrawler(viewport="mobile").crawl())
    logger.info("Crawled %d mobile pages", len(pages_mobile))
    issues_mobile, _ = _run_audits(
        pages_mobile,
        pass_name="mobile",
        check_outbound_links=settings.CHECK_OUTBOUND_LINKS and settings.CHECK_OUTBOUND_LINKS_ON_MOBILE,
    )
    for issue in issues_mobile:
        issue.viewport = "mobile"

    # Combine issues and pages
    all_pages = pages_desktop + pages_mobile
    issues = issues_desktop + issues_mobile

    # 3. Enrich with AI-generated or cached "how to fix" text
    issues = _run_stage(
        f"remediation enrichment for {len(issues)} issues",
        lambda: enrich_issues_with_remediation(issues, pages=all_pages),
    )

    # 4. Fetch Lighthouse lab data for homepage
    logger.info("Fetching Lighthouse metrics for base URL...")
    lab_metrics = _run_stage("Lighthouse/PageSpeed metrics", lambda: lighthouse.run_for_url(settings.SITE_BASE_URL))
    
    # 5. Fetch External SEO Data (Backlinks & Traffic)
    parsed_domain = urlparse(settings.SITE_BASE_URL).netloc.replace("www.", "")
    backlink_data = _run_stage("DataForSEO backlinks", lambda: backlinks.fetch_backlink_data(parsed_domain))
    traffic_data = _run_stage("DataForSEO traffic trends", lambda: traffic_trends.fetch_traffic_data(parsed_domain))

    # Calculate resource breakdown for homepage (desktop)
    resource_breakdown = {"script": 0, "stylesheet": 0, "image": 0, "font": 0, "document": 0, "other": 0}
    homepage_record = next((p for p in pages_desktop if p.url == settings.SITE_BASE_URL or p.url == settings.SITE_BASE_URL + "/"), None)
    
    if homepage_record:
        if homepage_record.resources:
            for res in homepage_record.resources:
                t = res.get("type", "other")
                if t in resource_breakdown:
                    resource_breakdown[t] += res.get("size_bytes", 0)
                else:
                    resource_breakdown["other"] += res.get("size_bytes", 0)
        else:
            # Fallback for requests crawler: parse HTML and do HEAD requests
            from bs4 import BeautifulSoup
            import requests
            from urllib.parse import urljoin
            import concurrent.futures
            
            if homepage_record.html:
                soup = BeautifulSoup(homepage_record.html, "lxml")
                resource_breakdown["document"] = len(homepage_record.html.encode("utf-8"))
                
                def get_size(url, res_type):
                    if not url.startswith("http"):
                        url = urljoin(settings.SITE_BASE_URL, url)
                    try:
                        r = requests.head(url, timeout=3, allow_redirects=True)
                        size = int(r.headers.get("content-length", 0))
                        resource_breakdown[res_type] += size
                    except Exception:
                        pass
                        
                with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                    for img in soup.find_all("img", src=True):
                        executor.submit(get_size, img["src"], "image")
                    for script in soup.find_all("script", src=True):
                        executor.submit(get_size, script["src"], "script")
                    for link in soup.find_all("link", rel="stylesheet", href=True):
                        executor.submit(get_size, link["href"], "stylesheet")
    
    has_resources = any(v > 0 for v in resource_breakdown.values())
    if not has_resources:
        resource_breakdown = None

    result = AuditResult(
        site=settings.SITE_BASE_URL,
        pages_crawled=len(pages_desktop), # We report unique URLs crawled, which is approx desktop pages length
        started_at=started_at,
        finished_at=datetime.now(timezone.utc).isoformat(),
        issues=issues,
        lab_metrics=lab_metrics,
        stats={
            "avg_response_time_ms_desktop": round(
                sum(p.response_time_ms for p in pages_desktop) / len(pages_desktop), 1
            ) if pages_desktop else 0,
            "avg_response_time_ms_mobile": round(
                sum(p.response_time_ms for p in pages_mobile) / len(pages_mobile), 1
            ) if pages_mobile else 0,
            "broken_pages": sum(1 for p in pages_desktop if p.status_code and p.status_code >= 400),
            "resource_breakdown": resource_breakdown,
            "social_data": social_data,
            "keyword_data": keyword_data,
            "tech_data": tech_data,
            "backlink_data": backlink_data,
            "traffic_data": traffic_data,
        },
    )

    # 5. AI analysis (NVIDIA Nemotron, with rule-based fallback)
    result.ai_summary = _run_stage(
        "AI executive analysis",
        lambda: analyze(issues, site=settings.SITE_BASE_URL, pages_crawled=len(pages_desktop)),
    )
    result.analysis, result.page_details = _run_stage(
        "detailed analysis",
        lambda: build_detailed_analysis(pages_desktop, issues),
    )

    # 4. Compute issue diff (fixed / new / critical)
    issue_dicts = [i.to_dict() for i in issues]
    diff = _run_stage("issue diff", lambda: compute_diff(issue_dicts, previous_reports))

    # 5. Generate report (HTML + JSON, saved to REPORTS_DIR)
    report = _run_stage("report generation", lambda: generate(result, diff=diff))
    logger.info("Report generated: %s", report["html_path"])

    # 5. Email delivery
    if send_email:
        subject = f"Weekly Website Health Report — {settings.SITE_BASE_URL} ({datetime.now().strftime('%b %d, %Y')})"
        attachments = []
        
        pdf_path = report["html_path"].replace(".html", ".pdf")
        try:
            logger.info("Generating PDF attachment...")
            html_to_pdf(report["html_path"], pdf_path)
            attachments.append(pdf_path)
        except Exception as e:
            logger.error("Failed to generate PDF for email: %s", e)

        if "csv_path" in report and report["csv_path"]:
            attachments.append(report["csv_path"])

        success = send_report_with_attachments(report["html"], subject=subject, attachments=attachments)
        if not success:
            raise RuntimeError("Email delivery failed after maximum retries.")

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    run_full_audit(send_email=False)
