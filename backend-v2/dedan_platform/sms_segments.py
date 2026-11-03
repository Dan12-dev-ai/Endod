"""SMS lengths: how many segments a text takes, and fitting a reply into a few.

A text in the GSM 7-bit alphabet takes 160 characters in one segment and 153
per segment when it needs more; any other character (Amharic, for one) makes
the whole text UCS-2: 70 characters in one segment, 67 per segment beyond.
Characters of the GSM extension table (``{ } [ ] ~ | ^ \\ €``) count twice.
"""

from __future__ import annotations

from typing import Iterable, List

_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXTENDED = set("^{}\\[~]|€\f")


def is_gsm(text: str) -> bool:
    return all(ch in _GSM_BASIC or ch in _GSM_EXTENDED for ch in text)


def length(text: str) -> int:
    """Septets (GSM) or UTF-16 code units (UCS-2)."""
    if is_gsm(text):
        return sum(2 if ch in _GSM_EXTENDED else 1 for ch in text)
    return len(text.encode("utf-16-le")) // 2


def segments(text: str) -> int:
    if not text:
        return 0
    size = length(text)
    single, multi = (160, 153) if is_gsm(text) else (70, 67)
    return 1 if size <= single else -(-size // multi)


def limit(text: str, max_segments: int) -> int:
    """How many characters fit in ``max_segments`` for a text like ``text``."""
    single, multi = (160, 153) if is_gsm(text) else (70, 67)
    return single if max_segments <= 1 else multi * max_segments


def fit_lines(lines: Iterable[str], max_segments: int, more: str = "") -> str:
    """Join ``lines`` with newlines, keeping as many whole lines as fit in
    ``max_segments``; when some are left out, ``more`` is added (if it fits).
    The first line is always kept (cut with "..." if it alone is too long)."""
    lines = [line for line in lines if line]
    if not lines:
        return ""
    kept: List[str] = []
    for index, line in enumerate(lines):
        candidate = "\n".join(kept + [line])
        last = index == len(lines) - 1
        # Room is kept for ``more`` while lines remain after this one.
        if segments(candidate if last or not more else candidate + "\n" + more) > max_segments:
            break
        kept.append(line)
    if not kept:
        kept = [lines[0]]
    text = "\n".join(kept)
    if len(kept) < len(lines) and more and segments(text + "\n" + more) <= max_segments:
        text = text + "\n" + more
    return cut(text, max_segments)


def cut(text: str, max_segments: int) -> str:
    """``text``, shortened with "..." to fit in ``max_segments``."""
    if segments(text) <= max_segments:
        return text
    room = limit(text, max_segments) - 3
    out = ""
    for ch in text:
        if length(out + ch) > room:
            break
        out += ch
    return out.rstrip() + "..."
