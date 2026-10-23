"""Prescriptions at pharmacies (docs/pharmacy.md).

Every hospital prescription the platform stores gets a dispensing entry
(section 1): an ``rx_id``, a signed QR token, a 6-digit code (texted once to
the patient's verified phone) and one item per medicine with what has been
given. Pharmacies look it up and record what they give through internal-api
(section 2, api_pharmacy.py); the patient sees it in History (section 3); the
hospital is told of each dispense (section 4).

Safety rules:

* the QR token is ``<rx_id>.<signature>`` with an HMAC under
  ``RX_SIGNING_KEY``; a token is checked (constant time) before anything is
  read, so a made-up token says nothing about which prescriptions exist;
* a code works only together with the account's *verified* phone;
* a dispense first updates the prescription's row (``lock_version``), which
  locks it on PostgreSQL and takes SQLite's write lock, and only then reads
  what has been given: two pharmacies dispensing at the same moment are
  applied one after the other, never both against the same "left";
* a correction moving the record to another patient withdraws the entry and
  issues a new one, so the first patient's QR and code never open the
  second patient's prescription.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dedan_platform import eventbus, partner_config, patient_sms
from dedan_platform.db import ensure_aware, ensure_utc, new_uuid, session_scope
from dedan_platform.eventbus import RetryLater
from dedan_platform.models import (
    HealthProfile, HospitalRecord, Prescription, PrescriptionDispense, PrescriptionItem, Profile, User, utcnow,
)
from dedan_platform.phone import normalise_ethiopian_mobile

logger = logging.getLogger(__name__)

ZONE = ZoneInfo("Africa/Addis_Ababa")
VALID_DAYS = 30
QR_BASE = "https://pharmacy.endod-health.com/rx/"
SIGNATURE_CHARS = 22
#: Floating-point slack when comparing amounts (quantities are counts).
_EPSILON = 1e-9

_TOKEN_RE = re.compile(r"^([0-9a-f]{32})\.([A-Za-z0-9_-]{22})$")
_CODE_RE = re.compile(r"^[0-9]{6}$")
#: A leading count: "21", "2.5", or with thousands commas "1,000" / "1,000,000".
#: A comma followed by a digit that is not a thousands group ("1,5") is
#: ambiguous, so there is no count.
_LEADING_NUMBER = re.compile(r"^\s*((?:\d{1,3}(?:,\d{3}){1,2}|\d{1,7})(?:\.\d{1,3})?)(?![\d.]|,\d)")

OPEN, COMPLETED, EXPIRED, RETRACTED = "open", "completed", "expired", "retracted"
NOT_GIVEN, PARTLY_GIVEN, GIVEN = "not_given", "partly_given", "given"


class DispenseError(Exception):
    """A dispense that cannot be applied; ``status_code`` is 404, 409 or 422.
    A 409 always carries the prescription's status (``prescription_status``)."""

    def __init__(self, status_code: int, detail: str, prescription_status: Optional[str] = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        #: The prescription's status, when that is why it was refused.
        self.prescription_status = prescription_status


# --- the QR token --------------------------------------------------------------------------

def signature(rx_id: str) -> Optional[str]:
    """base64url HMAC-SHA256 of ``rx:<rx_id>``, 22 chars; None without a key."""
    key = partner_config.rx_signing_key()
    if not key:
        return None
    digest = hmac.new(key.encode("utf-8"), f"rx:{rx_id}".encode("ascii"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")[:SIGNATURE_CHARS]


def token_for(rx_id: str) -> Optional[str]:
    sig = signature(rx_id)
    return f"{rx_id}.{sig}" if sig else None


def rx_id_from_token(token: Any) -> Optional[str]:
    """The rx_id a genuine token names, or None (malformed, forged, or no key)."""
    if not isinstance(token, str):
        return None
    match = _TOKEN_RE.match(token.strip())
    if match is None:
        return None
    expected = signature(match.group(1))
    if expected is None or not hmac.compare_digest(expected.encode("ascii"), match.group(2).encode("ascii")):
        return None
    return match.group(1)


def valid_code(code: Any) -> bool:
    return isinstance(code, str) and bool(_CODE_RE.match(code))


# --- quantities, expiry, statuses ----------------------------------------------------------

def parse_quantity(text: Optional[str]) -> Optional[float]:
    """The leading number of a quantity as written ("21 tablets" -> 21,
    "1,000 tablets" -> 1000), or None."""
    if not text:
        return None
    match = _LEADING_NUMBER.match(text)
    if match is None:
        return None
    value = float(match.group(1).replace(",", ""))
    return value if value > 0 else None


def number(value: Optional[float]) -> Optional[float]:
    """For JSON: 21 rather than 21.0."""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else round(value, 3)


def expiry_for(occurred_at: datetime) -> datetime:
    """30 days after the prescription's day, at the end of that day in Addis Ababa (UTC)."""
    day: date = ensure_aware(occurred_at).astimezone(ZONE).date() + timedelta(days=VALID_DAYS)
    return datetime.combine(day, time(23, 59, 59), ZONE).astimezone(timezone.utc)


def _item_status(item: PrescriptionItem) -> str:
    given = item.given_total or 0
    if item.completed:
        return GIVEN
    if item.quantity_total is not None and given + _EPSILON >= item.quantity_total:
        return GIVEN
    return PARTLY_GIVEN if given > 0 else NOT_GIVEN


def current_status(rx: Prescription, record: HospitalRecord, now: Optional[datetime] = None) -> str:
    if record.retracted_at is not None or rx.withdrawn_at is not None:
        return RETRACTED
    if rx.status == COMPLETED:
        return COMPLETED
    if (now or utcnow()) > ensure_aware(rx.expires_at):
        return EXPIRED
    return OPEN


def _active_items(session: Session, rx_id: str) -> List[PrescriptionItem]:
    return list(session.scalars(select(PrescriptionItem).where(
        PrescriptionItem.rx_id == rx_id, PrescriptionItem.removed.is_(False)).order_by(PrescriptionItem.item_index)))


# --- issuing and keeping entries (called from patient_history) ------------------------------

def _random_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _free_code(session: Session) -> str:
    """A code no active prescription holds. Codes of expired entries are freed first."""
    session.execute(update(Prescription).where(
        Prescription.active_code.is_not(None), Prescription.expires_at < utcnow()).values(active_code=None))
    for _ in range(25):
        code = _random_code()
        if session.scalar(select(Prescription.id).where(Prescription.active_code == code)) is None:
            return code
    raise RetryLater("no free prescription code found")


def _current_entry(session: Session, record_id: str) -> Optional[Prescription]:
    return session.scalar(select(Prescription).where(
        Prescription.record_id == record_id, Prescription.withdrawn_at.is_(None)).with_for_update())


def _withdraw(session: Session, rx: Prescription) -> None:
    rx.withdrawn_at = utcnow()
    rx.active_code = None
    rx.updated_at = utcnow()
    patient_sms.cancel_prefix(session, f"sms:rx:{rx.id}:")


def by_index(items: Any) -> Dict[int, Dict[str, Any]]:
    """A prescription's cleaned items by their index in the hospital's list
    (``item_index``, kept by patient_history.clean_details so a dropped empty
    item never shifts the others). Records stored before that have no
    ``item_index``: their position is their index."""
    out: Dict[int, Dict[str, Any]] = {}
    for position, medicine in enumerate(items if isinstance(items, list) else []):
        if not isinstance(medicine, dict):
            continue
        index = medicine.get("item_index")
        out[index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else position] = medicine
    return out


def _sync_items(session: Session, rx: Prescription, details: Dict[str, Any]) -> None:
    """Items by the hospital's index: given amounts kept, quantities as the record now says."""
    medicines = by_index(details.get("items"))
    existing = {item.item_index: item for item in session.scalars(
        select(PrescriptionItem).where(PrescriptionItem.rx_id == rx.id))}
    for index, medicine in sorted(medicines.items()):
        quantity = medicine.get("quantity")
        item = existing.pop(index, None)
        if item is None:
            item = PrescriptionItem(rx_id=rx.id, item_index=index, given_total=None, completed=False)
            session.add(item)
        item.quantity_text = quantity
        item.quantity_total = parse_quantity(quantity)
        item.removed = False
        item.status = _item_status(item)
    for dropped in existing.values():
        dropped.removed = True
    session.flush()


def _settle_status(session: Session, rx: Prescription) -> None:
    """Completed when every item is given (a correction may add one and reopen it)."""
    items = _active_items(session, rx.id)
    done = bool(items) and all(item.status == GIVEN for item in items)
    if done:
        rx.status = COMPLETED
        rx.active_code = None
    elif rx.status == COMPLETED:
        rx.status = OPEN
        if ensure_aware(rx.expires_at) > utcnow():
            _reclaim_code(session, rx)


def _reclaim_code(session: Session, rx: Prescription) -> None:
    """Hold the code again for a reopened entry, unless another took it meanwhile
    (lookups go by code and phone, so it keeps working either way)."""
    try:
        with session.begin_nested():
            rx.active_code = rx.code
            session.flush()
    except IntegrityError:
        rx.active_code = None


def on_prescription_stored(session: Session, record: HospitalRecord, details: Dict[str, Any]) -> None:
    """After ``record.published`` stored (or corrected) ``record``, in its transaction."""
    rx = _current_entry(session, record.id)
    if record.category != "prescription":
        if rx is not None:
            _withdraw(session, rx)  # no longer a prescription: its QR and code stop working
        return
    if rx is not None and rx.user_id != record.user_id:
        _withdraw(session, rx)  # moved to another patient: they get an entry of their own
        rx = None
    is_new = rx is None
    if rx is None:
        rx = Prescription(id=new_uuid(), record_id=record.id, user_id=record.user_id, status=OPEN,
                          expires_at=ensure_utc(expiry_for(record.occurred_at)))
        for _ in range(5):
            code = _free_code(session)
            try:
                with session.begin_nested():
                    rx.code, rx.active_code = code, code
                    session.add(rx)
                    session.flush()
                break
            except IntegrityError:
                continue  # another prescription took the code at the same moment
        else:
            raise RetryLater("could not reserve a prescription code")
    else:
        rx.expires_at = ensure_utc(expiry_for(record.occurred_at))
        if rx.status == OPEN and rx.active_code is None and ensure_aware(rx.expires_at) > utcnow():
            _reclaim_code(session, rx)
    rx.updated_at = utcnow()
    _sync_items(session, rx, details)
    _settle_status(session, rx)
    if is_new and current_status(rx, record) == OPEN:
        # Once (the key), only to a verified phone (to_account), never for an expired one.
        patient_sms.to_account(session, record.user_id, patient_sms.RX_CODE, f"sms:rx:{rx.id}:code",
                               {"rx_id": rx.id, "code": rx.code, "hospital": record.hospital_name})


def on_record_retracted(session: Session, record: HospitalRecord) -> None:
    """The hospital retracted the record: its entry closes (status ``retracted``)."""
    for rx in session.scalars(select(Prescription).where(Prescription.record_id == record.id)):
        rx.active_code = None
        rx.updated_at = utcnow()
        patient_sms.cancel_prefix(session, f"sms:rx:{rx.id}:code")


# --- what pharmacies and the patient see ---------------------------------------------------

def _medicines(record: HospitalRecord) -> Tuple[Dict[int, Dict[str, Any]], Optional[str]]:
    try:
        details = json.loads(record.details_json) if record.details_json else {}
    except ValueError:
        details = {}
    return by_index(details.get("items")), details.get("notes")


def _age(dob: Optional[datetime]) -> Optional[int]:
    if dob is None:
        return None
    born = ensure_aware(dob).astimezone(ZONE).date()
    today = datetime.now(ZONE).date()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return years if 0 <= years < 150 else None


def _patient(session: Session, user_id: str) -> Dict[str, Any]:
    user = session.get(User, user_id)
    profile = session.scalar(select(Profile).where(Profile.user_id == user_id))
    health = session.scalar(select(HealthProfile).where(HealthProfile.user_id == user_id))
    dedan_id = user.dedan_user_id if user is not None else None
    names = [getattr(profile, part, None) for part in ("first_name", "middle_name", "last_name")] if profile else []
    name = " ".join(n for n in names if n) or (profile.display_name if profile else None) or dedan_id
    return {"name": name, "dedan_id": dedan_id, "age": _age(health.date_of_birth) if health else None,
            "sex": (health.sex or None) if health else None}


def _dispenses(session: Session, rx_id: str) -> List[Dict[str, Any]]:
    rows = session.scalars(select(PrescriptionDispense).where(PrescriptionDispense.rx_id == rx_id)
                           .order_by(PrescriptionDispense.at, PrescriptionDispense.id))
    return [{"at": ensure_aware(row.at).isoformat(), "pharmacy_name": row.pharmacy_name,
             "items": json.loads(row.items_json)} for row in rows]


def pharmacy_view(session: Session, rx: Prescription, record: HospitalRecord) -> Dict[str, Any]:
    """The lookup response (contract section 2): this prescription and who it is for, nothing else."""
    status = current_status(rx, record)
    medicines, notes = _medicines(record)
    items = []
    if status != RETRACTED:  # entered in error: its contents are not shown again
        for item in _active_items(session, rx.id):
            medicine = medicines.get(item.item_index, {})
            items.append({
                "item_index": item.item_index, "drug": medicine.get("drug"), "dose": medicine.get("dose"),
                "route": medicine.get("route"), "frequency": medicine.get("frequency"),
                "duration": medicine.get("duration"), "quantity_text": item.quantity_text,
                "quantity_total": number(item.quantity_total), "given_total": number(item.given_total),
                "status": item.status, "notes": medicine.get("notes"),
            })
    return {
        "rx_id": rx.id, "status": status, "hospital_name": record.hospital_name,
        "doctor_name": record.recorded_by, "written_at": ensure_aware(record.occurred_at).isoformat(),
        "expires_at": ensure_aware(rx.expires_at).isoformat(), "patient": _patient(session, rx.user_id),
        "notes": notes if status != RETRACTED else None, "items": items,
        "dispenses": _dispenses(session, rx.id) if status != RETRACTED else [],
    }


def patient_views(session: Session, records: Iterable[HospitalRecord]) -> Dict[str, Dict[str, Any]]:
    """record_id -> what History shows under a prescription: QR, code, expiry,
    items and dispenses. The QR and code only while it can still be used."""
    by_id = {r.id: r for r in records if r.category == "prescription"}
    if not by_id:
        return {}
    views: Dict[str, Dict[str, Any]] = {}
    for rx in session.scalars(select(Prescription).where(
            Prescription.record_id.in_(list(by_id)), Prescription.withdrawn_at.is_(None))):
        record = by_id[rx.record_id]
        if rx.user_id != record.user_id:
            continue
        status = current_status(rx, record)
        usable = status == OPEN
        token = token_for(rx.id) if usable else None
        views[rx.record_id] = {
            "rx_id": rx.id, "status": status, "expires_at": ensure_aware(rx.expires_at).isoformat(),
            "code": rx.code if usable else None, "qr_url": f"{QR_BASE}{token}" if token else None,
            "items": [{"item_index": i.item_index, "quantity_text": i.quantity_text,
                       "quantity_total": number(i.quantity_total), "given_total": number(i.given_total),
                       "status": i.status} for i in _active_items(session, rx.id)],
            "dispenses": _dispenses(session, rx.id),
        }
    return views


# --- finding a prescription ----------------------------------------------------------------

def find_by_token(token: Any) -> Optional[str]:
    """The rx_id for a genuine token of an existing entry, else None."""
    rx_id = rx_id_from_token(token)
    if rx_id is None:
        return None
    with session_scope() as session:
        rx = session.get(Prescription, rx_id)
        return rx.id if rx is not None and rx.withdrawn_at is None else None


def find_by_code(code: Any, phone: Any) -> Optional[str]:
    """The rx_id for a code, when the phone is the account's verified phone.
    An open prescription first, then the newest."""
    if not valid_code(code):
        return None
    wanted = normalise_ethiopian_mobile(phone if isinstance(phone, str) else None)
    if wanted is None:
        return None
    with session_scope() as session:
        rows = session.execute(select(Prescription, Profile, HospitalRecord)
                               .join(Profile, Profile.user_id == Prescription.user_id)
                               .join(HospitalRecord, HospitalRecord.id == Prescription.record_id)
                               .where(Prescription.code == code, Prescription.withdrawn_at.is_(None))).all()
        matches = [(rx, record) for rx, profile, record in rows
                   if profile.phone_verified_at is not None and profile.phone
                   and hmac.compare_digest(normalise_ethiopian_mobile(profile.phone) or "", wanted)]
        if not matches:
            return None
        matches.sort(key=lambda m: (current_status(m[0], m[1]) == OPEN, ensure_aware(m[0].created_at)), reverse=True)
        return matches[0][0].id


def status_of(rx_id: str) -> Optional[str]:
    with session_scope() as session:
        rx = session.get(Prescription, rx_id)
        record = session.get(HospitalRecord, rx.record_id) if rx is not None else None
        return current_status(rx, record) if rx is not None and record is not None else None


def code_still_usable(rx_id: str) -> bool:
    """Whether a queued code text is still worth sending (checked just before)."""
    with session_scope() as session:
        rx = session.get(Prescription, rx_id)
        record = session.get(HospitalRecord, rx.record_id) if rx is not None else None
        return rx is not None and record is not None and current_status(rx, record) == OPEN


def lookup(rx_id: str) -> Optional[Dict[str, Any]]:
    with session_scope() as session:
        rx = session.get(Prescription, rx_id)
        record = session.get(HospitalRecord, rx.record_id) if rx is not None else None
        if rx is None or record is None:
            return None
        return pharmacy_view(session, rx, record)


# --- dispensing -----------------------------------------------------------------------------

def dispense(rx_id: str, *, pharmacy_name: str, pharmacist_name: Optional[str],
             items: List[Dict[str, Any]], idempotency_key: Optional[str] = None,
             before_apply=None) -> Dict[str, Any]:
    """Record medicine given (contract section 2). Returns the updated
    prescription as lookup shows it. Raises DispenseError (409/422).

    ``before_apply`` is a test hook, called with the row locked, after the
    checks and before the amounts are written.
    """
    after: List[Any] = []
    with session_scope() as session:
        # The lock, first: nothing about this prescription is read before it.
        session.execute(update(Prescription).where(Prescription.id == rx_id)
                        .values(lock_version=Prescription.lock_version + 1))
        rx = session.get(Prescription, rx_id, with_for_update=True, populate_existing=True)
        record = session.get(HospitalRecord, rx.record_id, populate_existing=True) if rx is not None else None
        if rx is None or record is None:
            raise DispenseError(404, "Not found")
        if idempotency_key:
            done = session.scalar(select(PrescriptionDispense).where(
                PrescriptionDispense.idempotency_key == idempotency_key))
            if done is not None:
                if done.rx_id != rx_id or not done.response_json:
                    raise DispenseError(409, "This Idempotency-Key was used for another dispense.",
                                        current_status(rx, record))
                return json.loads(done.response_json)
        status = current_status(rx, record)
        if status != OPEN:
            raise DispenseError(409, f"This prescription is {status}.", status)

        active = {item.item_index: item for item in _active_items(session, rx.id)}
        seen = set()
        for request in items:
            index = request["item_index"]
            if index in seen:
                raise DispenseError(422, f"Item {index} is listed twice.")
            seen.add(index)
            item = active.get(index)
            if item is None:
                raise DispenseError(422, f"There is no item {index} on this prescription.")
            if request.get("amount") is None and not request.get("complete"):
                raise DispenseError(422, f"Item {index}: give an amount or mark it complete.")
            if item.status == GIVEN:
                raise DispenseError(409, f"Item {index} has already been given.", status)
            amount = request.get("amount")
            if amount is not None and item.quantity_total is not None:
                left = item.quantity_total - (item.given_total or 0)
                if amount > left + _EPSILON:
                    raise DispenseError(409, f"Item {index}: only {number(max(left, 0))} left to give.", status)

        if before_apply is not None:
            before_apply()  # (tests) between checking what is left and giving it
        now = utcnow()
        given = []
        for request in items:
            item = active[request["item_index"]]
            amount = request.get("amount")
            if amount is not None:
                item.given_total = (item.given_total or 0) + amount
            if request.get("complete"):
                item.completed = True
            item.status = _item_status(item)
            given.append({"item_index": item.item_index, "amount": number(amount),
                          "complete": bool(request.get("complete")),
                          "given_total": number(item.given_total), "status": item.status})
        _settle_status(session, rx)
        rx.updated_at = now
        row = PrescriptionDispense(
            id=new_uuid(), rx_id=rx.id, at=now, pharmacy_name=pharmacy_name, pharmacist_name=pharmacist_name,
            items_json=json.dumps([{k: g[k] for k in ("item_index", "amount", "complete")} for g in given]),
            idempotency_key=idempotency_key or None)
        session.add(row)
        session.flush()
        response = pharmacy_view(session, rx, record)
        row.response_json = json.dumps(response, ensure_ascii=False)

        user = session.get(User, rx.user_id)
        eventbus.emit(session, "prescription.dispensed", {
            "record_id": record.id, "hospital_id": record.hospital_id,
            "dedan_id": user.dedan_user_id if user is not None else None, "dispense_id": row.id,
            "at": ensure_aware(now).isoformat(), "pharmacy_name": pharmacy_name,
            "status": COMPLETED if rx.status == COMPLETED else OPEN, "items": given,
        })
        # The text never names the pharmacy: the name is typed by whoever is at
        # the counter, and an SMS in Endod's name must not carry a number or a
        # link they chose. The app shows it, labelled as entered.
        patient_sms.to_account(session, rx.user_id, patient_sms.RX_DISPENSED, f"sms:rx:{rx.id}:dispense:{row.id}",
                               {"rx_id": rx.id})
        after.append((rx.user_id, record.id, " ".join(pharmacy_name.split())))
    from dedan_platform import inbox

    for user_id, record_id, name in after:
        # A generic title; the name only in the body, plain text and labelled
        # as the pharmacy entered it (it is not verified).
        inbox.add_item(user_id, "records", "prescription_dispensed", "Medicine given at a pharmacy",
                       f"Pharmacy (as entered): {name[:120]}. Open your prescription in History to see what is left.",
                       "history", record_id)
    return response
