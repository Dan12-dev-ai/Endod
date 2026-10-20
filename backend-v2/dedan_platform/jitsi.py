"""Video visits on Endod's own Jitsi server.

The server only lets in people holding a token signed with the shared app
secret (Jitsi's JWT authentication), so a meeting link alone is not enough to
join: the doctor gets a token from the hospital service, the patient from this
platform, each only for their own visit and only around its time. Both sign
with the same app secret (JITSI_APP_SECRET), the one the Jitsi server checks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict

from dedan_platform import partner_config as config

#: A visit can be joined from this long before it starts...
OPENS_BEFORE = timedelta(minutes=30)
#: ...until this long after it was due to end.
CLOSES_AFTER = timedelta(hours=1)
#: A token lasts this long (the call can go on after it expires).
TOKEN_TTL_SECONDS = 2 * 60 * 60


class JitsiError(RuntimeError):
    """Video is not configured, or the visit cannot be joined now."""


def new_room() -> str:
    """An unguessable room name."""
    return "endod-" + secrets.token_hex(12)


def join_window(starts_at: datetime, duration_minutes: int) -> tuple[datetime, datetime]:
    return starts_at - OPENS_BEFORE, starts_at + timedelta(minutes=duration_minutes) + CLOSES_AFTER


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def token(room: str, display_name: str, moderator: bool, now: float | None = None,
          expires_at: float | None = None) -> str:
    secret = config.jitsi_app_secret()
    if not secret:
        raise JitsiError("Video visits are not configured.")
    issued = int(now if now is not None else time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims: Dict[str, Any] = {
        "aud": "jitsi",
        "iss": config.jitsi_app_id(),
        "sub": config.jitsi_jwt_sub(),
        "room": room,
        "nbf": issued - 60,
        # Valid to join until the visit's window closes (and at least 10 minutes).
        "exp": int(max(expires_at, issued + 600)) if expires_at else issued + TOKEN_TTL_SECONDS,
        # The doctor runs the call. Prosody's token_affiliation reads
        # "affiliation"; "moderator" is read by other setups.
        "context": {"user": {"name": display_name[:80], "moderator": moderator,
                             "affiliation": "owner" if moderator else "member"}},
        "moderator": moderator,
    }
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{_b64(json.dumps(claims, separators=(',', ':'), ensure_ascii=False).encode())}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def join_details(room: str, display_name: str, moderator: bool, closes_at: datetime | None = None) -> Dict[str, Any]:
    domain = config.jitsi_domain()
    return {
        "domain": domain,
        "room": room,
        "jwt": token(room, display_name, moderator, expires_at=closes_at.timestamp() if closes_at else None),
        "url": f"https://{domain}/{room}",
    }
