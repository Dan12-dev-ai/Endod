"""Booking payments, booking quotes, video joins and emergency numbers.

* ``/users/me/hospital-bookings/quote``: what a visit at a partner hospital costs.
* ``/users/me/booking-payments/{tx_ref}``: the patient's payment for a booking,
  checked with Chapa (the app asks this when the patient comes back from Chapa).
* ``/users/me/appointments/{id}/video``: join details for an approved video visit.
* ``/users/me/care/emergency``: numbers to call, and the nearest partner hospitals' ambulances.
* ``/payments/status``: whether online payment is available (public).
* ``/payments/chapa/...``: Chapa's webhook and callback (public; they only
  trigger a verification with Chapa, see booking_payments.settle).
* ``/users/me/wallet``: the old Endod balance, readable; top-ups are gone (410).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool

from dedan_platform import booking_payments, chapa, deposits, hospital_bookings, partners, wallet
from dedan_platform.api_profile import current_user_id
from dedan_platform.appointments import AppointmentError, AppointmentNotFound
from dedan_platform.care_navigation import haversine_km
from dedan_platform.jitsi import JitsiError

router = APIRouter(tags=["payments"])


@router.get("/users/me/wallet")
def read_wallet(user_id: str = Depends(current_user_id),
                limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, Any]:
    return wallet.summary(user_id, limit=limit)


#: Patients pay for each booking through Chapa: there is no balance to top up.
TOPUPS_GONE = "Top-ups are no longer available. You pay for each booking through Chapa."


@router.post("/users/me/wallet/deposits")
def start_deposit(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=TOPUPS_GONE)


@router.get("/users/me/wallet/deposits/{deposit_id}")
def read_deposit(deposit_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    raise HTTPException(status_code=status.HTTP_410_GONE, detail=TOPUPS_GONE)


@router.get("/users/me/hospital-bookings/quote")
def booking_quote(hospital_id: str = Query(max_length=32), visit_mode: str = Query(default="in_person"),
                  user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    try:
        return hospital_bookings.quote(hospital_id, visit_mode)
    except AppointmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/users/me/booking-payments/{tx_ref}")
def read_booking_payment(tx_ref: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """The patient back from Chapa: their payment, checked with Chapa itself
    (the return address proves nothing), and the booking as it now stands."""
    if len(tx_ref) > 64:
        raise HTTPException(status_code=404, detail="Payment not found.")
    try:
        return booking_payments.status_for(user_id, tx_ref)
    except booking_payments.PaymentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/users/me/appointments/{appointment_id}/video")
def join_video(appointment_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    try:
        return hospital_bookings.video_join(user_id, appointment_id)
    except AppointmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AppointmentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JitsiError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


#: Ethiopia's national emergency numbers.
NATIONAL_NUMBERS = (
    {"service": "ambulance", "number": "907", "label": "Ambulance"},
    {"service": "police", "number": "991", "label": "Police"},
    {"service": "fire", "number": "939", "label": "Fire"},
)


@router.get("/users/me/care/emergency")
def emergency(latitude: Optional[float] = Query(default=None, ge=-90, le=90),
              longitude: Optional[float] = Query(default=None, ge=-180, le=180),
              user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """Who to call: the national numbers, and partner hospitals with an
    ambulance or emergency department, nearest first when the patient shares
    their location."""
    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=400, detail="Send both latitude and longitude, or neither.")
    located = latitude is not None
    rows: List[Dict[str, Any]] = []
    for hospital in partners.listed():
        if not (hospital.ambulance_phone or hospital.emergency):
            continue
        rows.append({
            "hospital_id": hospital.id, "name": hospital.name, "name_am": hospital.name_am,
            "city": hospital.city, "address": hospital.address,
            "ambulance_phone": hospital.ambulance_phone, "phone": hospital.phone,
            "emergency": hospital.emergency, "latitude": hospital.latitude, "longitude": hospital.longitude,
            "distance_km": round(haversine_km(latitude, longitude, hospital.latitude, hospital.longitude), 1)
            if located else None,
        })
    rows.sort(key=lambda r: (r["distance_km"], r["name"]) if located else (r["name"].lower(),))
    return {"national": list(NATIONAL_NUMBERS), "hospitals": rows[:20], "location_used": located}


# --- Chapa (public) ---------------------------------------------------------------------

#: Chapa's hosted checkout pages: the only place the app sends a patient to pay.
CHAPA_CHECKOUT_ORIGIN = "https://checkout.chapa.co"


@router.get("/payments/status")
@router.get("/users/me/payments/status")  # the same, through the app's /users/me proxy
def payments_status() -> Dict[str, Any]:
    """Whether online payment is on (a Chapa key is set), so the app can say
    so before anyone presses "Pay and book", and the pages it may send a
    patient to for paying: Chapa's checkout, plus the configured Chapa
    server's own origin when it is not Chapa's (a test stand-in). Public; no
    secrets."""
    from urllib.parse import urlsplit

    from dedan_platform import partner_config

    origins = [CHAPA_CHECKOUT_ORIGIN]
    base = urlsplit(partner_config.chapa_base_url())
    if base.scheme and base.netloc and not base.netloc.endswith("chapa.co"):
        origins.append(f"{base.scheme}://{base.netloc}")
    return {"online_payments": bool(partner_config.chapa_secret_key()), "checkout_origins": origins}


def _settle(tx_ref: Optional[str], recheck_settled: bool = False) -> Dict[str, Any]:
    if not tx_ref or len(tx_ref) > 64:
        raise HTTPException(status_code=400, detail="Missing transaction reference.")
    try:
        # A refund or reversal notice re-checks even a paid booking (a chargeback).
        result = booking_payments.settle(tx_ref, recheck_paid=recheck_settled)
        if result is None:
            # Not a booking: a deposit from the old balance (still settled, never started any more).
            result = deposits.settle(tx_ref, recheck_settled=recheck_settled)
    except chapa.ChapaError as exc:
        # Chapa will notify again; the patient's return and the worker also re-check.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown transaction.")
    return {"status": result["status"]}


@router.get("/payments/chapa/callback")
def chapa_callback(trx_ref: Optional[str] = None, tx_ref: Optional[str] = None) -> Dict[str, Any]:
    """Chapa calls this (GET) when a payment finishes."""
    return _settle(trx_ref or tx_ref)


@router.post("/payments/chapa/callback")
def chapa_callback_post(trx_ref: Optional[str] = None, tx_ref: Optional[str] = None) -> Dict[str, Any]:
    return _settle(trx_ref or tx_ref)


@router.post("/payments/chapa/webhook")
async def chapa_webhook(request: Request) -> Dict[str, Any]:
    raw = await request.body()
    if not chapa.signature_ok(raw, request.headers):
        raise HTTPException(status_code=401, detail="Bad signature.")
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Bad body.") from exc
    body = body if isinstance(body, dict) else {}
    tx_ref = body.get("tx_ref") or body.get("trx_ref")
    # A refund or reversal (charge.refunded / charge.reversed) of an earlier
    # payment is checked even though it was settled (Chapa's verify is still the judge).
    words = f"{body.get('event', '')} {body.get('status', '')}".lower()
    reversal = "refund" in words or "revers" in words
    # Settling calls Chapa (blocking I/O): off the event loop.
    return await run_in_threadpool(_settle, tx_ref, reversal)
