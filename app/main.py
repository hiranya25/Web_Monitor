"""
FastAPI Application
----------------------
Endpoints:
  GET  /health                -> liveness check
  POST /audit/run             -> trigger a full audit immediately (runs in background)
  GET  /audit/status/{job_id} -> check status of a triggered run
  GET  /audit/latest          -> latest report as JSON
  GET  /audit/latest/html     -> latest report as rendered HTML

Run locally:
    uvicorn app.main:app --reload

The weekly scheduler starts automatically on app startup.
"""
from __future__ import annotations
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.pipeline import run_full_audit
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("main")

app = FastAPI(
    title="AI Website Health Monitor",
    description="Automated crawling, SEO/technical/performance auditing, "
                "and AI-summarized weekly reporting for amipi.com.",
    version="1.0.0",
)

_executor = ThreadPoolExecutor(max_workers=2)
_jobs: dict[str, dict] = {}  # job_id -> {"status": "running"|"done"|"failed", "error": str|None}


@app.on_event("startup")
def _on_startup():
    start_scheduler()


@app.on_event("shutdown")
def _on_shutdown():
    stop_scheduler()


@app.get("/health")
def health():
    return {"status": "ok", "site": settings.SITE_BASE_URL}


def _run_job(job_id: str, send_email: bool):
    try:
        _jobs[job_id]["status"] = "running"
        run_full_audit(send_email=send_email)
        _jobs[job_id]["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        logger.exception("Audit job %s failed", job_id)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["error"] = str(exc)


@app.post("/audit/run")
def trigger_audit(send_email: bool = False):
    """Kick off a full audit in the background. Returns a job_id to poll."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "queued", "error": None}
    _executor.submit(_run_job, job_id, send_email)
    return {"job_id": job_id, "status": "queued"}


@app.get("/audit/status/{job_id}")
def job_status(job_id: str):
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Unknown job_id")
    return {"job_id": job_id, **_jobs[job_id]}


@app.get("/audit/latest")
def latest_report_json():
    import json
    path = os.path.join(settings.REPORTS_DIR, "latest.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No report generated yet. POST /audit/run first.")
    with open(path, "r", encoding="utf-8") as f:
        return JSONResponse(content=json.load(f))


@app.get("/audit/latest/html", response_class=HTMLResponse)
def latest_report_html():
    path = os.path.join(settings.REPORTS_DIR, "latest.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No report generated yet. POST /audit/run first.")
    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


import datetime
from fastapi.responses import FileResponse
from app.pdf_generator import html_to_pdf
from app.email_service import send_report_with_attachments

@app.get("/audit/latest/pdf")
def latest_report_pdf():
    html_path = os.path.join(settings.REPORTS_DIR, "latest.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="No report generated yet.")
    pdf_path = os.path.join(settings.REPORTS_DIR, "latest.pdf")
    
    try:
        html_to_pdf(html_path, pdf_path)
    except Exception as e:
        logger.error(f"PDF Generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF. Make sure Playwright browsers are installed.")

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    filename = f"{date_str} Amipi Health Check.pdf"
    return FileResponse(pdf_path, media_type='application/pdf', filename=filename)


@app.post("/audit/email")
def trigger_email():
    html_path = os.path.join(settings.REPORTS_DIR, "latest.html")
    if not os.path.exists(html_path):
        raise HTTPException(status_code=404, detail="No report generated yet.")
    
    pdf_path = os.path.join(settings.REPORTS_DIR, "latest.pdf")
    try:
        html_to_pdf(html_path, pdf_path)
    except Exception as e:
        logger.error(f"PDF Generation failed: {e}")
        # Ignore and just send without PDF if needed, or fail. We'll fail here.
        raise HTTPException(status_code=500, detail="Failed to generate PDF. Make sure Playwright browsers are installed.")
    
    with open(html_path, "r", encoding="utf-8") as f:
        html_body = f.read()
        
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    subject = f"{date_str} Amipi Health Check"
    
    attachments = [pdf_path]
    csv_path = os.path.join(settings.REPORTS_DIR, "latest.csv")
    if os.path.exists(csv_path):
        attachments.append(csv_path)
    
    success = send_report_with_attachments(html_body, subject, attachments)
    if success:
        return {"status": "sent"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send email.")


# ---------------------------------------------------------------------
# Frontend dashboard (static SPA). Mounted last so it never shadows the
# API routes above. html=True serves index.html for unmatched paths.
# ---------------------------------------------------------------------
_FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
