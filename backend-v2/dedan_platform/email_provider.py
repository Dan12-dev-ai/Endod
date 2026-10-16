"""
Email delivery (spec §17, §27).

Providers are pluggable behind one interface. The default is SMTP; a
console/logging provider exists so the reminder pipeline can be exercised
end-to-end without sending real mail to real patients.

Content rules enforced here, not left to templates
---------------------------------------------------
* **No clinical detail in the subject.** Subjects are rendered into inboxes, lock
  screens and notification previews. A subject like "Your diabetes consultation
  tomorrow" discloses a diagnosis to anyone glancing at a phone.
* **No clinical detail in the payload** the reminder queue carries.
* **No credentials or identifiers in links.** The link opens the portal's
  appointments page, behind sign-in; a forwarded email grants nothing.
"""

from __future__ import annotations

import abc
import logging
import os
import ssl
import uuid
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Generic subject. Deliberately carries no condition, provider or department.
APPOINTMENT_REMINDER_SUBJECT = "DEDAN Health — Appointment Reminder"

#: SMTP socket timeout. Bounded so a hung mail server cannot hold a worker slot
#: and stall the whole queue behind it.
SMTP_TIMEOUT_SECONDS = int(os.getenv("SMTP_TIMEOUT_SECONDS", "20"))


class EmailProviderError(RuntimeError):
    """Delivery failed. The queue turns this into a retry or a permanent failure."""


class EmailProvider(abc.ABC):
    """Contract for outbound email."""

    @abc.abstractmethod
    def send(
        self,
        to_address: str,
        subject: str,
        body: str,
        correlation_id: Optional[str] = None,
    ) -> Optional[str]:
        """Deliver one message. Raise `EmailProviderError` on failure.

        Returns an optional provider-side message reference. It is recorded when
        present and never required: a transport that offers no receipt returns
        None, and its absence must not be read as a delivery failure.
        """


class ConsoleEmailProvider(EmailProvider):
    """Logs instead of sending.

    The default when SMTP is unconfigured. This is explicitly a *development*
    transport: it never contacts a patient, so the UI can say reminders are
    queued without any risk of emailing a real address during testing.
    """

    def send(self, to_address, subject, body, correlation_id=None):
        # The address is masked: reminder logs are read by support staff and
        # should not become a list of patient emails.
        masked = _mask_email(to_address)
        logger.info(
            "email_dispatched_console",
            extra={"to": masked, "subject": subject, "correlation_id": correlation_id},
        )
        return None


class SmtpEmailProvider(EmailProvider):
    """Real SMTP delivery.

    TLS is required unless explicitly disabled for a local test relay; an
    unencrypted send of clinical appointment details is not acceptable.
    """

    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST", "")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.username = os.getenv("SMTP_USERNAME", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.sender = os.getenv("SMTP_FROM", "no-reply@dedanhealth.org")
        self.use_tls = os.getenv("SMTP_TLS", "true").strip().lower() in ("1", "true", "yes")

    def send(self, to_address, subject, body, correlation_id=None):
        if not self.host:
            raise EmailProviderError("SMTP_HOST is not configured.")
        import smtplib

        # A locally generated Message-ID gives the queue a stable reference to
        # cite when a patient asks whether a reminder was actually sent.
        domain = self.sender.partition("@")[2] or "dedanhealth.org"
        message_id = f"<{uuid.uuid4().hex}@{domain}>"

        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to_address
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
                if self.use_tls:
                    # An explicit default context verifies the server's
                    # certificate and hostname. Without one, `starttls()`
                    # encrypts but trusts any certificate, so anyone on the
                    # network path could capture the SMTP password and every
                    # patient email.
                    smtp.starttls(context=ssl.create_default_context())
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(message)
        except Exception as exc:
            # Message only -- never the credentials or the full error payload.
            raise EmailProviderError(f"SMTP delivery failed: {type(exc).__name__}") from exc
        return message_id


