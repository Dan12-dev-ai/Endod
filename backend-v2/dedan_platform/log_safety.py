"""Keep data values out of logs and dead letters.

Database errors quote what they were given: PostgreSQL adds ``DETAIL: Key
(...)=(...) already exists``, SQLAlchemy appends the statement and its
parameters, and validation errors repeat the input (``input_value=...``).
Any of these can be a patient's data. :func:`sanitize` removes them, and
:func:`install` applies it to every log record (message and traceback) made
in the process. The engine also hides statement parameters
(``hide_parameters=True``, db.py).
"""

from __future__ import annotations

import logging
import re

_MARKERS = ("DETAIL:", "[SQL:", "[parameters:", "input_value=", "Key (")
_PATTERNS = (
    # PostgreSQL's detail lines (the offending values).
    (re.compile(r"^[ \t]*DETAIL:.*$", re.M), "DETAIL: <removed>"),
    # Key (column)=(value) wherever it appears.
    (re.compile(r"Key \([^)]*\)=\([^)]*\)"), "Key (<removed>)"),
    # SQLAlchemy's statement and parameter blocks.
    (re.compile(r"\[SQL: .*?\](?=\n|$)", re.S), "[SQL: <removed>]"),
    (re.compile(r"\[parameters: .*?\](?=\n|$)", re.S), "[parameters: <removed>]"),
    # Pydantic (and similar) quoting the input.
    (re.compile(r"input_value=.*?(?=, input_type=|\]|$)", re.S), "input_value=<removed>"),
)


def sanitize(text: str) -> str:
    if not text or not any(marker in text for marker in _MARKERS):
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


_installed = False


def install() -> None:
    """Sanitize every log record made from now on in this process (idempotent)."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()
    formatter = logging.Formatter()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 -- a malformed record: leave it to logging
            return record
        clean = sanitize(message)
        if clean != message:
            record.msg, record.args = clean, ()
        if record.exc_info and record.exc_info[1] is not None:
            # Formatted now, sanitized; handlers use exc_text when it is set.
            record.exc_text = sanitize(formatter.formatException(record.exc_info))
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
