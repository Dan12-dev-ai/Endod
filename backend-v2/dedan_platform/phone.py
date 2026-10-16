"""
Ethiopian mobile numbers.

Accepted forms: "+251 911 234 567", "251911234567", "0911234567",
"911234567", with spaces, dashes, dots or brackets. Both Ethio Telecom (9...)
and Safaricom Ethiopia (7...) mobile ranges are accepted.

Stored and compared in E.164 ("+251911234567"); SMS Ethiopia takes the same
number without the plus ("251911234567").
"""

from __future__ import annotations

import re
from typing import Optional

_MOBILE = re.compile(r"^(?:251|0)?([79]\d{8})$")


def normalise_ethiopian_mobile(value: Optional[str]) -> Optional[str]:
    """E.164 form of an Ethiopian mobile number, or ``None`` if it is not one."""
    if not value or not isinstance(value, str):
        return None
    digits = re.sub(r"[\s().-]", "", value.strip())
    if digits.startswith("+"):
        digits = digits[1:]
        if not digits.startswith("251"):
            return None
    if not digits.isdigit():
        return None
    match = _MOBILE.match(digits)
    return f"+251{match.group(1)}" if match else None


def to_msisdn(e164: str) -> str:
    """The number as SMS Ethiopia expects it: digits only, no plus."""
    return e164.lstrip("+")


def mask(e164: str) -> str:
    """Safe for logs: "+251*******67"."""
    return f"{e164[:4]}{'*' * max(0, len(e164) - 6)}{e164[-2:]}" if e164 else "***"
