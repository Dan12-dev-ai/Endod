"""Endod's books for the service fee: one entry per paid hospital service
(docs/service-fee.md, section 4).

Entries come from every way a patient pays for a hospital service:

* a booking paid online through Chapa (booking_payments.settle ->
  hospital_bookings.on_paid): ``collected_by`` endod, ``collected``;
* a booking paid at the hospital: when the hospital says it was paid
  (``appointment.paid``) or, failing that, when it completes the visit
  (``appointment.completed``, method ``unrecorded``): ``collected_by``
  hospital, ``owed`` (the hospital collected the fee for Endod);
* a hospital charge paid at the hospital (``charge.paid``, hospital_charges.py):
  ``collected_by`` hospital, ``owed``.

An entry is written once per source (``source_type``, ``source_id``): a
redelivered event changes nothing. A refunded online payment becomes
``refunded`` (no fee is due). A super admin marks owed fees ``settled`` with
the reference of the hospital's payment to Endod (api_admin.py).

Amounts are santim. No health data: ids, amounts, methods and times only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dedan_platform.db import ensure_aware
from dedan_platform.models import FeeCollector, FeeLedgerEntry, FeeSettlement, PartnerHospital, utcnow

logger = logging.getLogger(__name__)

BOOKING, CHARGE = "booking", "charge"
SOURCES = (BOOKING, CHARGE)
#: How a payment was made.
METHODS = ("chapa", "cash", "card", "mobile_money", "other", "unrecorded")


class LedgerError(ValueError):
    """A settlement the rules refuse."""


def find(session: Session, source_type: str, source_id: str, lock: bool = False) -> Optional[FeeLedgerEntry]:
    query = select(FeeLedgerEntry).where(FeeLedgerEntry.source_type == source_type,
                                         FeeLedgerEntry.source_id == source_id)
    return session.scalar(query.with_for_update() if lock else query)


def record(session: Session, *, source_type: str, source_id: str, hospital_id: str, subtotal: int, fee: int,
           method: str, collected_by: str, paid_at: datetime, user_id: Optional[str] = None,
           dedan_id: Optional[str] = None, reference: Optional[str] = None) -> FeeLedgerEntry:
    """The entry of one paid hospital service, written once (the first one stands)."""
    assert source_type in SOURCES and collected_by in FeeCollector.ALL, (source_type, collected_by)
    existing = find(session, source_type, source_id)
    if existing is not None:
        return existing
    entry = FeeLedgerEntry(
        source_type=source_type, source_id=source_id, hospital_id=hospital_id, user_id=user_id, dedan_id=dedan_id,
        subtotal=subtotal, fee=fee, total=subtotal + fee, method=method if method in METHODS else "other",
        reference=(reference or "")[:100] or None, collected_by=collected_by, paid_at=paid_at,
        settlement_status=FeeSettlement.COLLECTED if collected_by == FeeCollector.ENDOD else FeeSettlement.OWED)
    try:
        with session.begin_nested():
            session.add(entry)
            session.flush()
    except IntegrityError:
        # Written at the same moment by another worker: theirs stands.
        return find(session, source_type, source_id)
    logger.info("fee_ledger_entry source=%s:%s hospital=%s fee=%s collected_by=%s", source_type, source_id,
                hospital_id, fee, collected_by)
    return entry


def mark_refunded(session: Session, source_type: str, source_id: str) -> bool:
    """The payment went back to the patient: no fee is due on it."""
    entry = find(session, source_type, source_id, lock=True)
    if entry is None or entry.settlement_status == FeeSettlement.REFUNDED:
        return False
    if entry.settlement_status == FeeSettlement.SETTLED:
        # The hospital already paid the fee over: a person sorts it out.
        logger.error("ALERT fee_refunded_after_settlement source=%s:%s", source_type, source_id)
    entry.settlement_status, entry.updated_at = FeeSettlement.REFUNDED, utcnow()
    return True


# --- what the super admin sees ----------------------------------------------------------------

def _iso(value: Optional[datetime]) -> Optional[str]:
    return ensure_aware(value).isoformat() if value is not None else None


def entry_out(entry: FeeLedgerEntry, hospital_name: Optional[str] = None) -> Dict[str, Any]:
    return {"id": entry.id, "source_type": entry.source_type, "source_id": entry.source_id,
            "hospital_id": entry.hospital_id, "hospital_name": hospital_name, "dedan_id": entry.dedan_id,
            "subtotal": entry.subtotal, "fee": entry.fee, "total": entry.total, "currency": entry.currency,
            "method": entry.method, "reference": entry.reference, "collected_by": entry.collected_by,
            "paid_at": _iso(entry.paid_at), "settlement_status": entry.settlement_status,
            "settled_at": _iso(entry.settled_at), "settlement_reference": entry.settlement_reference,
            "settled_by": entry.settled_by}


def _names(session: Session, ids: Iterable[str]) -> Dict[str, str]:
    ids = set(ids)
    if not ids:
        return {}
    return dict(session.execute(select(PartnerHospital.id, PartnerHospital.name)
                                .where(PartnerHospital.id.in_(ids))).all())


def _period(query, start: Optional[datetime], end: Optional[datetime]):
    if start is not None:
        query = query.where(FeeLedgerEntry.paid_at >= start)
    if end is not None:
        query = query.where(FeeLedgerEntry.paid_at < end)
    return query


def summary(session: Session, start: Optional[datetime], end: Optional[datetime]) -> Dict[str, Any]:
    """Per hospital, payments made in [start, end): fees collected online by
    Endod, owed by the hospital (not settled yet), settled, and refunded."""
    status = FeeLedgerEntry.settlement_status

    def fees_when(value: str):
        return func.coalesce(func.sum(case((status == value, FeeLedgerEntry.fee), else_=0)), 0)

    query = _period(select(
        FeeLedgerEntry.hospital_id, func.count(), func.coalesce(func.sum(FeeLedgerEntry.subtotal), 0),
        fees_when(FeeSettlement.COLLECTED), fees_when(FeeSettlement.OWED), fees_when(FeeSettlement.SETTLED),
        fees_when(FeeSettlement.REFUNDED),
        func.coalesce(func.sum(case((status == FeeSettlement.OWED, 1), else_=0)), 0),
    ).group_by(FeeLedgerEntry.hospital_id), start, end)
    rows = list(session.execute(query))
    names = _names(session, (r[0] for r in rows))
    hospitals = []
    for hospital_id, count, subtotal, collected, owed, settled, refunded, owed_count in rows:
        hospitals.append({"hospital_id": hospital_id, "hospital_name": names.get(hospital_id),
                          "payments": int(count), "subtotal": int(subtotal), "fees_collected": int(collected),
                          "fees_owed": int(owed), "fees_settled": int(settled), "fees_refunded": int(refunded),
                          "owed_entries": int(owed_count),
                          "fees_total": int(collected) + int(owed) + int(settled)})
    hospitals.sort(key=lambda h: (-h["fees_owed"], -h["fees_total"], h["hospital_name"] or h["hospital_id"]))
    totals = {key: sum(h[key] for h in hospitals) for key in (
        "payments", "subtotal", "fees_collected", "fees_owed", "fees_settled", "fees_refunded", "fees_total")}
    return {"currency": "ETB", "from": _iso(start), "to": _iso(end), "hospitals": hospitals, "totals": totals}


def entries(session: Session, *, hospital_id: Optional[str], status: Optional[str], source_type: Optional[str],
            start: Optional[datetime], end: Optional[datetime], limit: int, offset: int) -> Dict[str, Any]:
    query = _period(select(FeeLedgerEntry), start, end)
    count = _period(select(func.count()).select_from(FeeLedgerEntry), start, end)
    for column, value in ((FeeLedgerEntry.hospital_id, hospital_id), (FeeLedgerEntry.settlement_status, status),
                          (FeeLedgerEntry.source_type, source_type)):
        if value:
            query, count = query.where(column == value), count.where(column == value)
    rows = list(session.scalars(query.order_by(FeeLedgerEntry.paid_at.desc(), FeeLedgerEntry.id)
                                .limit(limit).offset(offset)))
    names = _names(session, (r.hospital_id for r in rows))
    return {"items": [entry_out(r, names.get(r.hospital_id)) for r in rows],
            "total": int(session.scalar(count) or 0), "limit": limit, "offset": offset}


def settle(session: Session, hospital_id: str, entry_ids: List[str], reference: str, actor_email: str) \
        -> Dict[str, Any]:
    """Mark these owed fees of one hospital as paid to Endod (all or nothing)."""
    ids = list(dict.fromkeys(entry_ids))
    rows = list(session.scalars(select(FeeLedgerEntry).where(FeeLedgerEntry.id.in_(ids))
                                .order_by(FeeLedgerEntry.id).with_for_update()))
    found = {r.id: r for r in rows}
    missing = [i for i in ids if i not in found or found[i].hospital_id != hospital_id]
    if missing:
        raise LedgerError(f"{len(missing)} of these entries are not this hospital's.")
    not_owed = [r.id for r in rows if r.settlement_status != FeeSettlement.OWED]
    if not_owed:
        raise LedgerError(f"{len(not_owed)} of these entries are not owed (already settled, collected online "
                          "or refunded). Reload and try again.")
    now = utcnow()
    for row in rows:
        row.settlement_status, row.settled_at = FeeSettlement.SETTLED, now
        row.settlement_reference, row.settled_by, row.updated_at = reference, actor_email, now
    amount = sum(r.fee for r in rows)
    logger.info("fees_settled hospital=%s entries=%s amount=%s reference=%s by=%s", hospital_id, len(rows), amount,
                reference, actor_email)
    return {"hospital_id": hospital_id, "settled": len(rows), "amount": amount, "currency": "ETB",
            "reference": reference, "settled_at": now.isoformat()}
