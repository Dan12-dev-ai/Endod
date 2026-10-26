"""Payments through Chapa (https://developer.chapa.co).

A booking's payment is started here (``initialize``: Chapa returns a checkout
page) and accepted only after Chapa's own verify endpoint says it was paid,
for the expected amount, in birr. The webhook, the callback and the patient's
return to the app all just trigger that verification; none of them is trusted
on its own word, so a forged notification cannot confirm a booking.

Refunds use Chapa's refund API (``POST /v1/refund/{tx_ref}``, the same
secret-key bearer token; ``GET /v1/refund/{ref_id}/verify`` for its progress).
Each refund carries a unique ``reference`` of ours, so a retried request is
refused by Chapa rather than paid twice.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional

import httpx

from dedan_platform import partner_config

logger = logging.getLogger(__name__)

#: Replaced in tests with an httpx.MockTransport.
_transport: Optional[httpx.BaseTransport] = None


class ChapaError(RuntimeError):
    """Chapa refused the request or could not be reached."""


class ChapaNotConfigured(ChapaError):
    """No Chapa secret key is set."""


def _client() -> httpx.Client:
    key = partner_config.chapa_secret_key()
    if not key:
        raise ChapaNotConfigured("Payments are not set up yet.")
    return httpx.Client(
        base_url=partner_config.chapa_base_url(), timeout=20.0, transport=_transport,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )


def new_tx_ref() -> str:
    return "endod-" + secrets.token_hex(12)


def _local_phone(phone: Optional[str]) -> Optional[str]:
    """Chapa wants 09XXXXXXXX / 07XXXXXXXX."""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("251") and len(digits) == 12:
        return "0" + digits[3:]
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    return None


def initialize(tx_ref: str, amount: int, first_name: str, last_name: str, phone: Optional[str],
               return_url: str, callback_url: str, description: str = "Health visit booking") -> str:
    """Start a payment page. Returns Chapa's checkout URL."""
    body: Dict[str, Any] = {
        "amount": f"{Decimal(amount) / 100:.2f}",
        "currency": "ETB",
        "tx_ref": tx_ref,
        "first_name": (first_name or "Endod")[:50],
        "last_name": (last_name or "Patient")[:50],
        "return_url": return_url,
        "callback_url": callback_url,
        # Chapa limits the title to 16 characters and the description to plain text.
        "customization": {"title": "Endod Health", "description": description},
    }
    local = _local_phone(phone)
    if local:
        body["phone_number"] = local
    try:
        with _client() as client:
            response = client.post("/transaction/initialize", json=body)
    except httpx.HTTPError as exc:
        raise ChapaError("Chapa could not be reached. Please try again.") from exc
    data = _json(response)
    checkout = (data.get("data") or {}).get("checkout_url")
    if response.status_code >= 400 or data.get("status") != "success" or not checkout:
        logger.warning("chapa_initialize_failed status=%s message=%s", response.status_code, data.get("message"))
        raise ChapaError("The payment could not be started. Please try again.")
    return str(checkout)


def verify(tx_ref: str) -> Dict[str, Any]:
    """Chapa's record of the payment.

    Returns {"paid", "failed", "reversed", "known", "amount" (santim), "currency",
    "reference", "status"}. Raises ChapaError when Chapa could not give an
    answer (unreachable, overloaded, or our key refused): a deposit is never
    judged on a non-answer.
    """
    try:
        with _client() as client:
            response = client.get(f"/transaction/verify/{tx_ref}", timeout=10.0)
    except httpx.HTTPError as exc:
        raise ChapaError("Chapa could not be reached.") from exc
    if response.status_code >= 500 or response.status_code in (401, 403, 429):
        raise ChapaError(f"Chapa could not answer (HTTP {response.status_code}).")
    data = _json(response)
    record = data.get("data") or {}
    if response.status_code >= 400 or not record:
        # Chapa has no such payment (never started or abandoned before paying).
        return {"paid": False, "failed": response.status_code == 404, "reversed": False, "known": False,
                "amount": None, "currency": None, "reference": None, "status": "not_found"}
    if record.get("tx_ref") and record.get("tx_ref") != tx_ref:
        raise ChapaError("Chapa returned a different transaction.")
    status = str(record.get("status") or "").lower()
    try:
        amount = int((Decimal(str(record.get("amount"))) * 100).to_integral_value())
    except Exception:  # noqa: BLE001 -- malformed amount: not paid as far as we know
        amount = None
    return {
        "paid": status == "success",
        "failed": status in ("failed", "cancelled", "canceled"),
        "reversed": status in ("refunded", "reversed"),
        "known": True,
        "amount": amount,
        "currency": record.get("currency"),
        "reference": record.get("reference"),
        "status": status,
    }


