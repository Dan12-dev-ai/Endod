"""Balance, deposits, booking quotes, video joins and emergency numbers.

* ``/users/me/wallet``: the balance and its history; deposits through Chapa.
* ``/users/me/hospital-bookings/quote``: what a visit at a partner hospital costs.
* ``/users/me/appointments/{id}/video``: join details for an approved video visit.
* ``/users/me/care/emergency``: numbers to call, and the nearest partner hospitals' ambulances.
* ``/payments/chapa/...``: Chapa's webhook and callback (public; they only
  trigger a verification with Chapa, see deposits.settle).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from dedan_platform import chapa, deposits, hospital_bookings, partners, wallet
from dedan_platform.api_profile import current_user_id
from dedan_platform.appointments import AppointmentError, AppointmentNotFound
from dedan_platform.care_navigation import haversine_km
from dedan_platform.jitsi import JitsiError

router = APIRouter(tags=["payments"])


class DepositRequest(BaseModel):
    #: Birr, up to two decimals.
    amount: Decimal = Field(gt=0, le=1_000_000, decimal_places=2)


@router.get("/users/me/wallet")
def read_wallet(user_id: str = Depends(current_user_id),
                limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, Any]:
    return wallet.summary(user_id, limit=limit)


@router.post("/users/me/wallet/deposits", status_code=status.HTTP_201_CREATED)
def start_deposit(body: DepositRequest, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    santim = int((body.amount * 100).to_integral_value())
    try:
        return deposits.start(user_id, santim)
    except deposits.DepositError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/users/me/wallet/deposits/{deposit_id}")
def read_deposit(deposit_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    try:
        return deposits.status_for(user_id, deposit_id)
    except deposits.DepositError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/users/me/hospital-bookings/quote")
def booking_quote(hospital_id: str = Query(max_length=32), visit_mode: str = Query(default="in_person"),
                  user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    try:
        quote = hospital_bookings.quote(hospital_id, visit_mode)
    except AppointmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    balance = wallet.summary(user_id, limit=1)["balance"]
    return {**quote, "balance": balance, "enough": balance >= quote["total"]}


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

def _settle(tx_ref: Optional[str]) -> Dict[str, Any]:
    if not tx_ref or len(tx_ref) > 64:
        raise HTTPException(status_code=400, detail="Missing transaction reference.")
    try:
        result = deposits.settle(tx_ref)
    except chapa.ChapaError as exc:
        # Chapa will notify again; the patient's return also re-checks.
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
    tx_ref = (body.get("tx_ref") or body.get("trx_ref")) if isinstance(body, dict) else None
    # Settling calls Chapa (blocking I/O): off the event loop.
    return await run_in_threadpool(_settle, tx_ref)
