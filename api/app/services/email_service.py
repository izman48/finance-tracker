"""Outbound email via SMTP.

Configured entirely from environment (SMTP_HOST etc. — see core.config). When
SMTP is not configured the message is logged instead of sent, so flows like
password reset stay testable in development.
"""
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True if handed to an SMTP server."""
    settings = get_settings()

    if not settings.smtp_host:
        logger.warning(
            "SMTP not configured — email to %s not sent. Subject: %r. Body:\n%s",
            to, subject, body,
        )
        return False

    msg = EmailMessage()
    msg["From"] = settings.smtp_from or settings.smtp_username
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)
    logger.info("Sent email to %s: %s", to, subject)
    return True
