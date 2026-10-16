"""
In-app inbox: what the patient sees on the notifications screen.

Items are written by the events that matter to a patient (an appointment
booked, moved or cancelled; a password change; a phone linked) and read,
marked read or dismissed by the patient. Writing an item never blocks the
action it describes: an inbox failure is logged, not raised.
"""

from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import and_, func, or_, select, update

from dedan_platform.db import ensure_aware, ensure_utc, session_scope
from dedan_platform.models import InboxItem, utcnow

logger = logging.getLogger(__name__)

CATEGORIES = ("appointments", "records", "messages", "security")
MAX_PAGE = 100


class InboxError(RuntimeError):
    pass


def add_item(
    user_id: str,
    category: str,
    kind: str,
    title: str,
    body: Optional[str] = None,
    link_screen: Optional[str] = None,
    link_id: Optional[str] = None,
) -> Optional[str]:
    """Add an item; returns its id, or None if it could not be written."""
    if category not in CATEGORIES:
        raise ValueError(f"Unknown inbox category {category!r}")
    try:
        with session_scope() as session:
            item = InboxItem(
                user_id=user_id, category=category, kind=kind, title=title[:160],
                body=body, link_screen=link_screen, link_id=link_id,
            )
            session.add(item)
            session.flush()
            return item.id
    except Exception:  # noqa: BLE001 - the inbox must never fail the action
        logger.exception("inbox_item_not_written kind=%s", kind)
        return None


def _payload(item: InboxItem) -> Dict[str, Any]:
    return {
        "id": item.id,
        "category": item.category,
        "kind": item.kind,
        "title": item.title,
        "body": item.body,
        "link": {"screen": item.link_screen, "id": item.link_id} if item.link_screen else None,
        "created_at": ensure_aware(item.created_at).isoformat(),
        "read": item.read_at is not None,
    }


def _encode_cursor(item: InboxItem) -> str:
    raw = f"{ensure_aware(item.created_at).isoformat()}|{item.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> Tuple[datetime, str]:
    """(created_at, id) of the last item on the previous page."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        when, item_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(when)
        if created_at.tzinfo is None or not item_id:
            raise ValueError(raw)
        return ensure_utc(created_at), item_id
    except (binascii.Error, UnicodeDecodeError, ValueError, OverflowError) as exc:
        raise InboxError("cursor is not valid; use next_cursor from the previous page.") from exc


def list_items(
    user_id: str,
    category: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    """Newest first, excluding dismissed items, plus unread counts.

    Paged by an opaque keyset cursor over (created_at, id), so items that
    share a timestamp are neither skipped nor repeated across pages.
    """
    after = _decode_cursor(cursor) if cursor else None
    if category is not None and category not in CATEGORIES:
        raise InboxError(f"category must be one of {list(CATEGORIES)}")
    limit = max(1, min(limit, MAX_PAGE))
    visible = (InboxItem.user_id == user_id) & InboxItem.dismissed_at.is_(None)
    with session_scope() as session:
        query = select(InboxItem).where(visible)
        if category:
            query = query.where(InboxItem.category == category)
        if unread_only:
            query = query.where(InboxItem.read_at.is_(None))
        if after is not None:
            created_at, item_id = after
            query = query.where(or_(
                InboxItem.created_at < created_at,
                and_(InboxItem.created_at == created_at, InboxItem.id < item_id),
            ))
        rows = session.scalars(
            query.order_by(InboxItem.created_at.desc(), InboxItem.id.desc()).limit(limit + 1)
        ).all()
        unread = dict(session.execute(
            select(InboxItem.category, func.count(InboxItem.id))
            .where(visible, InboxItem.read_at.is_(None))
            .group_by(InboxItem.category)
        ).all())
        items = [_payload(item) for item in rows[:limit]]
        next_cursor = _encode_cursor(rows[limit - 1]) if len(rows) > limit else None
    return {
        "items": items,
        "next_cursor": next_cursor,
        "unread_count": sum(unread.values()),
        "unread_by_category": {c: unread.get(c, 0) for c in CATEGORIES},
    }


def mark_read(user_id: str, item_id: str) -> bool:
    with session_scope() as session:
        result = session.execute(
            update(InboxItem)
            .where(InboxItem.id == item_id, InboxItem.user_id == user_id, InboxItem.read_at.is_(None))
            .values(read_at=utcnow())
        )
        if result.rowcount:
            return True
        return session.scalar(
            select(InboxItem.id).where(InboxItem.id == item_id, InboxItem.user_id == user_id)
        ) is not None


def mark_all_read(user_id: str, category: Optional[str] = None) -> int:
    if category is not None and category not in CATEGORIES:
        raise InboxError(f"category must be one of {list(CATEGORIES)}")
    query = update(InboxItem).where(
        InboxItem.user_id == user_id, InboxItem.read_at.is_(None), InboxItem.dismissed_at.is_(None)
    )
    if category:
        query = query.where(InboxItem.category == category)
    with session_scope() as session:
        return session.execute(query.values(read_at=utcnow())).rowcount


def dismiss(user_id: str, item_id: str) -> bool:
    now = utcnow()
    with session_scope() as session:
        result = session.execute(
            update(InboxItem)
            .where(InboxItem.id == item_id, InboxItem.user_id == user_id, InboxItem.dismissed_at.is_(None))
            .values(dismissed_at=now, read_at=func.coalesce(InboxItem.read_at, now))
        )
        return bool(result.rowcount)
