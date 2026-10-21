"""The event worker: ``python -m dedan_platform.events_worker``.

Sends this platform's queued events (bookings, cancellations, shared records)
to the hospital service and applies the hospital service's (listings,
decisions on bookings, links, records, follow-ups, queues). It also re-checks
pending Chapa deposits now and then, in case a webhook was missed, ends
expired record shares, and (on a thread of its own) downloads record files.
Survives Redis being down or failing over: it waits and reconnects
(through Sentinel, to whichever server is master); events wait in the
database meanwhile.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import timedelta

import redis
from sqlalchemy import or_, select

from dedan_platform import chapa, deposits, eventbus, hospital_bookings, patient_history, record_files, shares
from dedan_platform.db import session_scope
from dedan_platform.models import Deposit, DepositStatus, utcnow

logger = logging.getLogger("dedan.events_worker")
_running = True

DEPOSITS_EVERY = 300
STALE_EVERY = 300
SHARES_EVERY = 60
HOUSEKEEPING_EVERY = 3600
_last = {"deposits": 0.0, "stale": 0.0, "shares": 0.0, "housekeeping": 0.0}

#: Every event this worker handles: bookings and listings, and patient history.
HANDLERS = {**hospital_bookings.HANDLERS, **patient_history.HANDLERS}


def _stop(*_args) -> None:
    global _running
    _running = False


#: Seconds a round may spend asking Chapa, so events are never held up long.
RECHECK_BUDGET = 15


def recheck_deposits(budget_seconds: float = RECHECK_BUDGET) -> int:
    """Settle deposits still pending a few minutes on (a missed webhook):
    newest and least recently checked first, within a time budget."""
    now = utcnow()
    with session_scope() as session:
        refs = list(session.scalars(select(Deposit.tx_ref).where(
            Deposit.status == DepositStatus.PENDING,
            Deposit.created_at < now - timedelta(minutes=3),
            or_(Deposit.last_checked_at.is_(None), Deposit.last_checked_at < now - timedelta(minutes=10)),
        ).order_by(Deposit.created_at.desc()).limit(20)))
    settled, started = 0, time.monotonic()
    for tx_ref in refs:
        if time.monotonic() - started > budget_seconds:
            break
        try:
            deposits.settle(tx_ref)
            settled += 1
        except chapa.ChapaError as exc:
            logger.warning("deposit_recheck_failed tx_ref=%s %s", tx_ref, exc)
            with session_scope() as session:
                deposit = session.scalar(select(Deposit).where(Deposit.tx_ref == tx_ref))
                if deposit is not None:
                    deposit.last_checked_at = utcnow()
    return settled


def run_once(client: redis.Redis, now: float | None = None) -> int:
    now = time.monotonic() if now is None else now
    work = eventbus.publish_pending(client)
    work += eventbus.consume_once(client, HANDLERS, block_ms=1000)
    if now - _last["deposits"] >= DEPOSITS_EVERY:
        _last["deposits"] = now
        try:
            work += recheck_deposits()
        except chapa.ChapaNotConfigured:
            pass
    if now - _last["stale"] >= STALE_EVERY:
        _last["stale"] = now
        work += hospital_bookings.refund_unanswered()
    if now - _last["shares"] >= SHARES_EVERY:
        _last["shares"] = now
        # Shares whose end has come: the hospital is told to delete its copy.
        work += shares.expire_due()
    if now - _last["housekeeping"] >= HOUSEKEEPING_EVERY:
        eventbus.housekeeping(client)
        _last["housekeeping"] = now
    return work


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    from dedan_platform.db import create_all

    create_all()
    from dedan_platform import partner_config

    logger.info("events_worker_started record_file_downloads=%s",
                "on" if partner_config.hospital_api_url() and partner_config.platform_admin_key() else "OFF")
    # Record files are fetched on a thread of their own, so a slow hospital
    # API never holds up events.
    import threading

    stop_downloads = threading.Event()
    downloads = threading.Thread(target=record_files.run_forever, args=(stop_downloads,),
                                 name="record-files", daemon=True)
    downloads.start()
    backoff = 1.0
    client = None
    while _running:
        try:
            if client is None:
                client = eventbus.connect()
                if client is None:
                    logger.error("No Redis configured (REDIS_URL or REDIS_SENTINELS).")
                    time.sleep(30)
                    continue
            run_once(client)
            backoff = 1.0
        except (redis.ConnectionError, redis.TimeoutError, redis.sentinel.MasterNotFoundError) as exc:
            logger.warning("redis_unavailable %s; retrying in %.0fs", exc, backoff)
            client = None
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except Exception:  # noqa: BLE001 -- keep the worker alive; events are retried
            logger.exception("worker_round_failed")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
    stop_downloads.set()
    downloads.join(timeout=35)
    logger.info("worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
