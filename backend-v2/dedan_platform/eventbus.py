"""Events between the patient platform and the Endod hospital service (Redis Streams).

Two streams, one per direction (the contract is in docs/events.md of the
hospital service repository):

* ``endod:patient``: what this platform publishes (bookings, cancellations);
* ``endod:hospital``: what the hospital service publishes (hospital listings,
  decisions on bookings), read here with the consumer group ``patient-platform``.

Delivery is at least once, and handling is exactly once:

* **Outbox.** :func:`emit` writes the event into ``outbox_events`` in the same
  transaction as the change it describes. :func:`publish_pending` sends
  unsent rows to Redis, in order, from one publisher at a time (a database
  lock), and marks them sent only after Redis (and, when configured, a
  replica) has them. If Redis is down, events wait in the database.
* **Inbox.** Each received event's id is recorded in ``processed_events`` in
  the same transaction as its effect, so a redelivered event is skipped.
* **Retries.** A failed event stays pending in the group and is claimed again
  after :data:`RETRY_AFTER_MS`; after :data:`MAX_DELIVERIES` attempts, or at
  once for a malformed event (:class:`PermanentEventError`), it goes to
  ``endod:dead-letter`` for a person to look at.

Redis is reached through Sentinel when ``REDIS_SENTINELS`` is set (the current
master is looked up on every connect, so a failover is followed), or directly
through ``REDIS_URL``.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import time
from datetime import timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import redis
    from redis.sentinel import Sentinel
except ImportError:  # redis is optional for offline/dev runs without a broker
    redis = None  # type: ignore[assignment]
    Sentinel = None  # type: ignore[assignment]
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dedan_platform import partner_config as config
from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import OutboxEvent, ProcessedEvent, utcnow

logger = logging.getLogger("dedan.events")

SOURCE = "patient-platform"
STREAM_OUT = "endod:patient"
STREAM_IN = "endod:hospital"
DEAD_LETTER = "endod:dead-letter"
GROUP = "patient-platform"
#: A pending event not acknowledged for this long is retried.
RETRY_AFTER_MS = 30_000
MAX_DELIVERIES = 5
#: Stream entries older than this are trimmed (well past any retry).
KEEP_STREAM_FOR = timedelta(days=7)
#: Sent outbox rows and handled-event ids are deleted after this.
KEEP_RECORDS_FOR = timedelta(days=30)
#: Postgres advisory lock id: one publisher at a time keeps events in order.
_PUBLISH_LOCK = 0x45_4E_44_4F_44  # "ENDOD"

Handler = Callable[[Session, Dict[str, Any]], None]


class PermanentEventError(ValueError):
    """The event can never be handled (malformed): dead-letter it at once."""


class RetryLater(RuntimeError):
    """The event cannot be handled yet (e.g. it refers to one not received yet)."""


# --- connection -------------------------------------------------------------------

def connect() -> Optional[redis.Redis]:
    """A client for the current Redis master, or None when no Redis is configured."""
    if redis is None:
        return None
    common = {"decode_responses": True, "socket_timeout": 5, "socket_connect_timeout": 5,
              "health_check_interval": 30}
    if config.redis_sentinels():
        sentinels = []
        for entry in config.redis_sentinels():
            host, _, port = entry.rpartition(":")
            sentinels.append((host, int(port or 26379)))
        sentinel_password = config.redis_sentinel_password()
        sentinel = Sentinel(sentinels, socket_timeout=5,
                            sentinel_kwargs={"password": sentinel_password} if sentinel_password else None)
        return sentinel.master_for(config.redis_sentinel_master(), password=config.redis_password(), **common)
    if config.redis_url():
        return redis.Redis.from_url(config.redis_url(), **common)
    return None


# --- publishing ------------------------------------------------------------------------

def after_commit(session: Session, action: Callable[[], None]) -> None:
    """Run ``action`` once the handler's transaction has committed.

    For side effects that open their own sessions (inbox items, cancelling
    reminders): run inside the transaction they would wait on its locks, and
    if the transaction rolled back they must not happen at all.
    """
    session.info.setdefault("after_commit", []).append(action)


def emit(session: Session, event_type: str, payload: Dict[str, Any]) -> None:
    """Queue an event; it is sent once the caller's transaction commits."""
    session.add(OutboxEvent(type=event_type, payload=json.dumps(payload, default=str, ensure_ascii=False)))


def _publisher_lock(session: Session) -> bool:
    """Only one publisher at a time (on Postgres): otherwise two workers could
    send rows out of order. SQLite has one writer anyway."""
    if session.get_bind().dialect.name != "postgresql":
        return True
    return bool(session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _PUBLISH_LOCK}))


def publish_pending(client: redis.Redis, batch: int = 100) -> int:
    """Send unsent events in order. Returns how many were sent."""
    min_replicas = config.redis_min_replicas()
    with session_scope() as session:
        if not _publisher_lock(session):
            return 0  # another worker is publishing
        rows = list(session.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.created_at, OutboxEvent.id).limit(batch)
        ))
        if not rows:
            return 0
        pipe = client.pipeline(transaction=False)
        for row in rows:
            pipe.xadd(STREAM_OUT, {
                "id": row.id,
                "type": row.type,
                "source": SOURCE,
                "occurred_at": ensure_aware(row.created_at).astimezone(timezone.utc).isoformat(),
                "payload": row.payload,
            })
        pipe.execute()
        if min_replicas > 0:
            # Redis replication is asynchronous: wait until a replica has the
            # events, or a failover could lose them after we marked them sent.
            acknowledged = client.wait(min_replicas, 2000)
            if acknowledged < min_replicas:
                raise redis.ConnectionError(f"only {acknowledged} replica(s) confirmed the events")
        now = utcnow()
        for row in rows:
            row.published_at = now
        # If this commit fails, the rows are sent again and the receiver's
        # inbox drops the duplicates.
        return len(rows)


