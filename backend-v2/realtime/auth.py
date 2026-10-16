"""
Signed session tokens for the portal REST API and the live-voice socket.

Format
------
``v1.<payload>.<signature>`` where ``payload`` is base64url(JSON) and
``signature`` is base64url(HMAC-SHA256(secret, "v1." + payload)). The payload
carries ``sub`` (the public DEDAN ID), ``iat`` and ``exp`` (unix seconds) and
``scope``.

Design rules
------------
* **No hard-coded fallback secret.** The signer uses ``REALTIME_TOKEN_SECRET``,
  then ``ADMIN_API_KEY``. With neither set it refuses to mint or verify, so a
  deployment that forgot the secret fails loudly instead of signing with a
  value published in this repository.
* **Uniform failure.** Malformed, forged and expired tokens all raise
  ``AuthError``; callers translate that to a single 401 so the response does not
  tell an attacker which check failed.
* **Expiry is mandatory.** Every token carries ``exp``; there is no
  non-expiring token.
* ``iat`` is recorded so a password change can invalidate tokens issued before
  it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional

#: Header the browser sends the token in. The value is the raw token; a
#: ``Bearer`` or ``DEDAN`` scheme prefix is also accepted (see
#: ``app.core.security.normalize_token``).
AUTH_HEADER = "Authorization"

TOKEN_VERSION = "v1"

#: Lifetime used when the caller does not pass ``expires_in``. Matches the
#: realtime session TTL; portal logins pass their own, longer lifetime.
DEFAULT_TTL_SECONDS = int(os.getenv("REALTIME_SESSION_TTL", "1800"))

#: Clock skew tolerated when checking ``iat`` so a token minted by a replica
#: whose clock runs slightly ahead is not rejected.
_CLOCK_SKEW_SECONDS = 30


class AuthError(Exception):
    """A token could not be issued or verified."""


def _secret() -> bytes:
    secret = os.getenv("REALTIME_TOKEN_SECRET") or os.getenv("ADMIN_API_KEY") or ""
    if not secret:
        raise AuthError("No token signing secret configured.")
    return secret.encode("utf-8")


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(signing_input: str) -> str:
    digest = hmac.new(_secret(), signing_input.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def issue_token(
    subject: str,
    expires_in: Optional[int] = None,
    scope: str = "realtime",
) -> str:
    """Mint a signed token for ``subject`` (a DEDAN ID)."""
    if not subject:
        raise AuthError("A token needs a subject.")
    ttl = DEFAULT_TTL_SECONDS if expires_in is None else int(expires_in)
    if ttl <= 0:
        raise AuthError("Token lifetime must be positive.")

    now = int(time.time())
    payload = {"sub": subject, "iat": now, "exp": now + ttl, "scope": scope}
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{TOKEN_VERSION}.{encoded}"
    return f"{signing_input}.{_sign(signing_input)}"


def decode_token(token: Optional[str]) -> Dict[str, Any]:
    """Verify ``token`` and return its payload. Raises ``AuthError``."""
    if not token or not isinstance(token, str):
        raise AuthError("Missing token.")

    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_VERSION:
        raise AuthError("Malformed token.")

    signing_input = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_sign(signing_input), parts[2]):
        raise AuthError("Invalid token signature.")

    try:
        payload = json.loads(_b64decode(parts[1]))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AuthError("Malformed token.") from exc
    if not isinstance(payload, dict):
        raise AuthError("Malformed token.")

    now = time.time()
    exp = payload.get("exp")
    iat = payload.get("iat")
    if not isinstance(exp, (int, float)) or now >= exp:
        raise AuthError("Token expired.")
    if not isinstance(iat, (int, float)) or iat > now + _CLOCK_SKEW_SECONDS:
        raise AuthError("Malformed token.")
    if not isinstance(payload.get("sub"), str) or not payload["sub"]:
        raise AuthError("Malformed token.")
    return payload


def identity_from_token(token: Optional[str]) -> str:
    """Return the DEDAN ID a valid token was issued to. Raises ``AuthError``."""
    return decode_token(token)["sub"]
