"""
Stage 1 API: `/users/me` surface (spec §24).

Authorization model
-------------------
Every route resolves the caller from a **verified credential**, never from a
parameter. There is deliberately no `/users/{id}` route: a route shaped like that
invites a future developer to trust the path value, and the spec requires that a
user can only ever reach their own records. `/users/me` makes that structurally
impossible rather than merely policed by code review.

The realtime signed token (`realtime.auth`) is the credential, reused rather than
reimplemented -- the browser already holds one for the live-voice socket.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from dedan_platform import identity
from app.core.security import normalize_token
from realtime.auth import AUTH_HEADER, AuthError, identity_from_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["profile"])


def current_user_id(
    request: Request,
    authorization: Optional[str] = Header(None, alias=AUTH_HEADER),
) -> str:
    """Resolve the caller's internal id from a verified token.

    Raises 401 rather than falling back to a default: an unauthenticated request
    must never be served a profile, and a silent anonymous fallback is precisely
    how cross-patient access happens.
    """
    # Normalised exactly as the websocket path does, so one credential works for
    # both the live-voice socket and the profile REST API.
    token = normalize_token(authorization or request.headers.get(AUTH_HEADER))
    try:
        subject = identity_from_token(token)
    except AuthError as exc:
        # Covers malformed, forged and expired tokens uniformly: telling the
        # caller which one it was would help an attacker.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        ) from exc
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = identity.get_user_by_dedan_id(subject)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account not found."
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated."
        )
    return user.id


def _error(exc: Exception) -> HTTPException:
    """Map a domain error onto a client-safe response."""
    if isinstance(exc, identity.InvalidDedanId):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, identity.UserNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, identity.EmailInUse):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/me")
def read_profile(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """Identity + profile + preferences + consent. No health data."""
    return identity.get_profile_payload(user_id)


@router.patch("/me")
def patch_profile(
    changes: Dict[str, Any],
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        return identity.update_profile(
            user_id, changes, correlation_id=request.headers.get("X-Correlation-ID")
        )
    except identity.IdentityError as exc:
        raise _error(exc) from exc


@router.get("/me/preferences")
def read_preferences(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return identity.get_profile_payload(user_id)["preferences"]


@router.patch("/me/preferences")
def patch_preferences(
    changes: Dict[str, Any],
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        payload = identity.update_preferences(
            user_id, changes, correlation_id=request.headers.get("X-Correlation-ID")
        )
    except identity.IdentityError as exc:
        raise _error(exc) from exc
    return payload["preferences"]


@router.get("/me/health-profile")
def read_health_profile(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """Health profile.

    Requires treatment consent. This is the enforcement point for the spec's rule
    that sensitive health data must not be exposed through ordinary profile
    endpoints -- an unauthorised read is 403, not an empty object, because an
    empty object would be indistinguishable from "no data recorded" and hide the
    refusal from the user.
    """
    payload = identity.get_profile_payload(user_id)
    if not payload["consent"]["treatment_processing"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consent to store health information is required.",
        )
    return identity.get_health_profile_payload(user_id)


@router.patch("/me/health-profile")
def patch_health_profile(
    changes: Dict[str, Any],
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    payload = identity.get_profile_payload(user_id)
    if not payload["consent"]["treatment_processing"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Consent to store health information is required.",
        )
    try:
        return identity.update_health_profile(
            user_id, changes, correlation_id=request.headers.get("X-Correlation-ID")
        )
    except identity.IdentityError as exc:
        raise _error(exc) from exc


@router.get("/me/consent")
def read_consent(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    return identity.get_profile_payload(user_id)["consent"]


@router.patch("/me/consent")
def patch_consent(
    changes: Dict[str, Any],
    request: Request,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        return identity.update_consent(
            user_id, changes, correlation_id=request.headers.get("X-Correlation-ID")
        )
    except identity.IdentityError as exc:
        raise _error(exc) from exc