def housekeeping(client: redis.Redis) -> None:
    """Trim old stream entries and delete old records (run now and then)."""
    cutoff_ms = int((time.time() - KEEP_STREAM_FOR.total_seconds()) * 1000)
    client.xtrim(STREAM_OUT, minid=f"{cutoff_ms}-0", approximate=True)
    cutoff = utcnow() - KEEP_RECORDS_FOR
    with session_scope() as session:
        session.execute(delete(OutboxEvent).where(OutboxEvent.published_at.is_not(None),
                                                  OutboxEvent.published_at < cutoff))
        session.execute(delete(ProcessedEvent).where(ProcessedEvent.processed_at < cutoff))


# --- consuming ---------------------------------------------------------------------------

def ensure_group(client: redis.Redis) -> None:
    try:
        client.xgroup_create(STREAM_IN, GROUP, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


#: Unique per process: two workers on one host must not share a name.
_CONSUMER = f"{socket.gethostname()}-{os.getpid()}-{secrets.token_hex(3)}"


def consumer_name() -> str:
    return _CONSUMER


def consume_once(client: redis.Redis, handlers: Dict[str, Handler], consumer: Optional[str] = None,
                 block_ms: int = 2000, count: int = 50) -> int:
    """Handle stalled events, then new ones. Returns how many were handled."""
    consumer = consumer or consumer_name()
    messages: List[Tuple[str, Dict[str, str]]] = []
    try:
        claimed = client.xautoclaim(STREAM_IN, GROUP, consumer, min_idle_time=RETRY_AFTER_MS,
                                    start_id="0-0", count=count)
    except redis.ResponseError as exc:
        if "NOGROUP" not in str(exc):
            raise
        # First run, or a Redis that restarted empty: create the group (from
        # the start of the stream, so nothing already there is skipped).
        ensure_group(client)
        claimed = (None, [], [])
    for message_id, fields in claimed[1]:
        if fields:
            messages.append((message_id, fields))
        else:
            # The entry was trimmed while pending (Redis 6.2 still lists it).
            client.xack(STREAM_IN, GROUP, message_id)
    fresh = client.xreadgroup(GROUP, consumer, {STREAM_IN: ">"}, count=count, block=block_ms)
    for _stream, entries in fresh or []:
        messages.extend(entries)
    for message_id, fields in messages:
        _handle(client, message_id, fields, handlers)
    return len(messages)


def _already_processed(event_id: str) -> bool:
    with session_scope() as session:
        return session.get(ProcessedEvent, event_id) is not None


def _dead_letter(client: redis.Redis, message_id: str, fields: Dict[str, str], why: str) -> None:
    client.xadd(DEAD_LETTER, {**fields, "stream": STREAM_IN, "group": GROUP, "error": why[:500]})
    client.xack(STREAM_IN, GROUP, message_id)
    logger.error("event_dead_lettered type=%s id=%s error=%s", fields.get("type"), fields.get("id"), why)


def _handle(client: redis.Redis, message_id: str, fields: Dict[str, str], handlers: Dict[str, Handler]) -> None:
    event_id, event_type = fields.get("id"), fields.get("type")
    handler = handlers.get(event_type or "")
    if not event_id or handler is None:
        # Not for us (or malformed): acknowledge so it does not block the group.
        logger.info("event_ignored type=%s id=%s", event_type, event_id)
        client.xack(STREAM_IN, GROUP, message_id)
        return
    try:
        try:
            payload = json.loads(fields.get("payload") or "{}")
        except ValueError as exc:
            raise PermanentEventError("payload is not JSON") from exc
        if not isinstance(payload, dict):
            raise PermanentEventError("payload is not an object")
        deferred: List[Callable[[], None]] = []
        with session_scope() as session:
            if session.get(ProcessedEvent, event_id) is None:
                handler(session, payload)
                session.add(ProcessedEvent(id=event_id, type=event_type))
                deferred = list(session.info.get("after_commit", []))
        client.xack(STREAM_IN, GROUP, message_id)
        for action in deferred:
            try:
                action()
            except Exception:  # noqa: BLE001 -- the event's effect is committed; a side effect is best effort
                logger.exception("after_commit_failed type=%s id=%s", event_type, event_id)
    except PermanentEventError as exc:
        _dead_letter(client, message_id, fields, f"invalid: {exc}")
    except Exception as exc:  # noqa: BLE001 -- retried, then dead-lettered
        if isinstance(exc, IntegrityError) and _already_processed(event_id):
            # Another worker handled the same event at the same moment.
            client.xack(STREAM_IN, GROUP, message_id)
            return
        if isinstance(exc, RetryLater):
            logger.info("event_deferred type=%s id=%s: %s", event_type, event_id, exc)
        else:
            logger.exception("event_failed type=%s id=%s", event_type, event_id)
        if _deliveries(client, message_id) >= MAX_DELIVERIES:
            _dead_letter(client, message_id, fields, repr(exc))


def _deliveries(client: redis.Redis, message_id: str) -> int:
    pending = client.xpending_range(STREAM_IN, GROUP, min=message_id, max=message_id, count=1)
    return int(pending[0]["times_delivered"]) if pending else 0
