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
  A sent row keeps its id, type and times, but its ``payload`` (bookings
  with the patient's notes, shared records, dispensed medicines) is emptied
  at once: the database keeps no second copy of clinical data that has
  already left it. ``processed_events`` holds ids and types only.
* **Inbox.** Each received event's id is recorded in ``processed_events`` in
  the same transaction as its effect, so a redelivered event is skipped.
* **Retries.** A failed event stays pending in the group and is claimed again
  after :data:`RETRY_AFTER_MS`; after :data:`MAX_DELIVERIES` attempts, or at
  once for a malformed event (:class:`PermanentEventError`), it goes to
  ``endod:dead-letter`` for a person to look at -- without its clinical
  content: the event's id, type and times, the error (input values removed)
  and the payload's identifiers only (:func:`redacted`). The dead-letter
  stream is capped at :data:`DEAD_LETTER_MAXLEN` entries.

Clinical data in Redis. Event payloads (bookings with the patient's notes,
shared records, dispensed medicines, records from hospitals) cross Redis in
plaintext: the hospital service, another system, reads them as they are.
They stay there only while in flight: an entry is deleted
(:func:`trim_acknowledged`) as soon as every consumer group of its stream
has acknowledged it -- ``endod:hospital`` after each batch handled here,
``endod:patient`` every :data:`TRIM_OUT_EVERY` seconds once the hospital
service has acknowledged. An entry never acknowledged (the other side down)
is kept at most :data:`KEEP_STREAM_FOR`. Redis's append-only file still holds
deleted entries until it is rewritten, which deploy/redis/redis.sh does
every hour on each server (and there are no RDB snapshots).

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
from sqlalchemy import delete, select, text, update
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
#: Stream entries never acknowledged are trimmed after this (well past any
#: retry); acknowledged ones go at once (trim_acknowledged).
KEEP_STREAM_FOR = timedelta(days=7)
#: How often the run loop deletes acknowledged entries of endod:patient.
TRIM_OUT_EVERY = 30
#: The dead-letter stream keeps about this many entries.
DEAD_LETTER_MAXLEN = 10_000
#: Payload keys a dead letter keeps (identifiers, to find the event again);
#: every other key is listed by name only.
DEAD_LETTER_PAYLOAD_KEYS = frozenset({
    "request_id", "record_id", "hospital_id", "appointment_id", "booking_id", "visit_id", "share_id",
    "follow_up_id", "rx_id", "file_id", "event_id", "dedan_id", "patient_id", "version", "status",
})
#: Sent outbox rows (already without payload) and handled-event ids are deleted after this.
KEEP_RECORDS_FOR = timedelta(days=30)
#: What a sent row's payload becomes (the column is NOT NULL).
PURGED = ""
#: The events worker's last round (ISO time, UTC), for the admin's health
#: page (api_admin.py). Expires on its own if the worker stops.
HEARTBEAT_KEY = "endod:events-worker:heartbeat"
HEARTBEAT_TTL_SECONDS = 600
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


def event_time(session: Session):
    """When the event being handled was sent (its envelope's ``occurred_at``,
    aware UTC), or None outside the worker or for an unreadable time."""
    from datetime import datetime

    raw = (session.info.get("event") or {}).get("occurred_at")
    try:
        when = datetime.fromisoformat(raw) if raw else None
    except (TypeError, ValueError):
        return None
    if when is None or when.tzinfo is None:
        return None
    return when.astimezone(timezone.utc)


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
            # Sent: no copy of what may be clinical data stays here.
            row.payload = PURGED
        # If this commit fails, the rows (payloads intact) are sent again and
        # the receiver's inbox drops the duplicates.
        return len(rows)


def purge_sent_payloads() -> int:
    """Empty the payload of every sent outbox row (rows sent before payloads
    were purged on sending). Returns how many were emptied."""
    with session_scope() as session:
        return session.execute(update(OutboxEvent).where(
            OutboxEvent.published_at.is_not(None), OutboxEvent.payload != PURGED,
        ).values(payload=PURGED).execution_options(synchronize_session=False)).rowcount


def _stream_id(value: str) -> Tuple[int, int]:
    ms, _, seq = value.partition("-")
    return int(ms), int(seq or 0)


def trim_acknowledged(client: redis.Redis, stream: str) -> int:
    """Delete the entries of ``stream`` that every consumer group has
    acknowledged (delivered, and no longer pending anywhere). Entries of a
    stream with no group yet are kept. Returns how many were deleted."""
    try:
        groups = client.xinfo_groups(stream)
    except redis.ResponseError:
        return 0  # no such stream yet
    if not groups:
        return 0
    bounds = []
    for group in groups:
        pending = client.xpending(stream, group["name"])
        if pending and pending.get("pending"):
            bounds.append(_stream_id(pending["min"]))  # keep it and everything after
        else:
            ms, seq = _stream_id(group["last-delivered-id"])
            bounds.append((ms, seq + 1))  # everything up to the last delivered is acknowledged
    ms, seq = min(bounds)
    # MINID deletes the entries with smaller ids: the acknowledged ones.
    return int(client.xtrim(stream, minid=f"{ms}-{seq}", approximate=False) or 0)


def housekeeping(client: redis.Redis) -> None:
    """Trim old stream entries and delete old records (run now and then)."""
    for stream in (STREAM_OUT, STREAM_IN):
        trim_acknowledged(client, stream)
    cutoff_ms = int((time.time() - KEEP_STREAM_FOR.total_seconds()) * 1000)
    client.xtrim(STREAM_OUT, minid=f"{cutoff_ms}-0", approximate=True)
    cutoff = utcnow() - KEEP_RECORDS_FOR
    purge_sent_payloads()
    with session_scope() as session:
        session.execute(delete(OutboxEvent).where(OutboxEvent.published_at.is_not(None),
                                                  OutboxEvent.published_at < cutoff))
        session.execute(delete(ProcessedEvent).where(ProcessedEvent.processed_at < cutoff))


def heartbeat(client: redis.Redis) -> None:
    """Note that the worker just finished a round (no data, only the time)."""
    client.set(HEARTBEAT_KEY, utcnow().isoformat(), ex=HEARTBEAT_TTL_SECONDS)


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
    if messages:
        # Handled (or dead-lettered): out of Redis as soon as every group is done.
        trim_acknowledged(client, STREAM_IN)
    return len(messages)


def _already_processed(event_id: str) -> bool:
    with session_scope() as session:
        return session.get(ProcessedEvent, event_id) is not None


def redact_error(why: str) -> str:
    """The error without the values it quotes (input values, DETAIL lines,
    statement parameters): log_safety.sanitize."""
    from dedan_platform import log_safety

    return log_safety.sanitize(why)[:500]


def redacted(fields: Dict[str, str]) -> Dict[str, str]:
    """What a dead letter keeps of an event: no clinical content."""
    out = {k: fields[k] for k in ("id", "type", "source", "occurred_at") if fields.get(k)}
    raw = fields.get("payload") or ""
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        ids = {k: v for k, v in payload.items()
               if k in DEAD_LETTER_PAYLOAD_KEYS and isinstance(v, (str, int)) and len(str(v)) <= 64}
        out["payload_ids"] = json.dumps(ids, sort_keys=True)
        out["payload_keys"] = ",".join(sorted(str(k) for k in payload))[:500]
    else:
        out["payload_note"] = f"not a JSON object ({len(raw)} bytes)"
    return out


def _dead_letter(client: redis.Redis, message_id: str, fields: Dict[str, str], why: str) -> None:
    error = redact_error(why)
    client.xadd(DEAD_LETTER, {**redacted(fields), "stream": STREAM_IN, "group": GROUP, "error": error},
                maxlen=DEAD_LETTER_MAXLEN, approximate=True)
    client.xack(STREAM_IN, GROUP, message_id)
    logger.error("event_dead_lettered type=%s id=%s error=%s", fields.get("type"), fields.get("id"), error)


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
                # The envelope, for handlers that order changes by when they
                # were sent (see event_time).
                session.info["event"] = {"id": event_id, "type": event_type,
                                         "occurred_at": fields.get("occurred_at")}
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
