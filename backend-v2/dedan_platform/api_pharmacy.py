"""The pharmacy site's API (docs/pharmacy.md section 2), server to server.

Served by internal-api only (main_internal, on the private bus network); the
patient API does not mount it. Every route needs ``X-Pharmacy-Key``
(``PHARMACY_API_KEY``, compared in constant time; refused while unset). The
pharmacy site's server passes the pharmacist's address in ``X-Client-IP``,
which keys the rate limits (counted in the database, see throttle.py):

* code lookups: 10 failed per client per hour, and 5 failed per code per
  hour, then 429 (a dispense by code counts the same way);
* token lookups: 60 per client per hour.

A forged token, an unknown code and a phone that does not match all answer
the same 404 "Not found".
"""

from __future__ import annotations

import hmac
import ipaddress
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError

from dedan_platform import partner_config, prescriptions, throttle

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"], include_in_schema=False)

TOKEN_LOOKUPS_PER_HOUR = 60
FAILED_CODES_PER_CLIENT = 10
FAILED_PER_CODE = 5


def require_pharmacy_key(x_pharmacy_key: Optional[str] = Header(default=None)) -> None:
    expected = partner_config.pharmacy_api_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Not available.")
    if not x_pharmacy_key or not hmac.compare_digest(x_pharmacy_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Not authorised.")


def client_key(raw: Optional[str]) -> str:
    """The rate-limit key for ``X-Client-IP``: the address in canonical form,
    an IPv6 address by its /64 (one subscriber's block), and anything missing
    or unreadable in one shared bucket."""
    try:
        ip = ipaddress.ip_address((raw or "").strip())
    except ValueError:
        return "unknown"
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def _clean_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError("must not contain control characters")
    return " ".join(value.split())


class Lookup(BaseModel):
    token: Optional[str] = Field(default=None, max_length=128)
    code: Optional[str] = Field(default=None, max_length=16)
    phone: Optional[str] = Field(default=None, max_length=32)


class DispenseItem(BaseModel):
    item_index: int = Field(ge=0, le=1000, strict=True)
    amount: Optional[float] = Field(default=None, gt=0, le=1_000_000)
    complete: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def _number(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("amount must be a number")
        return value


class Dispense(Lookup):
    pharmacy_name: str = Field(max_length=120)
    pharmacist_name: Optional[str] = Field(default=None, max_length=120)
    items: List[DispenseItem] = Field(min_length=1, max_length=50)

    @field_validator("pharmacy_name")
    @classmethod
    def _pharmacy(cls, value: str) -> str:
        value = _clean_name(value) or ""
        if not 2 <= len(value) <= 120:
            raise ValueError("pharmacy_name must be 2 to 120 characters")
        return value

    @field_validator("pharmacist_name")
    @classmethod
    def _pharmacist(cls, value: Optional[str]) -> Optional[str]:
        return _clean_name(value) or None


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Not found")


def _limit(limits: Dict[str, int]) -> List[str]:
    try:
        return throttle.begin(limits)
    except throttle.Limited as exc:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.",
                            headers={"Retry-After": str(exc.retry_after)}) from exc


def _resolve(body: Lookup, client: str, count_tokens: bool) -> str:
    """The rx_id the request names, or the shared 404."""
    if body.token is not None and body.code is None and body.phone is None:
        if count_tokens:
            _limit({f"rx:token:ip:{client}": TOKEN_LOOKUPS_PER_HOUR})
        rx_id = prescriptions.find_by_token(body.token)
        if rx_id is None:
            raise _not_found()
        return rx_id
    if body.token is None and body.code is not None and body.phone is not None:
        code = body.code.strip()
        # Failures only: counted first (so parallel guesses see each other),
        # taken back when the code and phone match.
        attempt = _limit({f"rx:code:ip:{client}": FAILED_CODES_PER_CLIENT,
                          f"rx:code:{code}": FAILED_PER_CODE})
        rx_id = prescriptions.find_by_code(code, body.phone)
        if rx_id is None:
            raise _not_found()
        throttle.forget(attempt)
        return rx_id
    raise HTTPException(status_code=422, detail="Send a token, or a code and a phone number.")


@router.post("/lookup", dependencies=[Depends(require_pharmacy_key)])
def lookup(body: Lookup, x_client_ip: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    rx_id = _resolve(body, client_key(x_client_ip), count_tokens=True)
    view = prescriptions.lookup(rx_id)
    if view is None:
        raise _not_found()
    return view


@router.post("/dispense", dependencies=[Depends(require_pharmacy_key)])
def dispense(body: Dispense, x_client_ip: Optional[str] = Header(default=None),
             idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    key = None
    if idempotency_key is not None:
        try:
            key = str(uuid.UUID(idempotency_key.strip()))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Idempotency-Key must be a UUID.") from exc
    rx_id = _resolve(body, client_key(x_client_ip), count_tokens=False)
    try:
        return prescriptions.dispense(
            rx_id, pharmacy_name=body.pharmacy_name, pharmacist_name=body.pharmacist_name,
            items=[item.model_dump() for item in body.items], idempotency_key=key)
    except prescriptions.DispenseError as exc:
        if exc.status_code == 404:
            raise _not_found() from exc
        content: Dict[str, Any] = {"detail": exc.detail}
        if exc.prescription_status:
            content["status"] = exc.prescription_status
        return JSONResponse(status_code=exc.status_code, content=content)
    except IntegrityError:
        # The same Idempotency-Key sent for two prescriptions at the same moment.
        return JSONResponse(status_code=409, content={"detail": "This Idempotency-Key was used for another dispense."})
