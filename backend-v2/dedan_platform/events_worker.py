"""The event worker: ``python -m dedan_platform.events_worker``.

Sends this platform's queued events (bookings, cancellations) to the hospital
service and applies the hospital service's (listings, decisions on bookings).
It also re-checks pending Chapa deposits now and then, in case a webhook was
missed. Survives Redis being down or failing over: it waits and reconnects
(through Sentinel, to whichever server is master); events wait in the
database meanwhile.
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import timedelta

import redis
from sqlalchemy import select

from dedan_platform import chapa, deposits, eventbus, hospital_bookings
from dedan_platform.db import session_scope
from dedan_platform.models import Deposit, DepositStatus, utcnow

logger = logging.getLogger("dedan.events_worker")
_running = True

DEPOSITS_EVERY = 300
HOUSEKEEPING_EVERY = 3600
_last = {"deposits": 0.0, "housekeeping": 0.0}


def _stop(*_args) -> None:
    global _running
    _running = False


def recheck_deposits() -> int:
    """Settle deposits still pending after a few minutes (a missed webhook)."""
    cutoff = utcnow() - timedelta(minutes=3)
    with session_scope() as session:
        refs = list(session.scalars(select(Deposit.tx_ref).where(
            Deposit.status == DepositStatus.PENDING, Deposit.created_at < cutoff).limit(50)))
    settled = 0
    for tx_ref in refs:
        try:
            deposits.settle(tx_ref)
            settled += 1
        except chapa.ChapaError as exc:
            logger.warning("deposit_recheck_failed tx_ref=%s %s", tx_ref, exc)
    return settled


def run_once(client: redis.Redis, now: float | None = None) -> int:
    now = time.monotonic() if now is None else now
    work = eventbus.publish_pending(client)
    work += eventbus.consume_once(client, hospital_bookings.HANDLERS, block_ms=1000)
    if now - _last["deposits"] >= DEPOSITS_EVERY:
        _last["deposits"] = now
        try:
            work += recheck_deposits()
        except chapa.ChapaNotConfigured:
            pass
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
    logger.info("worker_stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
