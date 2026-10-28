"""Application-level encryption of health data: envelope encryption.

Keys
----
* The **master key** (KEK, 32 random bytes) is read from the file named by
  ``PLATFORM_MASTER_KEY_FILE``. deploy/docker-compose.yml mounts it read-only
  into ``backend``, ``internal-api`` and ``events-worker`` only. It is never
  in the database, the repository or a backup of either, so a copy of the
  database (or of the record files) alone reveals no health data. Production
  refuses to start without it (:func:`require_master_key`). Elsewhere, with
  the variable unset, a fixed development key is used, with a warning: data
  written that way is not protected (tests, local runs, CI).
* Each patient has a **data key** (DEK, 32 random bytes) in ``user_keys``,
  wrapped with AES-256-GCM under the master key, its user id and version as
  associated data. New data uses the patient's highest active version; older
  versions stay readable until ``rotate-key`` re-encrypts what they hold.
  Unwrapped keys are cached in this process for :data:`CACHE_SECONDS`, and
  are never logged or put in an error message.

Values
------
``enc:v1:<key_version>:<base64(nonce || ciphertext || tag)>``: AES-256-GCM
with a fresh random 96-bit nonce per value (well inside GCM's limit for the
few thousand values one patient's key encrypts), and associated data binding
the table, column, row id and user id. A ciphertext copied into another row,
column or patient's account fails to decrypt instead of showing there.

Nothing here logs or raises with a plaintext, a ciphertext or a key: errors
name the table, column, row and user only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import os
import threading
import time
from typing import Dict, Optional, Tuple, Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

KEY_FILE_ENV = "PLATFORM_MASTER_KEY_FILE"
PREFIX = "enc:v1:"
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
#: How long an unwrapped data key stays in this process's memory.
CACHE_SECONDS = 300.0
CACHE_MAX = 4096

#: Used only outside production when no key file is configured. Published in
#: this file, so it protects nothing; it keeps development and tests working.
_DEVELOPMENT_KEY = hashlib.sha256(b"endod development master key - not secret, never for real data").digest()

Bind = Union[Session, Connection]


class CryptoError(RuntimeError):
    """Encryption is not possible (no master key, no data key)."""


class MasterKeyError(CryptoError):
    """The master key file is missing, unreadable or malformed."""


class DecryptionError(CryptoError):
    """A value (or a wrapped key) does not decrypt: wrong key, tampered, or
    moved from another row, column or user."""


# --- the master key ------------------------------------------------------------------------

def _environment() -> str:
    env = os.getenv("ENVIRONMENT")
    if env is None:
        try:
            from app.core.config import get_settings

            env = get_settings().ENVIRONMENT
        except Exception:  # noqa: BLE001 -- settings unavailable: not production
            env = "development"
    return (env or "development").strip().lower()


def _key_path() -> str:
    """The key file: process environment first, then settings (``.env``)."""
    path = os.getenv(KEY_FILE_ENV)
    if path is None:
        try:
            from app.core.config import get_settings

            path = get_settings().PLATFORM_MASTER_KEY_FILE
        except Exception:  # noqa: BLE001 -- settings unavailable: no key file
            path = None
    return (path or "").strip()


_master_lock = threading.Lock()
#: (key file path, key) of the key loaded last.
_master: Optional[Tuple[str, bytes]] = None


def _read_key_file(path: str) -> bytes:
    try:
        with open(path, "rb") as handle:
            data = handle.read(KEY_BYTES + 1)
    except OSError as exc:
        raise MasterKeyError(
            f"{KEY_FILE_ENV}={path} cannot be read ({type(exc).__name__}). Mount the key file read-only "
            "and make it readable by the service's user (deploy/README.md, 'Encryption of health data')."
        ) from None
    if len(data) != KEY_BYTES:
        raise MasterKeyError(
            f"{KEY_FILE_ENV}={path} must hold exactly {KEY_BYTES} random bytes "
            "(make it with: openssl rand -out master.key 32)."
        )
    return data


def master_key() -> bytes:
    """The master key (KEK). Raises MasterKeyError in production without one."""
    global _master
    path = _key_path()
    if not path:
        if _environment() == "production":
            raise MasterKeyError(
                f"{KEY_FILE_ENV} must be set in production: it names the master key file that "
                "encrypts health data (deploy/README.md, 'Encryption of health data')."
            )
        if _master is None or _master[0] != "":
            logger.warning("master_key_development_fallback: %s is not set, so health data is encrypted "
                           "with the published development key (never use this for real data)", KEY_FILE_ENV)
            _master = ("", _DEVELOPMENT_KEY)
        return _DEVELOPMENT_KEY
    current = _master
    if current is not None and current[0] == path:
        return current[1]
    with _master_lock:
        if _master is None or _master[0] != path:
            _master = (path, _read_key_file(path))
        return _master[1]


def key_id(kek: Optional[bytes] = None) -> str:
    """A short fingerprint of the master key, safe to log (to tell keys apart)."""
    return hashlib.sha256(b"endod-master-key-id:" + (kek or master_key())).hexdigest()[:12]


def require_master_key() -> str:
    """Startup check for the services that hold the key: raises if production
    has none (or any configured key file is unusable). Returns the key's id."""
    kek = master_key()
    ident = key_id(kek)
    if kek == _DEVELOPMENT_KEY:
        logger.warning("master_key_is_the_development_key id=%s", ident)
    else:
        logger.info("master_key_loaded id=%s", ident)
    return ident


