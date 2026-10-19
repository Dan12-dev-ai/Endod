"""
The Digital Health Card.

* ``GET /users/me/card``: the signed-in patient's DEDAN ID and card signature,
  from which the portal draws the card and its QR code.
* ``GET /cards/{dedan_user_id}/verify?s=``: public. What a hospital desk sees
  when it scans a card: whether it is genuine, and the holder's name and ID.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from dedan_platform import cards, identity
from dedan_platform.api_profile import current_user_id

router = APIRouter(tags=["cards"])

_NOT_GENUINE = "This card could not be verified."


@router.get("/users/me/card")
def my_card(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    try:
        return cards.card_for_user(user_id)
    except identity.UserNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.") from exc


@router.get("/cards/{dedan_user_id}/verify")
def verify_card(dedan_user_id: str, s: str = Query(default="", max_length=64)) -> Dict[str, Any]:
    holder = cards.verify_card(dedan_user_id, s)
    if holder is None:
        # One answer for a forged signature, an unknown ID and a closed
        # account, so the endpoint tells nothing about which IDs exist.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_GENUINE)
    return {"valid": True, **holder}
