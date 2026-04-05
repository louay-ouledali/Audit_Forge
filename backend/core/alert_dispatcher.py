"""Forge Sentinel — multi-channel alert delivery (in-app, email, Slack)."""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import smtplib
from datetime import datetime, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
from sqlalchemy.orm import Session

from backend.models.notification import Notification

logger = logging.getLogger("auditforge.sentinel.alerts")


def _load_smtp_settings(db: Session) -> dict | None:
    """Read SMTP settings from app_settings table."""
    from backend.models.app_settings import AppSettings
    keys = ["smtp_host", "smtp_port", "smtp_username", "smtp_password", "smtp_from", "smtp_use_tls"]
    settings = {}
    for row in db.query(AppSettings).filter(AppSettings.key.in_(keys)).all():
        settings[row.key] = row.value
    if not settings.get("smtp_host"):
        return None
    return settings


def _get_base_url(db: Session) -> str:
    """Read the configured base URL (e.g. https://auditforge.example.com) from settings."""
    from backend.models.app_settings import AppSettings
    row = db.query(AppSettings).filter(AppSettings.key == "base_url").first()
    return (row.value.rstrip("/") if row and row.value else "")


def create_notification(
    db: Session,
    *,
    title: str,
    body: str | None = None,
    type: str = "warning",
    icon: str | None = None,
    mission_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    link: str | None = None,
    user_id: int | None = None,
) -> Notification:
    """Create an in-app notification."""
    n = Notification(
        user_id=user_id,
        mission_id=mission_id,
        title=title,
        body=body,
        type=type,
        icon=icon,
        entity_type=entity_type,
        entity_id=entity_id,
        link=link,
    )
    db.add(n)
    db.flush()
    return n


def _send_email_sync(
    smtp_settings: dict,
    to_addresses: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Send SMTP email synchronously (run via asyncio.to_thread to avoid blocking)."""
    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = smtp_settings.get("smtp_from", "auditforge@local")
        msg["To"] = to_addresses
        msg.attach(MIMEText(html_body, "html"))

        for filename, content, mime_type in (attachments or []):
            maintype, subtype = mime_type.split("/", 1) if "/" in mime_type else ("application", "octet-stream")
            part = MIMEBase(maintype, subtype)
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

        host = smtp_settings["smtp_host"]
        port = int(smtp_settings.get("smtp_port", "587"))
        use_tls = smtp_settings.get("smtp_use_tls", "true").lower() == "true"

        # Use context manager to ensure connection cleanup
        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                server.starttls()
                server.ehlo()  # Required after STARTTLS per RFC 3207

            username = smtp_settings.get("smtp_username")
            password = smtp_settings.get("smtp_password")
            if username and password:
                server.login(username, password)

            # Strip whitespace from addresses
            recipients = [a.strip() for a in to_addresses.split(",") if a.strip()]
            server.sendmail(msg["From"], recipients, msg.as_string())

        logger.info("Email alert sent to %s (attachments: %d)", to_addresses, len(attachments or []))
        return True
    except Exception as exc:
        logger.warning("Email alert failed: %s", exc)
        return False


async def send_email_alert(
    db: Session,
    *,
    to_addresses: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Send an SMTP email alert without blocking the event loop."""
    smtp = _load_smtp_settings(db)
    if not smtp:
        logger.warning("SMTP not configured — skipping email alert")
        return False
    return await asyncio.to_thread(
        _send_email_sync, smtp, to_addresses, subject, html_body, attachments
    )


async def send_slack_alert(
    *,
    webhook_url: str,
    text: str,
    blocks: list[dict] | None = None,
) -> bool:
    """Send a Slack webhook alert. Returns True on success."""
    if not webhook_url:
        return False

    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                logger.info("Slack alert sent")
                return True
            logger.warning("Slack alert returned %d: %s", resp.status_code, resp.text)
            return False
    except Exception as exc:
        logger.warning("Slack alert failed: %s", exc)
        return False


async def dispatch_alerts(
    db: Session,
    *,
    schedule,
    run,
    alerts: list[dict],
    report_attachment: tuple[str, bytes, str] | None = None,
    report_download_url: str | None = None,
) -> list[dict]:
    """Send alerts to all configured channels. Returns list of sent records.

    *report_attachment* is an optional (filename, bytes, mime_type) tuple
    attached to email alerts. *report_download_url* is included as a link
    in Slack and in-app notifications.
    """
    channels = json.loads(schedule.alert_channels_json or '["in_app"]')
    sent: list[dict] = []
    now_str = datetime.now(timezone.utc).isoformat() + "Z"

    # Build absolute report URL for external channels (email, Slack)
    base_url = _get_base_url(db)
    absolute_report_url: str | None = None
    if report_download_url:
        if report_download_url.startswith("http"):
            absolute_report_url = report_download_url
        elif base_url:
            absolute_report_url = f"{base_url}{report_download_url}"
        else:
            absolute_report_url = report_download_url  # fallback to relative

    # Determine notification user from schedule creator
    notify_user_id: int | None = getattr(schedule, "created_by", None)

    for alert in alerts:
        title = alert.get("title", "Sentinel Alert")
        body = alert.get("body", "")
        alert_type = alert.get("type", "warning")

        # Build link — append report download if available
        base_link = f"/missions/{schedule.mission_id}?tab=sentinel"
        notif_link = base_link

        if "in_app" in channels:
            notif_body = body
            if report_download_url:
                notif_body += f"\n\n📄 Report: {report_download_url}"
            create_notification(
                db,
                title=title,
                body=notif_body,
                type=alert_type,
                icon=alert.get("icon", "shield-alert"),
                mission_id=schedule.mission_id,
                entity_type="schedule",
                entity_id=schedule.id,
                link=notif_link,
                user_id=notify_user_id,
            )
            sent.append({"channel": "in_app", "at": now_str})

        if "email" in channels and schedule.alert_emails:
            # Escape user-controlled content to prevent XSS in email HTML
            safe_title = html_lib.escape(title)
            safe_body = html_lib.escape(body)
            safe_name = html_lib.escape(schedule.name)
            subject = f"[AuditForge Sentinel] {title}"
            html = f"<h2>{safe_title}</h2><p>{safe_body}</p>"
            if absolute_report_url:
                html += f'<p>📄 <a href="{html_lib.escape(absolute_report_url)}">Download Report</a></p>'
            html += f"<hr><p><small>Schedule: {safe_name} | Mission ID: {schedule.mission_id}</small></p>"
            email_attachments = [report_attachment] if report_attachment else None
            ok = await send_email_alert(
                db,
                to_addresses=schedule.alert_emails,
                subject=subject,
                html_body=html,
                attachments=email_attachments,
            )
            if ok:
                sent.append({"channel": "email", "at": now_str})

        if "slack" in channels and schedule.slack_webhook_url:
            slack_body = body
            if absolute_report_url:
                slack_body += f"\n\n📄 <{absolute_report_url}|Download Report>"
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"⚠️ {title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": slack_body}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Schedule: *{schedule.name}* | {now_str}"}]},
            ]
            ok = await send_slack_alert(webhook_url=schedule.slack_webhook_url, text=title, blocks=blocks)
            if ok:
                sent.append({"channel": "slack", "at": now_str})

    return sent
