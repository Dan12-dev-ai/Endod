"""Endod's service fee: what the patient pays Endod on each paid hospital
service (docs/service-fee.md).

The CEO's rule: Endod covers the cost of SMS and earns a service fee charged
to the PATIENT (never the hospital) on every payment they make for a hospital
service: a booking, a lab test, imaging, a procedure, any other charge. The
hospital's bill is 200 ETB; the patient pays 225 ETB (25 ETB fee). A second
charge, the same again.

The single source of truth is this platform's ``platform_settings`` table:

* ``fees.enabled``: ``true`` / ``false`` (default true);
* ``fees.flat_santim``: the flat part, in santim (default 2500 = 25 birr);
* ``fees.percent_bp``: an optional share of the subtotal, in basis points
  (hundredths of a percent: 150 = 1.5%; default 0);
* ``fees.version``: raised on every change, so the hospital service keeps
  only the newest settings it was sent.

Until the super admin first saves them, the environment gives the defaults
(``SERVICE_FEE_FLAT_SANTIM``, ``SERVICE_FEE_PERCENT_BP``,
``SERVICE_FEE_ENABLED``), then the values above. The super admin changes them
through ``PUT /internal/admin/fees`` (api_admin.py): validated, and every
change is kept in ``fee_setting_changes`` (who, why, before and after).

The rule, the same here and in the hospital service (app/fees.py there):

* fee = flat + round_half_up(subtotal x percent_bp / 10000), in santim;
* no fee on a subtotal of 0 (a free visit), nor while ``enabled`` is false;
* one fee per payment: a booking, or a charge (however many items it has).

The hospital service is told the settings over the bus (``fees.updated``,
on every change and every ``BROADCAST_EVERY`` from the events worker) and
keeps the last ones it received, so it still quotes the right fee while this
platform is down.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from dedan_platform.db import ensure_aware, session_scope
from dedan_platform.models import FeeSettingChange, PlatformSetting, utcnow

logger = logging.getLogger(__name__)

PREFIX = "fees."
ENABLED, FLAT, PERCENT, VERSION, UPDATED_BY = (
    "fees.enabled", "fees.flat_santim", "fees.percent_bp", "fees.version", "fees.updated_by")

#: The defaults when neither the database nor the environment says otherwise.
DEFAULT_FLAT_SANTIM = 2500  # 25 birr
DEFAULT_PERCENT_BP = 0

#: Limits a change is checked against.
MAX_FLAT_SANTIM = 100_000  # 1,000 birr
MAX_PERCENT_BP = 2_000  # 20%

#: How often the events worker re-sends the settings to the hospital service
#: (so one that missed an event, or a new database, catches up).
BROADCAST_EVERY = 6 * 3600

_TRUE = {"1", "true", "yes", "on"}


class FeeSettingsError(ValueError):
    """A change the rules refuse (out of range)."""


@dataclass(frozen=True)
class FeeSettings:
    enabled: bool
    flat_santim: int
    percent_bp: int
    version: int
    updated_at: Optional[str]
    updated_by: Optional[str]

    def fee_for(self, subtotal: int) -> int:
        return fee_for(subtotal, self)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _defaults() -> Dict[str, Any]:
    enabled = (os.getenv("SERVICE_FEE_ENABLED") or "true").strip().lower() in _TRUE
    return {"enabled": enabled,
            "flat_santim": max(0, _env_int("SERVICE_FEE_FLAT_SANTIM", DEFAULT_FLAT_SANTIM)),
            "percent_bp": max(0, _env_int("SERVICE_FEE_PERCENT_BP", DEFAULT_PERCENT_BP))}


def _rows(session: Session) -> Dict[str, PlatformSetting]:
    return {row.key: row for row in session.scalars(
        select(PlatformSetting).where(PlatformSetting.key.like(f"{PREFIX}%")))}


def _from_rows(rows: Dict[str, PlatformSetting]) -> FeeSettings:
    values = _defaults()

    def number(key: str, fallback: int) -> int:
        row = rows.get(key)
        try:
            return int(row.value) if row is not None else fallback
        except ValueError:
            logger.warning("fee_setting_not_a_number key=%s", key)
            return fallback

    if ENABLED in rows:
        values["enabled"] = rows[ENABLED].value.strip().lower() in _TRUE
    values["flat_santim"] = max(0, number(FLAT, values["flat_santim"]))
    values["percent_bp"] = max(0, number(PERCENT, values["percent_bp"]))
    version_row = rows.get(VERSION)
    by = rows.get(UPDATED_BY)
    return FeeSettings(enabled=values["enabled"], flat_santim=values["flat_santim"],
                       percent_bp=values["percent_bp"], version=number(VERSION, 0),
                       updated_at=ensure_aware(version_row.updated_at).isoformat() if version_row else None,
                       updated_by=by.value if by is not None else None)


def read(session: Session) -> FeeSettings:
    return _from_rows(_rows(session))


def current() -> FeeSettings:
    """The settings now (from the database; the environment's defaults while
    the table is missing, e.g. a fresh database before create_all)."""
    try:
        with session_scope() as session:
            return read(session)
    except Exception as exc:  # noqa: BLE001 -- the fee must never break a quote
        logger.warning("fee_settings_unavailable error=%s", type(exc).__name__)
        values = _defaults()
        return FeeSettings(values["enabled"], values["flat_santim"], values["percent_bp"], 0, None, None)


def fee_for(subtotal: int, settings: Optional[FeeSettings] = None) -> int:
    """Endod's fee, in santim, on one payment of ``subtotal`` santim."""
    settings = settings or current()
    if not settings.enabled or subtotal <= 0:
        return 0
    share = (subtotal * settings.percent_bp + 5_000) // 10_000  # rounded half up, to the santim
    return settings.flat_santim + share