class RefundRefused(ChapaError):
    """Chapa answered and said no (e.g. not refundable, not enough merchant
    balance, or a reference it has already seen): retrying will not help."""


def refund(tx_ref: str, amount: int, reason: str, reference: str) -> Dict[str, Any]:
    """Ask Chapa to refund ``amount`` santim of the payment ``tx_ref``.

    Returns {"ref_id", "payment_reference"} once Chapa accepted it. Raises
    RefundRefused when Chapa refused it, ChapaError when it gave no answer
    (unreachable, overloaded, or our key refused: worth retrying).
    """
    body = {"amount": f"{Decimal(amount) / 100:.2f}", "reason": (reason or "Refund")[:100],
            "reference": reference, "meta": {"source": "endod"}}
    try:
        with _client() as client:
            response = client.post(f"/refund/{tx_ref}", json=body)
    except httpx.HTTPError as exc:
        raise ChapaError("Chapa could not be reached.") from exc
    if response.status_code >= 500 or response.status_code in (401, 403, 408, 429):
        raise ChapaError(f"Chapa could not answer (HTTP {response.status_code}).")
    data = _json(response)
    record = data.get("data") or {}
    if response.status_code >= 400 or str(data.get("status") or "").lower() != "success":
        message = data.get("message")
        if isinstance(message, dict):
            message = "; ".join(f"{k}: {v}" for k, v in message.items())
        raise RefundRefused(f"Chapa refused the refund (HTTP {response.status_code}): {message or 'no reason'}"[:300])
    return {"ref_id": str(record.get("ref_id") or "")[:100] or None,
            "payment_reference": record.get("payment_reference")}


def verify_refund(ref_id: str) -> str:
    """Where Chapa is with a refund: initiated, processing, refunded or reversed
    (lower case; "unknown" when it does not say). Raises ChapaError on no answer."""
    try:
        with _client() as client:
            response = client.get(f"/refund/{ref_id}/verify", timeout=10.0)
    except httpx.HTTPError as exc:
        raise ChapaError("Chapa could not be reached.") from exc
    if response.status_code >= 500 or response.status_code in (401, 403, 408, 429):
        raise ChapaError(f"Chapa could not answer (HTTP {response.status_code}).")
    record = _json(response).get("data") or {}
    if response.status_code >= 400 or not isinstance(record, dict):
        return "unknown"
    return str(record.get("status") or "unknown").lower()


def signature_ok(raw_body: bytes, headers: Mapping[str, str]) -> bool:
    """Chapa signs webhooks with the webhook secret (HMAC-SHA256).

    ``x-chapa-signature`` signs the body; ``chapa-signature`` signs the secret
    itself. Either matching is accepted. With no secret configured, the
    webhook only triggers a verification with Chapa (which is the real check).
    """
    secret = partner_config.chapa_webhook_secret()
    if not secret:
        return True
    lowered = {k.lower(): v for k, v in headers.items()}
    by_body = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    by_secret = hmac.new(secret.encode(), secret.encode(), hashlib.sha256).hexdigest()
    for header, expected in (("x-chapa-signature", by_body), ("chapa-signature", by_secret)):
        given = lowered.get(header)
        if given and hmac.compare_digest(given.strip().lower(), expected):
            return True
    return False


def _json(response: httpx.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
