"""SMS over HTTP: the inbound webhook for the short code, and the patient's PIN in the app.

Inbound (``router``, served only by the ``sms-inbound`` service, main_sms.py,
published by nginx at ``https://api.endod-health.com/sms/v1/...``; docs/sms.md):

* ``POST /sms/v1/inbound/africastalking/{secret}``: Africa's Talking's
  incoming-message callback (form fields ``from``, ``to``, ``text``, ``id``,
  ``date``, ``linkId``). Africa's Talking does not sign callbacks, so the
  shared secret (``SMS_INBOUND_SECRET``) is the last part of the URL
  registered with them. The reply goes back from the short code through
  their SMS API, after the answer (a background task).
* ``POST /sms/v1/inbound/generic``: any other gateway. JSON ``{"from", "to",
  "text", "id"}``, signed: ``X-Endod-Signature: t=<unix time>,v1=<hex
  HMAC-SHA256 of "<t>.<body>" under SMS_INBOUND_SECRET>`` (5 minutes'
  tolerance). The reply is in the answer, ``{"reply": text|null, "to"}``, for
  the gateway to send.

Every inbound route answers 404 while ``SMS_INBOUND_ENABLED`` is off or no
secret is set, and for a wrong secret or signature (nothing tells a prober
the route exists). Only nginx reaches the service: with ``EDGE_SHARED_SECRET``
set, every request must carry it in ``X-Endod-Edge-Key`` (403 otherwise);
in production without one, 503. The text and the reply are never logged.

Patient (``patient_router``, in the patient API, main_clinical):

* ``GET /users/me/sms-pin``: whether the account has a PIN, whether it is
  locked, and whether the short code is live (and its number).
* ``PUT /users/me/sms-pin`` ``{"pin"}``: set or change it (signed in).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
from hashlib import sha256
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from dedan_platform import sms_inbound, sms_pin, sms_settings
from dedan_platform.api_profile import current_user_id
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import SmsPin, UserEvent, utcnow
from dedan_platform.phone import mask
from dedan_platform.sms_provider import SmsProviderError, build_reply_provider

logger = logging.getLogger("dedan.sms")

EDGE_HEADER = "x-endod-edge-key"
SIGNATURE_HEADER = "x-endod-signature"
SIGNATURE_TOLERANCE = 300
MAX_BODY = 8 * 1024

router = APIRouter(prefix="/sms/v1", include_in_schema=False)
patient_router = APIRouter(prefix="/users/me", tags=["sms"])

#: Tests replace it; None means build_reply_provider().
reply_provider = None


def _production() -> bool:
    from app.core.config import get_settings

    return (os.getenv("ENVIRONMENT") or get_settings().ENVIRONMENT).strip().lower() == "production"


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not Found")


def gate(request: Request) -> None:
    """The edge key, then the switch and the secret (404 while off)."""
    edge = os.getenv("EDGE_SHARED_SECRET", "").strip()
    if edge:
        if not hmac.compare_digest(request.headers.get(EDGE_HEADER, "").encode(), edge.encode()):
            raise HTTPException(status_code=403, detail="Forbidden")
    elif _production():
        raise HTTPException(status_code=503, detail="Not configured")
    if not sms_settings.inbound_enabled() or not sms_settings.get("SMS_INBOUND_SECRET"):
        raise _not_found()


async def _body(request: Request) -> bytes:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status_code=413, detail="Too large")
    return raw


def _send_reply(phone: str, text: str) -> None:
    try:
        (reply_provider or build_reply_provider()).send(phone, text)
    except SmsProviderError as exc:
        logger.error("sms_reply_failed to=%s: %s", mask(phone), exc)


@router.post("/inbound/africastalking/{secret}", dependencies=[Depends(gate)])
async def africastalking(secret: str, request: Request, background: BackgroundTasks) -> PlainTextResponse:
    if not hmac.compare_digest(secret.encode(), sms_settings.get("SMS_INBOUND_SECRET").encode()):
        raise _not_found()
    raw = await _body(request)
    from urllib.parse import parse_qs

    form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace"), keep_blank_values=True).items()}
    sender, text = form.get("from", ""), form.get("text", "")
    answer = await _handle("africastalking", form.get("id"), sender, text)
    if answer.reply:
        background.add_task(_send_reply, answer_phone(sender), answer.reply)
    return PlainTextResponse("OK")


def answer_phone(sender: str) -> str:
    from dedan_platform.phone import normalise_ethiopian_mobile

    return normalise_ethiopian_mobile(sender) or sender


def _signed(header: str, body: bytes) -> bool:
    secret = sms_settings.get("SMS_INBOUND_SECRET")
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    try:
        timestamp = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp) > SIGNATURE_TOLERANCE:
        return False
    expected = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + body, sha256).hexdigest()
    return hmac.compare_digest(parts.get("v1", ""), expected)


@router.post("/inbound/generic", dependencies=[Depends(gate)])
async def generic(request: Request) -> JSONResponse:
    raw = await _body(request)
    if not _signed(request.headers.get(SIGNATURE_HEADER, ""), raw):
        raise _not_found()
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(status_code=400, detail="Send JSON.") from None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Send a JSON object.")
    sender, text = str(body.get("from") or ""), str(body.get("text") or "")
    answer = await _handle("generic", str(body["id"]) if body.get("id") is not None else None, sender, text)
    return JSONResponse({"reply": answer.reply, "to": answer_phone(sender) if answer.reply else None})


async def _handle(provider: str, message_id: Optional[str], sender: str, text: str) -> sms_inbound.Answer:
    from fastapi.concurrency import run_in_threadpool

    return await run_in_threadpool(sms_inbound.handle, provider, message_id, sender[:40], text[:480])


# --- the patient's PIN in the app ------------------------------------------------------------

class PinBody(BaseModel):
    pin: str = Field(min_length=4, max_length=4, description="4 digits, not all the same, not like 1234.")


def _pin_state(user_id: str) -> Dict[str, Any]:
    with session_scope() as session:
        row = session.get(SmsPin, user_id)
        locked = row is not None and row.locked_until is not None and ensure_aware(row.locked_until) > utcnow()
        return {"has_pin": row is not None, "locked_until": ensure_aware(row.locked_until).isoformat()
                if locked else None, "short_code": sms_settings.short_code() if sms_settings.inbound_live() else None,
                "commands_enabled": sms_settings.inbound_live()}


@patient_router.get("/sms-pin")
def read_pin(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return _pin_state(user_id)


@patient_router.put("/sms-pin")
def set_pin(body: PinBody, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    with session_scope() as session:
        try:
            sms_pin.set_pin(session, user_id, body.pin)
        except sms_pin.PinError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.add(UserEvent(user_id=user_id, event_type="sms_pin_set", payload=json.dumps({"via": "app"})))
    return _pin_state(user_id)
