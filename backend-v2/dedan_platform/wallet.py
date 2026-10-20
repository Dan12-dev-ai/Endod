"""A patient's Endod balance: deposit through Chapa, pay hospitals, get refunds.

Money is in santim (integer, 1/100 birr), never floats. Every movement is a
``WalletEntry`` (append-only); ``Wallet.balance`` is their running sum, kept on
a row that is locked for each movement, so two payments at once cannot both
spend the same birr. The balance cannot be withdrawn: it pays for health
services, and refunds come back into it.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dedan_platform import partner_config
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import Wallet, WalletEntry, WalletEntryKind, utcnow


class WalletError(RuntimeError):
    """A wallet operation failed."""


class InsufficientFunds(WalletError):
    def __init__(self, needed: int, balance: int):
        super().__init__(
            f"Your balance is {birr(balance)} birr; this needs {birr(needed)} birr. Add money to continue."
        )
        self.needed = needed
        self.balance = balance


def birr(santim: int) -> str:
    """Santim as birr text with two decimals, e.g. 15050 -> '150.50'."""
    return f"{Decimal(santim) / 100:.2f}"


def service_fee(price: int) -> int:
    """Endod's fee on a payment of ``price`` santim (flat part plus a share)."""
    share = price * partner_config.service_fee_percent_hundredths() // 10_000
    return partner_config.service_fee_flat() + share


def _wallet_for_update(session: Session, user_id: str) -> Wallet:
    wallet = session.get(Wallet, user_id, with_for_update=True)
    if wallet is None:
        try:
            with session.begin_nested():
                session.add(Wallet(user_id=user_id, balance=0))
        except IntegrityError:
            pass  # created by a concurrent first movement
        wallet = session.get(Wallet, user_id, with_for_update=True, populate_existing=True)
    return wallet


def post(
    session: Session,
    user_id: str,
    kind: str,
    amount: int,
    *,
    appointment_id: Optional[str] = None,
    deposit_id: Optional[str] = None,
    description: Optional[str] = None,
    allow_negative: bool = False,
) -> WalletEntry:
    """Record one movement in the caller's transaction. Raises InsufficientFunds
    (unless ``allow_negative``: only for taking back a reversed deposit)."""
    if kind not in WalletEntryKind.ALL:
        raise WalletError(f"Unknown wallet entry kind {kind!r}.")
    if amount == 0:
        raise WalletError("A wallet movement cannot be zero.")
    wallet = _wallet_for_update(session, user_id)
    new_balance = wallet.balance + amount
    if new_balance < 0 and not allow_negative:
        raise InsufficientFunds(needed=-amount, balance=wallet.balance)
    entry = WalletEntry(
        user_id=user_id, kind=kind, amount=amount, balance_after=new_balance,
        appointment_id=appointment_id, deposit_id=deposit_id, description=(description or "")[:200] or None,
    )
    session.add(entry)
    wallet.balance = new_balance
    wallet.updated_at = utcnow()
    session.flush()
    return entry


def balance_of(session: Session, user_id: str) -> int:
    wallet = session.get(Wallet, user_id)
    return wallet.balance if wallet else 0


def entry_payload(entry: WalletEntry) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "amount": entry.amount,
        "balance_after": entry.balance_after,
        "appointment_id": entry.appointment_id,
        "deposit_id": entry.deposit_id,
        "description": entry.description,
        "created_at": ensure_aware(entry.created_at).isoformat(),
    }


def summary(user_id: str, limit: int = 50) -> Dict[str, Any]:
    with session_scope() as session:
        entries: List[WalletEntry] = list(session.scalars(
            select(WalletEntry).where(WalletEntry.user_id == user_id)
            .order_by(WalletEntry.created_at.desc(), WalletEntry.id.desc()).limit(limit)
        ))
        return {
            "balance": balance_of(session, user_id),
            "currency": "ETB",
            "entries": [entry_payload(e) for e in entries],
            "service_fee": {
                "flat": partner_config.service_fee_flat(),
                "percent_hundredths": partner_config.service_fee_percent_hundredths(),
            },
        }
