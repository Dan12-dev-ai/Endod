"""Application-level encryption of health data: envelope encryption.

Keys
----
* The **master key** (KEK, 32 random bytes) is read from the file named by
  ``PLATFORM_MASTER_KEY_FILE``. deploy/docker-compose.yml mounts it read-only
  into ``backend``, ``internal-api`` and ``events-worker`` only. It is never
  in the database, the repository or a backup of either, so a copy of the
  database (or of the record files) alone reveals no health data. The
  services refuse to start without a usable key file (:func:`require_master_key`)
  unless ``ENVIRONMENT`` is explicitly ``development`` or ``test``: then, with
  no key file, a fixed development key is used, with a warning (data written
  that way is not protected). Staging, production, an unknown or an unset
  environment all need the key file.
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

Master key check. On first install the database stores a check value of the
master key (an HMAC of a constant under it) and its fingerprint
(``platform_settings``: ``master_key_check``, ``master_key_id``). The services
verify the mounted key against it at start (:func:`verify_master_key`) and
before any new data key is wrapped, and refuse a different key: a wrong key
mounted once would otherwise wrap new patients' keys that no longer open
once the right key is back.

Keys are never overwritten. Only rotate-key (marking older versions
inactive) and purge-old-keys (deleting unused old versions) change
``user_keys``; any other UPDATE of it beyond ``active``, or any DELETE, is
refused in-process (:func:`key_admin`). The platform uses one database role
for all its services, so this is a code guarantee, not a database grant
(deploy/README.md).

Plaintext from before encryption is read as it is until
``python -m dedan_platform.tools enforce`` records that every value has been
encrypted (``platform_settings``: ``encryption_enforced``). From then on a
stored value without a valid ``enc:v1:`` envelope is refused (:func:`enforced`).

Residual risk, accepted: someone with write access to the database can put
back an *older* ciphertext of the same row and column (it carries the same
associated data, so it decrypts). A per-row write counter in the associated
data would not stop them either: they would put back the old counter with
the old value. Detecting that needs a record of versions kept outside the
database's reach, which this does not attempt; database write access is
guarded instead (deploy/README.md).

First keys are made inside the caller's transaction with
``INSERT ... ON CONFLICT DO NOTHING`` and read back: this needs READ COMMITTED
(the PostgreSQL default, which db.py keeps; nothing here sets REPEATABLE READ
or SERIALIZABLE). Under a stricter level a lost race ends in a CryptoError
and the transaction is retried by its caller; it never yields a wrong key.

Nothing here logs or raises with a plaintext, a ciphertext or a key: errors
name the table, column, row and user only.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import contextvars
import hashlib
import hmac
import logging
import os
import threading
import time
from typing import Dict, Iterator, Optional, Set, Tuple, Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, Update

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

#: The only environments that may run without a key file (on the development key).
KEYLESS_ENVIRONMENTS = ("development", "test")


def _environment() -> str:
    """ENVIRONMENT as set explicitly (process environment, or .env through the
    settings); "" when it is not set at all. The settings' own default
    ("development") does not count: unset is not development."""
    env = os.getenv("ENVIRONMENT")
    if env is None:
        try:
            from app.core.config import get_settings

            settings = get_settings()
            env = settings.ENVIRONMENT if "ENVIRONMENT" in settings.model_fields_set else ""
        except Exception:  # noqa: BLE001 -- settings unavailable: not set
            env = ""
    return (env or "").strip().lower()


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
        env = _environment()
        if env not in KEYLESS_ENVIRONMENTS:
            raise MasterKeyError(
                f"{KEY_FILE_ENV} must be set (ENVIRONMENT={env or 'unset'}): it names the master key file "
                "that encrypts health data. Only ENVIRONMENT=development or test may run without it "
                "(deploy/README.md, 'Encryption of health data')."
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


def require_master_key(service: str = "") -> str:
    """Startup check for the services that hold the key: raises without a
    usable key (see :func:`master_key`). Logs the key's fingerprint, at
    WARNING so it shows whatever the logging setup, for the three services to
    be compared: they must all print the same id. Returns the id."""
    kek = master_key()
    ident = key_id(kek)
    if kek == _DEVELOPMENT_KEY:
        logger.warning("master_key_in_use service=%s id=%s (the published DEVELOPMENT key: never for real data)",
                       service or "-", ident)
    else:
        logger.warning("master_key_in_use service=%s id=%s", service or "-", ident)
    return ident


def reset() -> None:
    """Forget the loaded master key, every cached data key, the verified
    master keys and the cached enforcement state (tests; after a key change)."""
    global _master, _enforced_until, _enforced
    with _master_lock:
        _master = None
    _enforced, _enforced_until = False, 0.0
    _verified.clear()
    clear_cache()


# --- the master key, checked against the database ------------------------------------------------

MASTER_KEY_CHECK = "master_key_check"
MASTER_KEY_ID = "master_key_id"
#: (master key id, database url) already verified in this process.
_verified: Set[Tuple[str, str]] = set()


def _check_value(kek: bytes) -> str:
    return hmac.new(kek, b"endod master key check v1", hashlib.sha256).hexdigest()


def _settings_insert(conn: Connection, key: str, value: str) -> None:
    from dedan_platform.models import PlatformSetting, utcnow

    table = PlatformSetting.__table__
    values = {"key": key, "value": value, "updated_at": utcnow()}
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    conn.execute(dialect_insert(table).values(**values).on_conflict_do_nothing())


def _verify(conn: Connection, kek: bytes) -> str:
    from dedan_platform.models import PlatformSetting

    kid = key_id(kek)
    marker = (kid, str(conn.engine.url))
    if marker in _verified:
        return kid
    table = PlatformSetting.__table__
    stored = dict(conn.execute(select(table.c.key, table.c.value).where(
        table.c.key.in_([MASTER_KEY_CHECK, MASTER_KEY_ID]))).all())
    if MASTER_KEY_CHECK not in stored:
        # First install (or a database from before the check): any data key
        # already there must open with this key before it is recorded.
        keys = _keys_table()
        row = conn.execute(select(keys.c.user_id, keys.c.version, keys.c.wrapped_key).limit(1)).first()
        if row is not None:
            try:
                unwrap_key(row[2], row[0], int(row[1]), kek)
            except DecryptionError:
                raise MasterKeyError(
                    f"the mounted master key (id {kid}) does not open the data keys already in the database; "
                    "mount the master key file they were made with (deploy/README.md)."
                ) from None
        _settings_insert(conn, MASTER_KEY_CHECK, _check_value(kek))
        _settings_insert(conn, MASTER_KEY_ID, kid)
        stored = dict(conn.execute(select(table.c.key, table.c.value).where(
            table.c.key.in_([MASTER_KEY_CHECK, MASTER_KEY_ID]))).all())
    if not hmac.compare_digest(stored.get(MASTER_KEY_CHECK, ""), _check_value(kek)):
        raise MasterKeyError(
            f"the mounted master key (id {kid}) is not the one this database's data keys are wrapped with "
            f"(id {stored.get(MASTER_KEY_ID, '?')}); refusing to start rather than make keys no one can open. "
            "Mount the right master key file (deploy/README.md, 'The OFFLINE backup of the master key')."
        )
    _verified.add(marker)
    return kid


def verify_master_key(bind: Optional[Bind] = None) -> str:
    """Check the mounted master key against the database (recording it on
    first install). Raises MasterKeyError if it is another key. Returns its id."""
    kek = master_key()
    if bind is not None:
        return _verify(_connection(bind), kek)
    from dedan_platform.db import get_engine
    from dedan_platform.models import PlatformSetting, UserKey

    engine = get_engine()
    PlatformSetting.__table__.create(engine, checkfirst=True)
    UserKey.__table__.create(engine, checkfirst=True)
    with engine.begin() as conn:
        return _verify(conn, kek)


# --- user_keys is never overwritten --------------------------------------------------------------

_key_admin: contextvars.ContextVar[bool] = contextvars.ContextVar("endod_key_admin", default=False)


@contextlib.contextmanager
def key_admin() -> Iterator[None]:
    """Allow changing ``user_keys`` beyond ``active`` (purge-old-keys deletes
    unused old versions in it; tests age keys in it). Nothing else uses it."""
    token = _key_admin.set(True)
    try:
        yield
    finally:
        _key_admin.reset(token)


class KeyTableGuardError(CryptoError):
    """A statement would overwrite or delete data keys outside key administration."""


def _updated_columns(statement, multiparams, params) -> Set[str]:
    names = {getattr(k, "key", k) for k in (getattr(statement, "_values", None) or {})}
    for batch in list(multiparams or ()) + ([params] if params else []):
        rows = batch if isinstance(batch, (list, tuple)) else [batch]
        for row in rows:
            if isinstance(row, dict):
                names.update(str(k) for k in row)
    return names


@event.listens_for(Engine, "before_execute")
def _guard_user_keys(conn, statement, multiparams, params, execution_options) -> None:
    if not isinstance(statement, (Update, Delete)):
        return
    table = getattr(statement, "table", None)
    if getattr(table, "name", None) != "user_keys" or _key_admin.get():
        return
    if isinstance(statement, Delete):
        raise KeyTableGuardError("data keys are deleted only by purge-old-keys")
    if _updated_columns(statement, multiparams, params) - {"active"}:
        raise KeyTableGuardError("data keys are never overwritten (only their 'active' flag changes)")


# --- enforcement ---------------------------------------------------------------------------------

ENFORCED_SETTING = "encryption_enforced"
#: The enforcement setting is read again this often.
ENFORCED_RECHECK_SECONDS = 30.0
_enforced = False
_enforced_until = 0.0


def enforced(bind: Optional[Bind] = None) -> bool:
    """Whether plaintext is refused (``tools enforce`` was run). Read again
    every :data:`ENFORCED_RECHECK_SECONDS`, either way: switched off for a
    rollback (decrypt-existing), it reaches running processes too."""
    global _enforced, _enforced_until
    now = time.monotonic()
    if now < _enforced_until:
        return _enforced
    from dedan_platform.models import PlatformSetting

    table = PlatformSetting.__table__
    query = select(table.c.value).where(table.c.key == ENFORCED_SETTING)
    try:
        if bind is not None:
            value = _connection(bind).execute(query).scalar()
        else:
            from dedan_platform.db import get_engine

            with get_engine().connect() as conn:
                value = conn.execute(query).scalar()
    except Exception:  # noqa: BLE001 -- e.g. the table not made yet: not enforced
        return False
    _enforced = value == "yes"
    _enforced_until = now + ENFORCED_RECHECK_SECONDS
    return _enforced


def plaintext_refused(where: str) -> DecryptionError:
    """The error (logged) for a plaintext value met while enforced. Never the value."""
    logger.error("plaintext_refused %s: encryption is enforced and the stored value is not encrypted", where)
    return DecryptionError(f"{where} is not encrypted, and encryption is enforced")


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


def evict(user_id: str, version: Optional[int] = None) -> None:
    """Forget the cached data keys of a user (one version, or all): the next
    use reads them from the database again."""
    with _cache_lock:
        for cached in [k for k in _cache if k[1] == user_id and (version is None or k[2] == version)]:
            del _cache[cached]


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


def data_key(bind: Bind, user_id: str, version: int, fresh: bool = False) -> bytes:
    """The user's data key of this version (cached briefly; ``fresh`` reads
    it from the database whatever the cache holds)."""
    kek = master_key()
    kid = key_id(kek)
    cached = None if fresh else _cache_get(kid, user_id, version)
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
    kek = master_key()
    # Never wrap a new key under a master key the database does not know.
    _verify(conn, kek)
    values = {"user_id": user_id, "version": version, "created_at": utcnow(), "active": True,
              "wrapped_key": wrap_key(os.urandom(KEY_BYTES), user_id, version, kek)}
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


#: session.info key: (user id, version) of the keys made in this session's
#: transaction, forgotten from the cache if it rolls back (field_encryption.py).
CREATED_KEYS = "endod_created_keys"


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
        made = _insert_key(conn, user_id)
        if isinstance(bind, Session):
            bind.info.setdefault(CREATED_KEYS, set()).add((user_id, made))
    raise CryptoError(f"user {user_id} has no active data key")


def lock_user_keys(bind: Bind, user_id: str) -> None:
    """Lock the user's key rows until the transaction ends (PostgreSQL; SQLite
    has one writer at a time anyway). Taken by rotate_user_key, by the purge
    of old keys and by a file download's storing step, so none of them sees
    the others half done."""
    conn = _connection(bind)
    if conn.dialect.name == "postgresql":
        table = _keys_table()
        conn.execute(select(table.c.version).where(table.c.user_id == user_id).with_for_update())


def rotate_user_key(bind: Bind, user_id: str) -> int:
    """Make a new active data key for the user (older ones become inactive,
    still readable). Returns the new version."""
    conn = _connection(bind)
    table = _keys_table()
    lock_user_keys(conn, user_id)  # one rotation at a time per user
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


def parses(value: object) -> bool:
    """Whether a value is a well-formed envelope (a plaintext that merely
    starts with ``enc:v1:`` is not)."""
    if not is_encrypted(value):
        return False
    try:
        _parse(value)
    except DecryptionError:
        return False
    return True


def decrypt_field(bind: Bind, *, table: str, column: str, row_id: object, user_id: object, value: str) -> str:
    """The plaintext of a stored value. A value from before encryption (no
    well-formed envelope) is returned as it is, until encryption is enforced;
    then it is refused."""
    where = f"{table}.{column} of row {row_id}"
    if not parses(value):
        if enforced(bind):
            raise plaintext_refused(where)
        return value
    if not user_id:
        raise DecryptionError(f"{where} has no owner to decrypt it with")
    version, _raw = _parse(value)
    aad = value_aad(table, column, row_id, user_id)
    for fresh in (False, True):
        # A cached key may be one a rolled-back transaction made: on failure,
        # read it from the database once more.
        key = data_key(bind, str(user_id), version, fresh=fresh)
        try:
            return decrypt_value(value, key=key, aad=aad)
        except DecryptionError:
            continue
    raise DecryptionError(f"{where} does not decrypt (wrong key, tampered, or moved from another row or user)")
