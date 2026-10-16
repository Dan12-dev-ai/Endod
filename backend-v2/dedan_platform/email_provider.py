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
* **Signed, expiring links** back into DEDAN rather than raw deep links, so a
  forwarded email cannot be replayed indefinitely.
"""

from __future__ import annotations

import abc
import hashlib
import hmac
import logging
import os
import ssl
import time
import uuid
from email.message import EmailMessage
from typing import Any, Dict, Optional

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


def build_provider() -> EmailProvider:
    """Choose a transport from configuration.

    Falls back to the console provider when SMTP is absent, which is what keeps a
    fresh checkout working with no mail server.
    """
    if os.getenv("SMTP_HOST", "").strip():
        return SmtpEmailProvider()
    logger.warning("SMTP_NOT_CONFIGURED_USING_CONSOLE_TRANSPORT")
    return ConsoleEmailProvider()


def signed_link(user_id: str, appointment_id: str, ttl_seconds: int = 86400) -> str:
    """Build a signed, expiring link back into DEDAN.

    HMAC-signed with the server secret so the link cannot be forged, and
    time-limited so a forwarded email stops working. Uses `compare_digest` on
    verification to avoid a timing oracle.
    """
    base = os.getenv("PUBLIC_WEB_URL", "http://localhost:3000").rstrip("/")
    expires_at = int(time.time()) + ttl_seconds
    message = f"{user_id}.{appointment_id}.{expires_at}".encode("utf-8")
    signature = hmac.new(_link_secret(), message, hashlib.sha256).hexdigest()
    return (
        f"{base}/appointments/{appointment_id}"
        f"?uid={user_id}&exp={expires_at}&sig={signature}"
    )


def verify_signed_link(user_id: str, appointment_id: str, expires_at: int, signature: str) -> bool:
    """Verify a signed link. Expiry is checked before the signature."""
    try:
        expires_at = int(expires_at)
    except (TypeError, ValueError):
        return False
    if expires_at < int(time.time()):
        return False
    message = f"{user_id}.{appointment_id}.{expires_at}".encode("utf-8")
    expected = hmac.new(_link_secret(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _link_secret() -> bytes:
    secret = (
        os.getenv("REALTIME_TOKEN_SECRET")
        or os.getenv("ADMIN_API_KEY")
        or "development-only-link-secret"
    )
    return secret.encode("utf-8")


def render_appointment_reminder(
    payload: Dict[str, Any],
    user_id: str,
    appointment_id: str,
) -> Dict[str, str]:
    """Render a reminder into subject + body.

    The body carries logistics only (when, where, how to change it). Any
    clinical context stays in DEDAN behind authentication.
    """
    when = payload.get("scheduled_at_display", "your scheduled time")
    kind = str(payload.get("appointment_type", "consultation")).replace("_", " ").title()
    location = payload.get("location") or payload.get("meeting_url") or "Details in DEDAN Health"
    link = signed_link(user_id, appointment_id)

    body = (
        f"Hello,\n\n"
        f"This is a reminder of your upcoming DEDAN Health appointment.\n\n"
        f"  Type:      {kind}\n"
        f"  When:      {when}\n"
        f"  Where:     {location}\n\n"
        f"View or change this appointment:\n{link}\n\n"
        f"This link is personal to you and expires in 24 hours.\n\n"
        f"— DEDAN Health\n"
        f"If you no longer wish to receive reminders, you can turn them off in "
        f"your notification settings."
    )
    return {"subject": APPOINTMENT_REMINDER_SUBJECT, "body": body}