def reset() -> None:
    """Forget the loaded master key and every cached data key (tests; after a key change)."""
    global _master
    with _master_lock:
        _master = None
    clear_cache()


# --- data keys --------------------------------------------------------------------------------

_cache_lock = threading.Lock()
#: (master key id, user id, version) -> (expires at, data key)
_cache: Dict[Tuple[str, str, int], Tuple[float, bytes]] = {}


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_get(kid: str, user_id: str, version: int) -> Optional[bytes]:
    with _cache_lock:
        hit = _cache.get((kid, user_id, version))
        if hit is None:
            return None
        if hit[0] < time.monotonic():
            del _cache[(kid, user_id, version)]
            return None
        return hit[1]


def _cache_put(kid: str, user_id: str, version: int, key: bytes) -> None:
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            now = time.monotonic()
            for stale in [k for k, (expires, _) in _cache.items() if expires < now]:
                del _cache[stale]
            if len(_cache) >= CACHE_MAX:
                _cache.clear()
        _cache[(kid, user_id, version)] = (time.monotonic() + CACHE_SECONDS, key)


def _evict(kid: str, user_id: str, version: int) -> None:
    with _cache_lock:
        _cache.pop((kid, user_id, version), None)


def _wrap_aad(user_id: str, version: int) -> bytes:
    return f"endod:user-key:v1|{user_id}|{version}".encode("utf-8")


def wrap_key(dek: bytes, user_id: str, version: int, kek: Optional[bytes] = None) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(kek or master_key()).encrypt(nonce, dek, _wrap_aad(user_id, version))
    return base64.b64encode(nonce + sealed).decode("ascii")


def unwrap_key(wrapped: str, user_id: str, version: int, kek: Optional[bytes] = None) -> bytes:
    try:
        raw = base64.b64decode(wrapped, validate=True)
        dek = AESGCM(kek or master_key()).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], _wrap_aad(user_id, version))
    except (InvalidTag, ValueError, binascii.Error):
        raise DecryptionError(
            f"the data key of user {user_id} (version {version}) does not open with this master key"
        ) from None
    if len(dek) != KEY_BYTES:
        raise DecryptionError(f"the data key of user {user_id} (version {version}) is malformed")
    return dek


def _connection(bind: Bind) -> Connection:
    # Session.connection() never autoflushes, so this is safe inside a flush.
    return bind.connection() if isinstance(bind, Session) else bind


def _keys_table():
    from dedan_platform.models import UserKey

    return UserKey.__table__


def data_key(bind: Bind, user_id: str, version: int) -> bytes:
    """The user's data key of this version (cached briefly)."""
    kek = master_key()
    kid = key_id(kek)
    cached = _cache_get(kid, user_id, version)
    if cached is not None:
        return cached
    table = _keys_table()
    wrapped = _connection(bind).execute(select(table.c.wrapped_key).where(
        table.c.user_id == user_id, table.c.version == version)).scalar()
    if wrapped is None:
        raise DecryptionError(f"user {user_id} has no data key version {version}")
    dek = unwrap_key(wrapped, user_id, version, kek)
    _cache_put(kid, user_id, version, dek)
    return dek


