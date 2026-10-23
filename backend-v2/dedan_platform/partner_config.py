"""Settings for partner hospitals, payments, video and events.

Read from the process environment on every call (as the notification
settings are), so a deployment changes them in ``deploy/.env`` and tests set
them with ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os
from typing import List, Optional


def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _int(name: str, default: int) -> int:
    try:
        return int(_get(name) or default)
    except ValueError:
        return default


def environment() -> str:
    return (_get("ENVIRONMENT", "development") or "development").lower()


# --- events (Redis Streams; Sentinel in production) ---

def redis_url() -> Optional[str]:
    return _get("REDIS_URL")


def redis_sentinels() -> List[str]:
    return [part.strip() for part in (_get("REDIS_SENTINELS") or "").split(",") if part.strip()]


def redis_sentinel_master() -> str:
    return _get("REDIS_SENTINEL_MASTER", "endod") or "endod"


def redis_password() -> Optional[str]:
    return _get("REDIS_PASSWORD")


def redis_sentinel_password() -> Optional[str]:
    return _get("REDIS_SENTINEL_PASSWORD")


def redis_min_replicas() -> int:
    """Replicas that must hold an event before it counts as sent (0: single Redis)."""
    return max(0, _int("REDIS_MIN_REPLICAS", 0))


# --- the hospital service's API and patient records (docs/history-events.md) ---

def hospital_api_url() -> Optional[str]:
    """The hospital service's private API (over endod-bus), e.g. http://endod-hospital-api:8000."""
    value = _get("HOSPITAL_API_URL")
    return value.rstrip("/") if value else None


def platform_admin_key() -> Optional[str]:
    """Shared with the hospital service: sent to its /platform API and required
    on this API's /internal endpoints. Unset: both are refused."""
    return _get("PLATFORM_ADMIN_KEY")


def pharmacy_api_key() -> Optional[str]:
    """Shared with the pharmacy site's server: required as ``X-Pharmacy-Key``
    on internal-api's /pharmacy endpoints (docs/pharmacy.md). Unset: refused."""
    return _get("PHARMACY_API_KEY")


def rx_signing_key() -> Optional[str]:
    """Signs prescription QR tokens (docs/pharmacy.md section 1). Separate from
    the card key. Unset: no QR is issued and every token is refused (the
    6-digit code still works)."""
    return _get("RX_SIGNING_KEY")


def record_files_dir() -> str:
    """Where the platform keeps its copies of hospital record files (a volume)."""
    return _get("RECORD_FILES_DIR", "/data/records") or "/data/records"


# --- the care directory ---

def demo_directory() -> bool:
    """The built-in sample facilities: on in development and tests, off in production
    (where every listed hospital is a real partner)."""
    value = _get("CARE_DEMO_DIRECTORY")
    if value is None:
        return environment() != "production"
    return value.lower() in ("1", "true", "yes", "on")


# --- payments ---

def service_fee_flat() -> int:
    """Endod's fee per payment, in santim (default 5 birr)."""
    return max(0, _int("SERVICE_FEE_FLAT_SANTIM", 500))


def service_fee_percent_hundredths() -> int:
    """Endod's fee as a share of the price, in hundredths of a percent (150 = 1.5%)."""
    return max(0, _int("SERVICE_FEE_PERCENT_BP", 0))


def chapa_secret_key() -> Optional[str]:
    return _get("CHAPA_SECRET_KEY")


def chapa_webhook_secret() -> Optional[str]:
    return _get("CHAPA_WEBHOOK_SECRET")


def chapa_base_url() -> str:
    return (_get("CHAPA_BASE_URL", "https://api.chapa.co/v1") or "").rstrip("/")


def public_app_url() -> str:
    """Where patients use Endod (for Chapa's return and callback links)."""
    return (_get("PUBLIC_APP_URL", "http://localhost:3000") or "").rstrip("/")


#: Deposit limits, in santim.
DEPOSIT_MIN = 1_000  # 10 birr
DEPOSIT_MAX = 10_000_000  # 100,000 birr


# --- video visits ---

def jitsi_domain() -> str:
    return _get("JITSI_DOMAIN", "meet.endod-health.com") or "meet.endod-health.com"


def jitsi_app_id() -> str:
    return _get("JITSI_APP_ID", "endod") or "endod"


def jitsi_app_secret() -> Optional[str]:
    return _get("JITSI_APP_SECRET")


def jitsi_jwt_sub() -> str:
    return _get("JITSI_JWT_SUB", "meet.jitsi") or "meet.jitsi"
