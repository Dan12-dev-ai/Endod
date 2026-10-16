"""
In-app inbox: what the patient sees on the notifications screen.

Items are written by the events that matter to a patient (an appointment
booked, moved or cancelled; a password change; a phone linked) and read,
marked read or dismissed by the patient. Writing an item never blocks the
action it describes: an inbox failure is logged, not raised.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import func, select, update

from dedan_platform.db import ensure_aware, session_scope
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


def list_items(
    user_id: str,
    category: Optional[str] = None,
    unread_only: bool = False,
    limit: int = 50,
    before: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Newest first, excluding dismissed items, plus unread counts."""
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
        if before is not None:
            query = query.where(InboxItem.created_at < before)
        rows = session.scalars(
            query.order_by(InboxItem.created_at.desc(), InboxItem.id.desc()).limit(limit + 1)
        ).all()
        unread = dict(session.execute(
            select(InboxItem.category, func.count(InboxItem.id))
            .where(visible, InboxItem.read_at.is_(None))
            .group_by(InboxItem.category)
        ).all())
        items = [_payload(item) for item in rows[:limit]]
    return {
        "items": items,
        "next_before": items[-1]["created_at"] if len(rows) > limit else None,
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
