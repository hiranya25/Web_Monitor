import os
import logging
from app.config import settings

logger = logging.getLogger("pdf_generator")

def html_to_pdf(html_path: str, pdf_path: str):
    """
    Converts a local HTML file to a PDF using Playwright, falling back to pure-Python xhtml2pdf if Playwright fails.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=settings.PLAYWRIGHT_CHROMIUM_ARGS)
            page = browser.new_page()
            page.goto(f"file://{os.path.abspath(html_path)}", wait_until="networkidle")
            page.pdf(path=pdf_path, format="A4", print_background=True)
            browser.close()
            return
    except Exception as exc:
        logger.warning(f"Playwright PDF generation failed ({exc}). Trying pure-Python xhtml2pdf fallback...")

    # Pure-Python fallback (doesn't require Chromium or system dependencies)
    try:
        from xhtml2pdf import pisa
        with open(html_path, "r", encoding="utf-8") as html_file:
            html_content = html_file.read()
        with open(pdf_path, "wb") as pdf_file:
            pisa_status = pisa.CreatePDF(html_content, dest=pdf_file)
        if not pisa_status.err:
            logger.info("PDF successfully generated using xhtml2pdf fallback!")
            return
        else:
            logger.error("xhtml2pdf encountered errors during PDF rendering.")
    except Exception as fallback_exc:
        logger.error(f"xhtml2pdf PDF generation failed: {fallback_exc}")

