"""
Verifies that Playwright Chromium can launch and generate a PDF.

Run this on cPanel after `python -m playwright install chromium`.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from app.pdf_generator import html_to_pdf


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        html_path = Path(tmp) / "playwright-check.html"
        pdf_path = Path(tmp) / "playwright-check.pdf"
        html_path.write_text(
            "<!doctype html><html><body>"
            "<h1>Playwright OK</h1>"
            "<p>Chromium launched and generated this PDF.</p>"
            "</body></html>",
            encoding="utf-8",
        )

        html_to_pdf(str(html_path), str(pdf_path))
        size = pdf_path.stat().st_size
        if size <= 0:
            raise RuntimeError("PDF was created but is empty.")

    print("Playwright Chromium check passed: PDF generation works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