def _insert_key(conn: Connection, user_id: str, version: Optional[int] = None) -> int:
    """Add a data key (the next version unless given). A concurrent insert of
    the same version wins quietly: the caller reads whichever was stored."""
    from dedan_platform.models import utcnow

    table = _keys_table()
    if version is None:
        latest = conn.execute(select(func.max(table.c.version)).where(table.c.user_id == user_id)).scalar()
        version = int(latest or 0) + 1
    values = {"user_id": user_id, "version": version, "created_at": utcnow(), "active": True,
              "wrapped_key": wrap_key(os.urandom(KEY_BYTES), user_id, version)}
    dialect = conn.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:  # pragma: no cover - only PostgreSQL and SQLite are supported
        conn.execute(table.insert().values(**values))
        return version
    conn.execute(dialect_insert(table).values(**values).on_conflict_do_nothing())
    return version


def active_key(bind: Bind, user_id: str, create: bool = True) -> Tuple[int, bytes]:
    """(version, data key) to encrypt the user's new data with; made on first use.

    Read from the database each time (not cached), so after a rotation every
    process encrypts under the new version at once.
    """
    if not user_id:
        raise CryptoError("no user to encrypt for")
    conn = _connection(bind)
    table = _keys_table()
    kek = master_key()
    for _ in range(3):
        row = conn.execute(select(table.c.version, table.c.wrapped_key).where(
            table.c.user_id == user_id, table.c.active.is_(True)).order_by(table.c.version.desc()).limit(1)).first()
        if row is not None:
            version, wrapped = int(row[0]), row[1]
            dek = unwrap_key(wrapped, user_id, version, kek)
            _cache_put(key_id(kek), user_id, version, dek)
            return version, dek
        if not create:
            break
        _insert_key(conn, user_id)
    raise CryptoError(f"user {user_id} has no active data key")


def rotate_user_key(bind: Bind, user_id: str) -> int:
    """Make a new active data key for the user (older ones become inactive,
    still readable). Returns the new version."""
    conn = _connection(bind)
    table = _keys_table()
    if conn.dialect.name == "postgresql":
        # One rotation at a time per user.
        conn.execute(select(table.c.version).where(table.c.user_id == user_id).with_for_update())
    version = _insert_key(conn, user_id)
    conn.execute(table.update().where(table.c.user_id == user_id, table.c.version != version).values(active=False))
    return version


# --- values -----------------------------------------------------------------------------------

def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def value_aad(table: str, column: str, row_id: object, user_id: object) -> bytes:
    return f"endod:v1|{table}|{column}|{row_id}|{user_id}".encode("utf-8")


def _parse(value: str) -> Tuple[int, bytes]:
    try:
        version_text, encoded = value[len(PREFIX):].split(":", 1)
        version = int(version_text)
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise DecryptionError("malformed ciphertext") from None
    if version < 1 or len(raw) < NONCE_BYTES + TAG_BYTES:
        raise DecryptionError("malformed ciphertext")
    return version, raw


def key_version(value: str) -> Optional[int]:
    """The data key version a ciphertext was made with (None for plaintext)."""
    if not is_encrypted(value):
        return None
    return _parse(value)[0]


def encrypt_value(plaintext: str, *, key: bytes, version: int, aad: bytes) -> str:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return f"{PREFIX}{version}:{base64.b64encode(nonce + sealed).decode('ascii')}"


def decrypt_value(value: str, *, key: bytes, aad: bytes) -> str:
    _version, raw = _parse(value)
    try:
        return AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], aad).decode("utf-8")
    except (InvalidTag, UnicodeDecodeError):
        raise DecryptionError("the value does not decrypt") from None


def encrypt_field(bind: Bind, *, table: str, column: str, row_id: str, user_id: str, plaintext: str) -> str:
    version, key = active_key(bind, user_id)
    return encrypt_value(plaintext, key=key, version=version, aad=value_aad(table, column, row_id, user_id))


def decrypt_field(bind: Bind, *, table: str, column: str, row_id: object, user_id: object, value: str) -> str:
    """The plaintext of a stored value; plaintext (legacy) is returned as is."""
    if not is_encrypted(value):
        return value
    where = f"{table}.{column} of row {row_id}"
    if not user_id:
        raise DecryptionError(f"{where} has no owner to decrypt it with")
    version, _raw = _parse(value)
    aad = value_aad(table, column, row_id, user_id)
    kek = master_key()
    for attempt in (1, 2):
        key = data_key(bind, str(user_id), version)
        try:
            return decrypt_value(value, key=key, aad=aad)
        except DecryptionError:
            if attempt == 2:
                break
            # A cached key may be one a rolled-back transaction made: read it again.
            _evict(key_id(kek), str(user_id), version)
    raise DecryptionError(f"{where} does not decrypt (wrong key, tampered, or moved from another row or user)")