def _mask_email(address: str) -> str:
    if "@" not in address:
        return "***"
    local, _, domain = address.partition("@")
    keep = local[:1] if local else ""
    return f"{keep}***@{domain}"


class EmailNotConfiguredError(EmailProviderError):
    """No mail server is configured where one is required."""


def _is_production() -> bool:
    # The process environment first, then settings, which also read `.env`: a
    # production ENVIRONMENT set only in `.env` was missed by os.getenv alone,
    # and the console transport then marked reminders SENT undelivered.
    from app.core.config import get_settings

    value = os.getenv("ENVIRONMENT") or get_settings().ENVIRONMENT
    return value.strip().lower() == "production"


def build_provider() -> EmailProvider:
    """Choose a transport from configuration.

    Falls back to the console provider when SMTP is absent, which is what keeps a
    fresh checkout working with no mail server -- outside production only. In
    production the console "send" marked every reminder SENT while nothing was
    delivered, so there it refuses instead and the reminders wait in the queue.
    """
    if os.getenv("SMTP_HOST", "").strip():
        return SmtpEmailProvider()
    if _is_production():
        raise EmailNotConfiguredError("SMTP_HOST is not set; reminders cannot be delivered.")
    logger.warning("SMTP_NOT_CONFIGURED_USING_CONSOLE_TRANSPORT")
    return ConsoleEmailProvider()


def portal_link() -> Optional[str]:
    """Where a patient manages appointments, or ``None`` if not configured.

    The link used to point at ``/appointments/{id}`` on ``localhost:3000`` by
    default: a page that does not exist, on a host no patient can reach. A
    reminder without a link is better than one with a broken link.
    """
    base = os.getenv("PUBLIC_WEB_URL", "").strip().rstrip("/")
    if not base:
        return None
    path = os.getenv("PORTAL_APPOINTMENTS_PATH", "/interview").strip() or "/"
    return f"{base}/{path.lstrip('/')}"


def format_appointment_time(payload: Dict[str, Any]) -> str:
    """The appointment time in the appointment's own timezone.

    The template used to read a ``scheduled_at_display`` key that nothing ever
    set, so every reminder said "When: your scheduled time".
    """
    raw = payload.get("scheduled_at")
    if not raw:
        return "your scheduled time"
    try:
        when = datetime.fromisoformat(str(raw))
    except ValueError:
        return "your scheduled time"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    zone_name = payload.get("timezone") or "UTC"
    try:
        local = when.astimezone(ZoneInfo(zone_name))
    except (ZoneInfoNotFoundError, ValueError):
        local, zone_name = when.astimezone(timezone.utc), "UTC"
    return f"{local.strftime('%A %d %B %Y, %H:%M')} ({zone_name})"


def render_appointment_reminder(
    payload: Dict[str, Any],
    user_id: str,
    appointment_id: str,
) -> Dict[str, str]:
    """Render a reminder into subject + body.

    The body carries logistics only (when, where, how to change it). Any
    clinical context stays in DEDAN behind authentication.
    """
    when = format_appointment_time(payload)
    kind = str(payload.get("appointment_type", "consultation")).replace("_", " ").title()
    location = payload.get("location") or payload.get("meeting_url") or "Details in DEDAN Health"
    link = portal_link()
    manage = (
        f"View or change this appointment (sign in first):\n{link}\n\n" if link
        else "You can view or change this appointment in DEDAN Health.\n\n"
    )

    body = (
        f"Hello,\n\n"
        f"This is a reminder of your upcoming DEDAN Health appointment.\n\n"
        f"  Type:      {kind}\n"
        f"  When:      {when}\n"
        f"  Where:     {location}\n\n"
        f"{manage}"
        f"— DEDAN Health\n"
        f"If you no longer wish to receive reminders, you can turn them off in "
        f"your notification settings."
    )
    return {"subject": APPOINTMENT_REMINDER_SUBJECT, "body": body}
