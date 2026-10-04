"""
Email Delivery Service
-------------------------
Sends the generated HTML report to EMAIL_RECIPIENTS via SMTP
(works with Gmail/Outlook/any standard SMTP+STARTTLS provider).
"""
from __future__ import annotations
import logging
import os
import smtplib
import ssl
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger("email_service")


def send_report(html_body: str, subject: str | None = None) -> bool:
    return send_report_with_attachments(html_body, subject, None)


def _open_smtp_connection():
    context = ssl.create_default_context()
    if settings.SMTP_USE_SSL:
        return smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT,
            context=context,
        )

    server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT)
    server.ehlo()
    if settings.SMTP_USE_STARTTLS:
        server.starttls(context=context)
        server.ehlo()
    return server


def send_report_with_attachments(html_body: str, subject: str | None, attachments: list[str] | None) -> bool:
    if not settings.SMTP_HOST or not settings.EMAIL_RECIPIENTS:
        logger.warning("SMTP not configured or no recipients set — skipping email send.")
        return False

    subject = subject or "Weekly Website Health Report — AMIPI"

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_FROM or settings.SMTP_USERNAME
    msg["To"] = ", ".join(settings.EMAIL_RECIPIENTS)
    
    # Send a short body message instead of the full HTML report
    short_body = (
        "<html><body>"
        "<p>Hello,</p>"
        "<p>Please find the latest Weekly Website Health Report for AMIPI attached.</p>"
        "<p>Attachments:<br>"
        "1. <b>PDF Report</b> (Executive Summary, Scorecard, and Prioritized Fixes)<br>"
        "2. <b>CSV Spreadsheet</b> (Complete list of all URL-level technical findings)</p>"
        "<br><p><i>Generated automatically by the AI Website Health Monitor.</i></p>"
        "</body></html>"
    )
    
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(short_body, "html"))
    msg.attach(alt)

    if attachments:
        for filepath in attachments:
            if filepath and os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    file_ext = os.path.splitext(filepath)[1].lower().strip('.')
                    subtype = "pdf" if file_ext == "pdf" else ("csv" if file_ext == "csv" else "octet-stream")
                    attachment_part = MIMEApplication(f.read(), _subtype=subtype)
                    filename = os.path.basename(filepath)
                    attachment_part.add_header('Content-Disposition', 'attachment', filename=filename)
                    msg.attach(attachment_part)
            else:
                logger.warning("Attachment file not found: %s", filepath)

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Sending report email to %s via %s:%s using %s (attempt %d/%d)...",
                settings.EMAIL_RECIPIENTS,
                settings.SMTP_HOST,
                settings.SMTP_PORT,
                "SMTP_SSL" if settings.SMTP_USE_SSL else ("STARTTLS" if settings.SMTP_USE_STARTTLS else "plain SMTP"),
                attempt,
                max_retries,
            )
            with _open_smtp_connection() as server:
                if settings.SMTP_USERNAME:
                    server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                server.sendmail(msg["From"], settings.EMAIL_RECIPIENTS, msg.as_string())
            logger.info("Report email sent successfully to %s", settings.EMAIL_RECIPIENTS)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to send report email (attempt %d/%d): %s", attempt, max_retries, exc)
            if attempt < max_retries:
                time.sleep(5)
            else:
                logger.error("Email automation failed after 3 attempts.")
                return False
    return False
