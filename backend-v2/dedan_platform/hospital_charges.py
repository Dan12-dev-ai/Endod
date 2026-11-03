"""Charges from partner hospitals: bills the patient pays at the hospital for a
lab test, imaging, a procedure, a consultation or anything else
(docs/service-fee.md; the hospital service's integration API, ``/charges``).

The hospital's system creates a charge there; the hospital service adds
Endod's service fee (the settings it was last sent, ``fees.updated``) and
tells this platform:

* ``charge.created`` (only for a patient linked to an Endod account): the
  patient's bill (``patient_bills``) appears in the app (``GET
  /users/me/bills``), with an inbox item and an SMS when they allow SMS. The
  SMS is never clinical: "your bill at the hospital: ETB total (incl. Endod
  service fee ETB fee)"; no test, no hospital name.
* ``charge.paid`` (every charge, linked patient or not): the patient paid the
  hospital the total, so the hospital owes Endod the fee: an entry of the fee
  ledger (fee_ledger.py, ``owed``), and the bill becomes ``paid``.
* ``charge.voided``: the bill is ``voided`` (an open charge only; a paid one
  cannot be voided at the hospital service).

The amounts are the hospital service's (it computed the fee with Endod's
rule, fee_settings.fee_for); here they are checked to add up. Santim.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from dedan_platform import eventbus, fee_ledger, wallet
from dedan_platform.db import ensure_aware, ensure_utc, session_scope
from dedan_platform.eventbus import PermanentEventError
from dedan_platform.models import BillStatus, PartnerHospital, PatientBill, User, utcnow

logger = logging.getLogger(__name__)

CATEGORIES = ("lab_test", "imaging", "procedure", "consultation", "other")
#: How a patient may pay a charge at the hospital.
METHODS = ("cash", "card", "mobile_money", "other")


class _Item(BaseModel):
    category: Literal["lab_test", "imaging", "procedure", "consultation", "other"]
    name: str = Field(min_length=1, max_length=160)
    code: Optional[str] = Field(default=None, max_length=40)
    amount: int = Field(ge=0, strict=True)
    quantity: int = Field(ge=1, le=1000, strict=True)


class _Charge(BaseModel):
    charge_id: str = Field(min_length=1, max_length=64)
    hospital_id: str = Field(min_length=1, max_length=32)
    dedan_id: Optional[str] = Field(default=None, max_length=16)
    appointment_id: Optional[str] = Field(default=None, max_length=64)
    subtotal: int = Field(ge=0, strict=True)
    service_fee: int = Field(ge=0, strict=True)
    total: int = Field(ge=0, strict=True)
    currency: Literal["ETB"] = "ETB"

    @model_validator(mode="after")
    def _adds_up(self):
        if self.subtotal + self.service_fee != self.total:
            raise ValueError("total must be subtotal + service_fee")
        return self


class Created(_Charge):
    items: List[_Item] = Field(min_length=1, max_length=100)


class Paid(_Charge):
    method: Literal["cash", "card", "mobile_money", "other"]
    reference: Optional[str] = Field(default=None, max_length=100)
    paid_at: datetime


class Voided(BaseModel):
    charge_id: str = Field(min_length=1, max_length=64)
    hospital_id: str = Field(min_length=1, max_length=32)
    dedan_id: Optional[str] = Field(default=None, max_length=16)


def _parse(model, payload: Dict[str, Any]):
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise PermanentEventError(str(exc).splitlines()[0] + ": " + str(exc.errors()[0].get("loc"))) from exc


def _patient(session: Session, hospital_id: str, dedan_id: Optional[str]) -> Optional[User]:
    """The account the charge is for, when it is a patient this hospital may
    send things about (linked, or booked through Endod); else None."""
    from dedan_platform import patient_history

    user = patient_history._user_by_dedan(session, dedan_id)
    if user is None:
        return None
    if not patient_history.may_act_for(session, hospital_id, user.id):
        logger.warning("charge_for_unlinked_patient hospital=%s", hospital_id)
        return None
    return user


def _bill(session: Session, charge_id: str, hospital_id: str) -> Optional[PatientBill]:
    return session.scalar(select(PatientBill).where(PatientBill.charge_id == charge_id,
                                                    PatientBill.hospital_id == hospital_id).with_for_update())


def on_created(session: Session, payload: Dict[str, Any]) -> None:
    charge = _parse(Created, payload)
    user = _patient(session, charge.hospital_id, charge.dedan_id)
    if user is None:
        return  # not an Endod patient here: no bill to show (charge.paid still reaches the ledger)
    if session.scalar(select(PatientBill.id).where(PatientBill.charge_id == charge.charge_id)) is not None:
        return  # a redelivery
    items = [item.model_dump(exclude_none=True) for item in charge.items]
    bill = PatientBill(user_id=user.id, hospital_id=charge.hospital_id, charge_id=charge.charge_id,
                       booking_id=charge.appointment_id, items_json=json.dumps(items, ensure_ascii=False),
                       subtotal=charge.subtotal, service_fee=charge.service_fee, total=charge.total,
                       status=BillStatus.OPEN)
    session.add(bill)
    session.flush()
    from dedan_platform import patient_sms

    # Never clinical: the amounts only (no test, no hospital name).
    patient_sms.to_account(session, user.id, patient_sms.BILL, f"sms:bill:{charge.charge_id}",
                           {"total": wallet.birr(charge.total), "fee": wallet.birr(charge.service_fee)})
    hospital = session.get(PartnerHospital, charge.hospital_id)
    name = hospital.name if hospital is not None else "The hospital"
    user_id, bill_id = user.id, bill.id
    body = (f"{name}: ETB {wallet.birr(charge.total)} to pay at the hospital (ETB {wallet.birr(charge.subtotal)} "
            f"plus the Endod service fee of ETB {wallet.birr(charge.service_fee)}).")

    def notice() -> None:
        from dedan_platform import inbox

        inbox.add_item(user_id, "messages", "bill_created", "New bill from the hospital", body=body,
                       link_screen="bills", link_id=bill_id)

    eventbus.after_commit(session, notice)


def on_paid(session: Session, payload: Dict[str, Any]) -> None:
    charge = _parse(Paid, payload)
    if charge.paid_at.tzinfo is None:
        raise PermanentEventError("paid_at must include a timezone offset")
    paid_at = ensure_utc(charge.paid_at)
    user = _patient(session, charge.hospital_id, charge.dedan_id)
    fee_ledger.record(session, source_type=fee_ledger.CHARGE, source_id=charge.charge_id,
                      hospital_id=charge.hospital_id, user_id=user.id if user else None,
                      dedan_id=user.dedan_user_id if user else None, subtotal=charge.subtotal,
                      fee=charge.service_fee, method=charge.method, reference=charge.reference,
                      collected_by="hospital", paid_at=paid_at)
    bill = _bill(session, charge.charge_id, charge.hospital_id)
    if bill is not None and bill.status == BillStatus.OPEN:
        bill.status, bill.method, bill.paid_at, bill.updated_at = BillStatus.PAID, charge.method, paid_at, utcnow()


def on_voided(session: Session, payload: Dict[str, Any]) -> None:
    voided = _parse(Voided, payload)
    bill = _bill(session, voided.charge_id, voided.hospital_id)
    if bill is None or bill.status != BillStatus.OPEN:
        return
    bill.status, bill.voided_at, bill.updated_at = BillStatus.VOIDED, utcnow(), utcnow()
    from dedan_platform import patient_sms

    # A text about the bill that has not gone yet is not sent.
    patient_sms.cancel_prefix(session, f"sms:bill:{voided.charge_id}")


HANDLERS = {
    "charge.created": on_created,
    "charge.paid": on_paid,
    "charge.voided": on_voided,
}


# --- the patient's bills (GET /users/me/bills) ------------------------------------------------

def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value is not None else None


def bill_out(bill: PatientBill, hospital_name: Optional[str]) -> Dict[str, Any]:
    try:
        items = json.loads(bill.items_json or "[]")
    except ValueError:
        items = []
    return {"id": bill.id, "hospital_id": bill.hospital_id, "hospital_name": hospital_name,
            "appointment_id": bill.booking_id, "items": items, "subtotal": bill.subtotal,
            "service_fee": bill.service_fee, "total": bill.total, "currency": bill.currency, "status": bill.status,
            "method": bill.method, "paid_at": _iso(bill.paid_at), "voided_at": _iso(bill.voided_at),
            "created_at": _iso(bill.created_at),
            # How it is paid: at the hospital (online payment of bills is not offered yet).
            "pay_at": "hospital"}


def list_bills(user_id: str, limit: int = 50) -> Dict[str, Any]:
    with session_scope() as session:
        rows = list(session.scalars(select(PatientBill).where(PatientBill.user_id == user_id)
                                    .order_by(PatientBill.created_at.desc(), PatientBill.id).limit(limit)))
        ids = {r.hospital_id for r in rows}
        names = dict(session.execute(select(PartnerHospital.id, PartnerHospital.name)
                                     .where(PartnerHospital.id.in_(ids))).all()) if ids else {}
        items = [bill_out(r, names.get(r.hospital_id)) for r in rows]
    open_total = sum(b["total"] for b in items if b["status"] == BillStatus.OPEN)
    return {"items": items, "open_total": open_total, "currency": "ETB"}
