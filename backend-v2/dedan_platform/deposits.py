"""Adding money to the Endod balance through Chapa.

``start`` creates a pending deposit and Chapa's checkout page. ``settle`` asks
Chapa whether that payment went through and, if it did for the expected
amount in birr, credits the balance once (the deposit row is locked and the
ledger allows one entry per deposit). Chapa's webhook and callback, and the
patient coming back to the app, all call ``settle``; none is trusted alone.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

from sqlalchemy import select

from dedan_platform import chapa, identity, partner_config, wallet
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import Deposit, DepositStatus, WalletEntryKind, utcnow

logger = logging.getLogger(__name__)

#: A deposit still unpaid after this long is closed as failed.
ABANDONED_AFTER = timedelta(hours=24)


class DepositError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _payload(deposit: Deposit) -> Dict[str, Any]:
    return {
        "deposit_id": deposit.id,
        "amount": deposit.amount,
        "status": deposit.status,
        "checkout_url": deposit.checkout_url if deposit.status == DepositStatus.PENDING else None,
        "failure": deposit.failure,
        "created_at": ensure_aware(deposit.created_at).isoformat(),
        "completed_at": ensure_aware(deposit.completed_at).isoformat() if deposit.completed_at else None,
    }


def start(user_id: str, amount: int) -> Dict[str, Any]:
    """Begin a deposit of ``amount`` santim. Returns the Chapa checkout URL."""
    if not partner_config.DEPOSIT_MIN <= amount <= partner_config.DEPOSIT_MAX:
        raise DepositError(f"Deposits are from {wallet.birr(partner_config.DEPOSIT_MIN)} to "
                           f"{wallet.birr(partner_config.DEPOSIT_MAX)} birr.")
    if not partner_config.chapa_secret_key():
        raise DepositError("Payments are not set up yet.", 503)
    profile = identity.get_profile_payload(user_id)
    with session_scope() as session:
        deposit = Deposit(user_id=user_id, tx_ref=chapa.new_tx_ref(), amount=amount)
        session.add(deposit)
        session.flush()
        deposit_id, tx_ref = deposit.id, deposit.tx_ref
    base = partner_config.public_app_url()
    try:
        checkout = chapa.initialize(
            tx_ref, amount, profile.get("first_name") or "", profile.get("last_name") or "",
            profile.get("phone"),
            return_url=f"{base}/interview?section=wallet&deposit={deposit_id}",
            callback_url=f"{base}/api/payments/chapa/callback",
        )
    except chapa.ChapaError as exc:
        with session_scope() as session:
            deposit = session.get(Deposit, deposit_id, with_for_update=True)
            deposit.status, deposit.failure, deposit.completed_at = DepositStatus.FAILED, str(exc)[:200], utcnow()
        raise DepositError(str(exc), 502) from exc
    with session_scope() as session:
        deposit = session.get(Deposit, deposit_id, with_for_update=True)
        deposit.checkout_url = checkout
        return _payload(deposit)


def settle(tx_ref: str) -> Optional[Dict[str, Any]]:
    """Check a deposit with Chapa and credit it if paid. Returns the deposit, or None if unknown."""
    with session_scope() as session:
        deposit = session.scalar(select(Deposit).where(Deposit.tx_ref == tx_ref))
        if deposit is None:
            return None
        if deposit.status != DepositStatus.PENDING:
            return _payload(deposit)
        deposit_id = deposit.id
    record = chapa.verify(tx_ref)
    with session_scope() as session:
        deposit = session.get(Deposit, deposit_id, with_for_update=True)
        if deposit.status != DepositStatus.PENDING:
            return _payload(deposit)  # settled meanwhile by another notification
        if record["paid"]:
            if record["amount"] != deposit.amount or (record.get("currency") or "ETB") != "ETB":
                # Never credit an amount other than the one asked for.
                logger.error("deposit_amount_mismatch tx_ref=%s expected=%s got=%s %s",
                             tx_ref, deposit.amount, record["amount"], record.get("currency"))
                deposit.status, deposit.failure = DepositStatus.FAILED, "Amount did not match; contact Endod."
                deposit.completed_at = utcnow()
                return _payload(deposit)
            wallet.post(session, deposit.user_id, WalletEntryKind.DEPOSIT, deposit.amount, deposit_id=deposit.id,
                        description="Deposit through Chapa")
            deposit.status, deposit.completed_at = DepositStatus.SUCCEEDED, utcnow()
            deposit.provider_reference = (record.get("reference") or "")[:100] or None
            user_id, amount = deposit.user_id, deposit.amount
            result = _payload(deposit)
        else:
            stale = utcnow() - ensure_aware(deposit.created_at) > ABANDONED_AFTER
            if record.get("failed") or stale:
                deposit.status, deposit.completed_at = DepositStatus.FAILED, utcnow()
                deposit.failure = "Payment was not completed."
            return _payload(deposit)
    from dedan_platform import inbox

    inbox.add_item(user_id, "messages", "deposit_received", "Money added",
                   body=f"{wallet.birr(amount)} birr was added to your Endod balance.")
    return result


def status_for(user_id: str, deposit_id: str) -> Dict[str, Any]:
    """The patient's own deposit; checked with Chapa while still pending."""
    with session_scope() as session:
        deposit = session.scalar(select(Deposit).where(Deposit.id == deposit_id, Deposit.user_id == user_id))
        if deposit is None:
            raise DepositError("Deposit not found.", 404)
        if deposit.status != DepositStatus.PENDING:
            return _payload(deposit)
        tx_ref = deposit.tx_ref
    try:
        return settle(tx_ref) or {}
    except chapa.ChapaError:
        with session_scope() as session:
            return _payload(session.get(Deposit, deposit_id))
