"""
`/users/me/inbox`: the patient's in-app notifications.

Same ownership model as the rest of `/users/me`: every query is filtered by
the authenticated account, and another patient's item id answers 404.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from dedan_platform import inbox
from dedan_platform.api_profile import current_user_id

router = APIRouter(prefix="/users/me/inbox", tags=["inbox"])


@router.get("")
def list_inbox(
    category: Optional[str] = Query(default=None, description="appointments | records | messages | security"),
    unread_only: bool = False,
    limit: int = Query(default=50, ge=1, le=inbox.MAX_PAGE),
    cursor: Optional[str] = Query(default=None, max_length=200, description="next_cursor from the previous page"),
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        return inbox.list_items(user_id, category, unread_only, limit, cursor)
    except inbox.InboxError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/read-all")
def read_all(
    category: Optional[str] = Query(default=None),
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        return {"marked_read": inbox.mark_all_read(user_id, category)}
    except inbox.InboxError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{item_id}/read")
def read_item(item_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    if not inbox.mark_read(user_id, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    return {"id": item_id, "read": True}


@router.delete("/{item_id}")
def dismiss_item(item_id: str, user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    if not inbox.dismiss(user_id, item_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found.")
    return {"id": item_id, "dismissed": True}