def validate(enabled: bool, flat_santim: int, percent_bp: int) -> None:
    if not isinstance(flat_santim, int) or not 0 <= flat_santim <= MAX_FLAT_SANTIM:
        raise FeeSettingsError(f"The flat fee must be 0 to {MAX_FLAT_SANTIM // 100} birr.")
    if not isinstance(percent_bp, int) or not 0 <= percent_bp <= MAX_PERCENT_BP:
        raise FeeSettingsError(f"The percentage must be 0 to {MAX_PERCENT_BP / 100:g}%.")
    if enabled and flat_santim == 0 and percent_bp == 0:
        raise FeeSettingsError("An enabled fee needs a flat amount or a percentage (or switch the fee off).")


def _put(session: Session, rows: Dict[str, PlatformSetting], key: str, value: str, now: datetime) -> None:
    row = rows.get(key)
    if row is None:
        session.add(PlatformSetting(key=key, value=value, updated_at=now))
    else:
        row.value, row.updated_at = value, now


def broadcast_payload(settings: FeeSettings) -> Dict[str, Any]:
    """What ``fees.updated`` says (the hospital service keeps the newest version)."""
    return {"version": settings.version, "enabled": settings.enabled, "flat_santim": settings.flat_santim,
            "percent_bp": settings.percent_bp, "currency": "ETB", "updated_at": settings.updated_at}


def change(enabled: bool, flat_santim: int, percent_bp: int, actor_email: str, reason: str) -> Dict[str, Any]:
    """Save new settings (validated), record who changed them and why, and
    tell the hospital service (``fees.updated``) in the same transaction."""
    from dedan_platform import eventbus

    validate(enabled, flat_santim, percent_bp)
    with session_scope() as session:
        rows = _rows(session)
        # Serialise concurrent changes on the version row (Postgres: a row lock).
        version_row = session.scalar(select(PlatformSetting).where(PlatformSetting.key == VERSION)
                                     .with_for_update())
        before = _from_rows(rows)
        now = utcnow()
        _put(session, rows, ENABLED, "true" if enabled else "false", now)
        _put(session, rows, FLAT, str(flat_santim), now)
        _put(session, rows, PERCENT, str(percent_bp), now)
        _put(session, rows, UPDATED_BY, actor_email, now)
        new_version = (int(version_row.value) if version_row is not None and version_row.value.isdigit()
                       else before.version) + 1
        if version_row is None:
            session.add(PlatformSetting(key=VERSION, value=str(new_version), updated_at=now))
        else:
            version_row.value, version_row.updated_at = str(new_version), now
        session.flush()
        after = FeeSettings(enabled, flat_santim, percent_bp, new_version, ensure_aware(now).isoformat(),
                            actor_email)
        session.add(FeeSettingChange(
            changed_at=now, actor_email=actor_email, reason=reason,
            before=json.dumps({k: v for k, v in before.as_dict().items() if k in ("enabled", "flat_santim",
                                                                                   "percent_bp")}),
            after=json.dumps({"enabled": enabled, "flat_santim": flat_santim, "percent_bp": percent_bp}),
            version=new_version))
        eventbus.emit(session, "fees.updated", broadcast_payload(after))
    logger.info("fee_settings_changed version=%s by=%s enabled=%s flat=%s bp=%s", new_version, actor_email,
                enabled, flat_santim, percent_bp)
    return view()


def history(limit: int = 20) -> List[Dict[str, Any]]:
    with session_scope() as session:
        rows = session.scalars(select(FeeSettingChange).order_by(FeeSettingChange.changed_at.desc(),
                                                                 FeeSettingChange.id.desc()).limit(limit))
        return [{"version": r.version, "changed_at": ensure_aware(r.changed_at).isoformat(),
                 "actor_email": r.actor_email, "reason": r.reason, "before": json.loads(r.before),
                 "after": json.loads(r.after)} for r in rows]


#: The example the super admin shows: what a 200 ETB bill becomes.
EXAMPLE_SUBTOTAL = 20_000


def view() -> Dict[str, Any]:
    """The settings, an example, the limits and the latest changes (the admin API's answer)."""
    settings = current()
    fee = fee_for(EXAMPLE_SUBTOTAL, settings)
    return {**settings.as_dict(), "currency": "ETB",
            "example": {"subtotal": EXAMPLE_SUBTOTAL, "service_fee": fee, "total": EXAMPLE_SUBTOTAL + fee},
            "limits": {"max_flat_santim": MAX_FLAT_SANTIM, "max_percent_bp": MAX_PERCENT_BP},
            "history": history()}


def broadcast() -> None:
    """Queue ``fees.updated`` with the settings now (the events worker, now and then)."""
    from dedan_platform import eventbus

    settings = current()
    with session_scope() as session:
        eventbus.emit(session, "fees.updated", broadcast_payload(settings))
