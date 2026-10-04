"""
Weekly Scheduler
-------------------
Uses APScheduler's CronTrigger (parsed from WEEKLY_CRON, default:
pipeline automatically, so no one has to remember to run it manually.
"""
from __future__ import annotations
import fcntl
import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from datetime import timezone, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.pipeline import run_full_audit

logger = logging.getLogger("scheduler")

def _scheduler_timezone():
    try:
        return ZoneInfo(settings.WEEKLY_CRON_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning("Unknown WEEKLY_CRON_TIMEZONE=%s; falling back to UTC.", settings.WEEKLY_CRON_TIMEZONE)
        return timezone.utc


scheduler = BackgroundScheduler(timezone=_scheduler_timezone())

def _cron_trigger_from_string(cron_str: str) -> CronTrigger:
    minute, hour, day, month, day_of_week = cron_str.split()
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
        timezone=_scheduler_timezone(),
    )

def _retry_email_only():
    try:
        logger.info("Scheduler attempting to resend email for previously completed audit...")
        import os
        from app.pdf_generator import html_to_pdf
        from app.email_service import send_report_with_attachments
        
        html_path = os.path.join(settings.REPORTS_DIR, "latest.html")
        pdf_path = os.path.join(settings.REPORTS_DIR, "latest.pdf")
        csv_path = os.path.join(settings.REPORTS_DIR, "latest.csv")
        
        if not os.path.exists(html_path):
            raise RuntimeError("Cannot retry email: latest.html missing.")
            
        if not os.path.exists(pdf_path):
            html_to_pdf(html_path, pdf_path)
            
        with open(html_path, "r", encoding="utf-8") as f:
            html_body = f.read()
            
        attachments = [pdf_path]
        if os.path.exists(csv_path):
            attachments.append(csv_path)
            
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        subject = f"Weekly Website Health Report — {settings.SITE_BASE_URL} ({date_str})"
        
        success = send_report_with_attachments(html_body, subject, attachments)
        if not success:
            raise RuntimeError("Email delivery failed after maximum retries.")
            
    except Exception as exc:
        logger.error("Email retry job failed again: %s", exc)
        _schedule_retry(_retry_email_only)

def _schedule_retry(func):
    retry_time = datetime.now(timezone.utc) + timedelta(hours=1)
    retry_id = f"retry_audit_{int(retry_time.timestamp())}"
    logger.info("Scheduling a retry attempt in 1 hour (at %s)", retry_time)
    scheduler.add_job(
        func=func,
        trigger='date',
        run_date=retry_time,
        id=retry_id,
        replace_existing=True
    )

def _safe_run_audit():
    try:
        logger.info("Scheduler triggered automatic audit job.")
        os.makedirs(settings.REPORTS_DIR, exist_ok=True)
        lock_path = os.path.join(settings.REPORTS_DIR, ".weekly_audit.lock")
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                logger.warning("Another scheduled audit is already running; skipping this execution.")
                return

            run_full_audit(send_email=True)
    except Exception as exc:
        logger.error("Scheduled audit job failed: %s", exc, exc_info=True)
        # If it was ONLY an email failure, just retry the email next time
        if str(exc) == "Email delivery failed after maximum retries.":
            _schedule_retry(_retry_email_only)
        else:
            # Otherwise, the crawl/AI failed, we need to run everything again
            _schedule_retry(_safe_run_audit)

def start_scheduler():
    if scheduler.running:
        logger.info("Scheduler already running; leaving existing jobs in place.")
        return

    if settings.SCHEDULER_TEST_MODE:
        trigger = IntervalTrigger(minutes=1, timezone=_scheduler_timezone())
        logger.info("Scheduler started in TESTING MODE (runs every 1 minute).")
    else:
        trigger = _cron_trigger_from_string(settings.WEEKLY_CRON)
        logger.info(
            "Scheduler started. Weekly audit cron: %s (%s)",
            settings.WEEKLY_CRON,
            settings.WEEKLY_CRON_TIMEZONE,
        )

    scheduler.add_job(
        func=_safe_run_audit,
        trigger=trigger,
        id="weekly_website_audit",
        replace_existing=True,
    )
    
    scheduler.start()
    
    # Print next run time
    job = scheduler.get_job("weekly_website_audit")
    if job and job.next_run_time:
        logger.info("Next scheduled run time: %s", job.next_run_time)


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
