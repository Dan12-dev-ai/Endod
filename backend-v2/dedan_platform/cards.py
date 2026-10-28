"""
The Digital Health Card: a signature that proves a card was issued by Endod.

The card's QR code links to ``/card/<DEDAN ID>?s=<signature>``. The signature
is an HMAC of the DEDAN ID under a server secret, so:

* a card with a made-up or altered ID does not verify: only the server can
  produce a signature, and each ID has exactly one;
* the signature is checked *before* any account lookup, so the verify
  endpoint cannot be used to find out which DEDAN IDs exist;
* the QR code carries no health data, only the ID and the signature.

The DEDAN ID itself is unique (database constraint, see
``identity._allocate_user``), so every card is unique too.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from typing import Any, Dict, Optional

from dedan_platform import identity
from realtime.auth import signing_secret

#: Bumping this invalidates every printed card at once (e.g. after a leak of
#: the secret); cards are re-issued from the profile on the next visit.
CARD_VERSION = "v1"
#: 16 bytes = 128 bits: far beyond guessing, short enough for a small QR code.
_SIGNATURE_BYTES = 16
_SIGNATURE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class CardError(Exception):
    """The card could not be signed or verified."""


def _secret() -> bytes:
    # A secret of its own, so rotating the session-signing secret (to end
    # every session) does not also void every printed card. Until it is set,
    # the session-signing secret is used.
    secret = os.getenv("CARD_SIGNING_SECRET") or signing_secret()
    if not secret:
        raise CardError("No signing secret configured.")
    return secret.encode("utf-8")


def card_signature(dedan_user_id: str) -> str:
    message = f"endod-card:{CARD_VERSION}:{dedan_user_id}".encode("ascii")
    digest = hmac.new(_secret(), message, hashlib.sha256).digest()[:_SIGNATURE_BYTES]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def card_for_user(internal_user_id: str) -> Dict[str, Any]:
    """What the signed-in patient's card needs: their ID and its signature."""
    user = identity.get_user_by_internal_id(internal_user_id)
    if user is None:
        raise identity.UserNotFound("Account not found.")
    return {
        "dedan_user_id": user.dedan_user_id,
        "signature": card_signature(user.dedan_user_id),
        "issued_at": user.created_at.isoformat(),
    }


def verify_card(dedan_user_id: str, signature: str) -> Optional[Dict[str, Any]]:
    """The card holder as a scanner may see them, or None if the card is not genuine.

    Shows only what is printed on the card already (name, ID, issue date),
    so scanning reveals nothing the card itself does not.
    """
    try:
        dedan_user_id = identity.validate_dedan_user_id(dedan_user_id)
    except identity.InvalidDedanId:
        return None
    if not signature or not _SIGNATURE_RE.match(signature):
        return None
    if not hmac.compare_digest(card_signature(dedan_user_id).encode("ascii"), signature.encode("ascii")):
        return None
    user = identity.get_user_by_dedan_id(dedan_user_id)
    if user is None or not user.is_active or user.suspended_at is not None:
        return None
    profile = user.profile
    names = [getattr(profile, part, None) for part in ("first_name", "middle_name", "last_name")]
    full_name = " ".join(n for n in names if n) or getattr(profile, "display_name", None)
    return {
        "dedan_user_id": user.dedan_user_id,
        "full_name": full_name,
        "issued_at": user.created_at.isoformat(),
    }
