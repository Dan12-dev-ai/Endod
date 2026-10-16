"""
Signup and login for the web portal.

These are the only routes in the platform that are deliberately *unauthenticated*
-- they are how a caller obtains the token every other route requires. There is
no route here that accepts a user id, and none that reads another account.

Two design points are inherited from the platform rather than chosen here:

* **The DEDAN ID is assigned by the server**, never chosen by the patient.
  `models.generate_dedan_user_id` draws it from a cryptographic source and the
  insert is retried on collision, which is what makes it unguessable. Signup
  therefore returns it rather than accepting one -- a client-chosen public id
  would be enumerable, and would also contradict the immutability the rest of
  the platform relies on.
* **Sign-in accepts either the DEDAN ID or the email address**, matching the
  placeholder on the portal's identity field ("DE482731 or user@example.com").
  `identity.resolve_user` owns that resolution so REST and any future support
  tooling agree on what an identifier means.

Token shape matches the realtime websocket path (`realtime.auth.issue_token`),
so one credential in `localStorage` authorises both the REST calls on these
pages and the live-voice socket.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.security import RateLimitMiddleware
from dedan_platform import credentials as cred
from dedan_platform import identity
from dedan_platform.api_profile import current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Signup payload. Deliberately has no DEDAN ID field -- see the module docstring."""

    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    password_confirmation: str = Field(min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=32)
    locale: str = Field(default="en", max_length=8)
    timezone: str = Field(default="UTC", max_length=64)
    country_code: str = Field(default="ET", max_length=2)


class LoginRequest(BaseModel):
    #: DEDAN ID or email address.
    identifier: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)
    new_password_confirmation: str = Field(min_length=1, max_length=200)


def _fail(exc: Exception) -> HTTPException:
    """Map a credential failure onto a status code.

    Every credential error that could help an attacker enumerate accounts returns
    401 with the same body; only `AccountLockedError` is distinguishable (429),
    and that reveals nothing the attacker did not already cause by guessing.
    """
    if isinstance(exc, cred.PasswordPolicyError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, cred.AccountLockedError):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest) -> Dict[str, Any]:
    """Create an account and sign in immediately.

    Registering and logging in as one step avoids a pointless second round trip
    and a second password prompt for a brand-new user. The assigned DEDAN ID is
    returned in the response because it is the one credential-independent
    identifier the patient will ever need for support.
    """
    try:
        email = cred.validate_email(body.email)
        cred.validate_password(body.password, body.password_confirmation)
    except cred.PasswordPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Names are stored as a single display name; the platform's Profile has one
    # field. Joining with a space preserves both without widening the schema.
    display_name = f"{body.first_name.strip()} {body.last_name.strip()}".strip()

    try:
        created = identity.create_user(
            display_name=display_name,
            email=email,
            phone=(body.phone or "").strip() or None,
            locale=body.locale or "en",
            timezone_name=body.timezone or "UTC",
            country_code=(body.country_code or "ET").upper(),
        )
    except identity.EmailInUse as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # A failure here would leave an unreachable half-provisioned account: the
    # row exists but nobody can ever authenticate against it, and the patient
    # holds no credential row to retry with. Report it as a retryable 500
    # instead of pretending the signup worked.
    try:
        cred.set_credential(created["internal_user_id"], body.password)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("register_credential_failed user_id=%s: %s", created["internal_user_id"], exc)
        raise HTTPException(
            status_code=500, detail="Could not finish setting up the account. Please retry."
        ) from exc

    token = cred.issue_token(created["dedan_user_id"], scope="portal")
    logger.info("register_success dedan_user_id=%s", created["dedan_user_id"])
    return {
        "access_token": token,
        "token_type": "DEDAN",
        "expires_in": cred.SESSION_TTL_SECONDS,
        "dedan_user_id": created["dedan_user_id"],
        "profile": identity.get_profile_payload(created["internal_user_id"]),
    }


@router.post("/login")
def login(body: LoginRequest, request: Request) -> Dict[str, Any]:
    """Exchange a DEDAN ID (or email) and password for a session token."""
    try:
        result = cred.authenticate(
            body.identifier, body.password, client=RateLimitMiddleware.client_identity(request)
        )
    except cred.CredentialError as exc:
        raise _fail(exc) from exc

    user = identity.get_user_by_dedan_id(result["dedan_user_id"])
    result["profile"] = identity.get_profile_payload(user.id) if user else None
    return result


@router.get("/session")
def read_session(user_id: str = Depends(current_user_id)) -> Dict[str, Any]:
    """Return the signed-in account.

    Used by the portal on load to decide whether to show the app or the sign-in
    wall, which is why it returns the profile rather than a bare 200.
    """
    return {"profile": identity.get_profile_payload(user_id)}


@router.post("/password")
def change_password(
    body: ChangePasswordRequest,
    user_id: str = Depends(current_user_id),
) -> Dict[str, Any]:
    try:
        cred.change_password(
            user_id,
            body.current_password,
            body.new_password,
            body.new_password_confirmation,
        )
    except cred.CredentialError as exc:
        raise _fail(exc) from exc
    return {"changed": True}
