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
from typing import Any, Dict, Optional, Tuple

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


def settle(tx_ref: str, recheck_settled: bool = False) -> Optional[Dict[str, Any]]:
    """Check a deposit with Chapa and credit it if paid. Returns the deposit, or None if unknown.

    A pending or failed deposit Chapa reports as paid (for the right amount
    in birr) is credited, once. With ``recheck_settled`` (Chapa's webhook told
    of a refund or reversal), a credited deposit is checked again and taken
    back if Chapa reversed it. Raises ChapaError when Chapa gave no answer.
    """
    with session_scope() as session:
        deposit = session.scalar(select(Deposit).where(Deposit.tx_ref == tx_ref))
        if deposit is None:
            return None
        settled = deposit.status in (DepositStatus.SUCCEEDED, DepositStatus.REVERSED)
        if settled and not (recheck_settled and deposit.status == DepositStatus.SUCCEEDED):
            return _payload(deposit)
        deposit_id = deposit.id
    record = chapa.verify(tx_ref)
    notify: Optional[Tuple[str, str, str]] = None
    with session_scope() as session:
        deposit = session.get(Deposit, deposit_id, with_for_update=True)
        deposit.last_checked_at = utcnow()
        if deposit.status == DepositStatus.SUCCEEDED:
            if record.get("reversed"):
                # Chapa gave the money back to the payer: take the credit back.
                wallet.post(session, deposit.user_id, WalletEntryKind.REVERSAL, -deposit.amount,
                            deposit_id=deposit.id, description="Deposit refunded by Chapa", allow_negative=True)
                deposit.status, deposit.failure = DepositStatus.REVERSED, "Refunded or reversed at Chapa."
                logger.warning("deposit_reversed tx_ref=%s amount=%s", tx_ref, deposit.amount)
                notify = (deposit.user_id, "Deposit reversed",
                          f"{wallet.birr(deposit.amount)} birr was refunded to you by Chapa and taken off your balance.")
            result = _payload(deposit)
        elif deposit.status == DepositStatus.REVERSED:
            result = _payload(deposit)
        elif record["paid"]:
            if record["amount"] != deposit.amount or (record.get("currency") or "ETB") != "ETB":
                # Never credit an amount other than the one asked for; a person
                # sorts it out (the patient was charged something).
                logger.error("ALERT deposit_amount_mismatch tx_ref=%s expected=%s got=%s %s",
                             tx_ref, deposit.amount, record["amount"], record.get("currency"))
                deposit.status, deposit.failure = DepositStatus.FAILED, "Amount did not match; contact Endod."
                deposit.completed_at = utcnow()
                notify = (deposit.user_id, "Deposit needs checking",
                          "Your payment did not match the amount requested. Endod will contact you; "
                          "nothing is lost.")
            else:
                wallet.post(session, deposit.user_id, WalletEntryKind.DEPOSIT, deposit.amount,
                            deposit_id=deposit.id, description="Deposit through Chapa")
                deposit.status, deposit.completed_at, deposit.failure = DepositStatus.SUCCEEDED, utcnow(), None
                deposit.provider_reference = (record.get("reference") or "")[:100] or None
                notify = (deposit.user_id, "Money added",
                          f"{wallet.birr(deposit.amount)} birr was added to your Endod balance.")
            result = _payload(deposit)
        else:
            # Closed only on Chapa's definite word (failed, or no such payment
            # a day later); a pending one stays pending.
            stale = utcnow() - ensure_aware(deposit.created_at) > ABANDONED_AFTER
            if deposit.status == DepositStatus.PENDING and (record.get("failed") and (record.get("known") or stale)):
                deposit.status, deposit.completed_at = DepositStatus.FAILED, utcnow()
                deposit.failure = "Payment was not completed."
            result = _payload(deposit)
    if notify:
        from dedan_platform import inbox

        try:
            kind = "deposit_received" if notify[1] == "Money added" else "deposit_update"
            inbox.add_item(notify[0], "messages", kind, notify[1], body=notify[2])
        except Exception:  # noqa: BLE001 -- the money moved; the message is best effort
            logger.exception("deposit_inbox_failed tx_ref=%s", tx_ref)
    return result


def status_for(user_id: str, deposit_id: str) -> Dict[str, Any]:
    """The patient's own deposit; checked with Chapa while still pending."""
    with session_scope() as session:
        deposit = session.scalar(select(Deposit).where(Deposit.id == deposit_id, Deposit.user_id == user_id))
        if deposit is None:
            raise DepositError("Deposit not found.", 404)
        if deposit.status not in (DepositStatus.PENDING, DepositStatus.FAILED):
            return _payload(deposit)
        tx_ref = deposit.tx_ref
    try:
        return settle(tx_ref) or {}
    except chapa.ChapaError:
        with session_scope() as session:
            return _payload(session.get(Deposit, deposit_id))
