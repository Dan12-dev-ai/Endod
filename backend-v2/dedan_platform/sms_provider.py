"""
SMS delivery.

Providers are pluggable behind one interface, like `email_provider`:

* `SmsEthiopiaProvider` -- https://smsethiopia.com, selected when
  ``SMSETHIOPIA_API_KEY`` is set.
* `ConsoleSmsProvider` -- logs instead of sending. Development only: in
  production `build_provider` refuses it, because a console "send" that reports
  success is exactly how verification codes silently never reach a patient.

Failures are raised as `SmsProviderError` with the provider's status and a
short excerpt of its reply, so "the SMS is not arriving" can be diagnosed from
the logs. The API key and the message text are never logged by the real
provider (the text carries the verification code).
"""

from __future__ import annotations

import abc
import logging
import os
from typing import Optional

from dedan_platform.phone import mask, to_msisdn

logger = logging.getLogger(__name__)

SMS_ETHIOPIA_URL = os.getenv("SMSETHIOPIA_API_URL", "https://smsethiopia.com/api/sms/send")
SMS_TIMEOUT_SECONDS = float(os.getenv("SMS_TIMEOUT_SECONDS", "15"))
#: Shown in every text the platform sends.
BRAND_NAME = os.getenv("SMS_BRAND_NAME", "Endod Health")


class SmsProviderError(RuntimeError):
    """The message was not accepted for delivery."""


class SmsNotConfiguredError(SmsProviderError):
    """No real SMS provider is configured where one is required."""


class SmsProvider(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def send(self, phone: str, text: str) -> Optional[str]:
        """Send ``text`` to an E.164 ``phone``. Returns the provider's message id
        when it gives one. Raises `SmsProviderError` if not accepted."""


class ConsoleSmsProvider(SmsProvider):
    """Development stand-in: writes the message to the log instead of sending."""

    name = "console"

    def send(self, phone: str, text: str) -> Optional[str]:
        # The text (with its code) is logged deliberately: this provider only
        # exists so a developer can complete the flow without an SMS account.
        logger.warning("sms_console_delivery to=%s text=%r", mask(phone), text)
        return None


class SmsEthiopiaProvider(SmsProvider):
    name = "smsethiopia"

    def __init__(self, api_key: str, url: str = SMS_ETHIOPIA_URL) -> None:
        self.api_key = api_key
        self.url = url

    def send(self, phone: str, text: str) -> Optional[str]:
        import httpx

        try:
            response = httpx.post(
                self.url,
                headers={"KEY": self.api_key, "Content-Type": "application/json"},
                json={"msisdn": to_msisdn(phone), "text": text},
                timeout=SMS_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("sms_send_network_error to=%s error=%s", mask(phone), type(exc).__name__)
            raise SmsProviderError(f"SMS provider unreachable: {type(exc).__name__}") from exc

        excerpt = response.text[:300]
        if response.status_code >= 400:
            logger.error(
                "sms_send_rejected to=%s status=%s body=%r", mask(phone), response.status_code, excerpt
            )
            raise SmsProviderError(f"SMS provider returned HTTP {response.status_code}")

        # A 200 is not proof of acceptance: some gateways report failures (no
        # credit, unapproved sender) in the body. Check it when it is JSON.
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            status = str(body.get("status", "")).lower()
            if body.get("success") is False or body.get("error") or status in {"error", "failed", "fail"}:
                logger.error("sms_send_rejected to=%s status=200 body=%r", mask(phone), excerpt)
                raise SmsProviderError("SMS provider rejected the message")
            message_id = body.get("message_id") or body.get("messageId") or body.get("id")
        else:
            message_id = None
        logger.info("sms_sent to=%s provider=smsethiopia", mask(phone))
        return str(message_id) if message_id else None


def render_sms_reminder(payload: dict) -> str:
    """An appointment reminder short enough for one or two SMS segments.

    Only the time. An SMS preview is visible on a lock screen, and the
    appointment type and place are free text that can reveal the kind of care
    (a psychiatric hospital, a clinic's department), so neither is included;
    the app shows the details after sign-in.
    """
    from dedan_platform.email_provider import format_appointment_time

    return (
        f"{BRAND_NAME} reminder: you have an appointment on {format_appointment_time(payload)}. "
        "Open the app for details."
    )


def build_provider() -> SmsProvider:
    """The configured provider. Fails closed in production without a key."""
    api_key = os.getenv("SMSETHIOPIA_API_KEY", "").strip()
    if api_key:
        return SmsEthiopiaProvider(api_key)
    from app.core.config import get_settings

    # The process environment first, then settings, which also read `.env`.
    environment = os.getenv("ENVIRONMENT") or get_settings().ENVIRONMENT
    if environment.strip().lower() == "production":
        raise SmsNotConfiguredError("SMSETHIOPIA_API_KEY is not set; SMS cannot be sent.")
    return ConsoleSmsProvider()
