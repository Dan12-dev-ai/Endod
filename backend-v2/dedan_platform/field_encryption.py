"""Transparent encryption of the models' ``__encrypted__`` columns (see crypto.py).

Every model listing ``__encrypted__`` (column names) and having ``id`` and
``user_id`` gets:

* **on flush** (``before_flush``): each new or changed value of those columns
  is encrypted with the owner's active data key, bound to the table, column,
  row id and user id; after the flush the object holds the plaintext again,
  so the code that wrote it keeps reading what it wrote;
* **on load and refresh**: stored ciphertext is decrypted into the object.
  Plaintext from before encryption (``encrypt-existing`` not run yet) is
  returned as it is.

So application code reads and writes plain values through the ORM and never
handles keys. What this cannot cover, by design: Core statements over those
columns (``select(Model.title)``, ``update(Model).values(title=...)``,
``Model.title.contains(...)``, ``order_by(Model.title)``) see or write the
stored form. The application uses whole entities for them (tests check the
stored form is never plaintext).

A row moved to another patient (``user_id`` changed) has every encrypted
column re-encrypted for the new owner in the same flush.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from dedan_platform import crypto
from dedan_platform.db import Base, new_uuid

#: session.info key: [(obj, column, plaintext, ciphertext)] for values this
#: session's flushes encrypted, until the transaction ends. After the flush the
#: object reads the plaintext again; if the transaction (or a savepoint) rolls
#: back, values the failed flush left as ciphertext are put back to plaintext,
#: so the next flush encrypts them again, under a key that exists.
_WRITTEN = "endod_encrypted_writes"


def encrypted_models() -> List[type]:
    """Every mapped class with encrypted columns."""
    return sorted((m.class_ for m in Base.registry.mappers if getattr(m.class_, "__encrypted__", None)),
                  key=lambda cls: cls.__table__.name)


def table_of(obj_or_cls: Any) -> str:
    cls = obj_or_cls if isinstance(obj_or_cls, type) else type(obj_or_cls)
    return cls.__table__.name


def _modified(state, key: str) -> bool:
    history = state.attrs[key].history
    if not history.added:
        return False
    return not history.deleted or history.added[0] != history.deleted[0]


def _owner(session: Session, obj: Any) -> str:
    """The user whose key encrypts this row (filled in where the model can derive it)."""
    user_id = getattr(obj, "user_id", None)
    if not user_id:
        user = obj.__dict__.get("user")  # a health profile added through User.health_profile
        if user is not None:
            if user.id is None:
                user.id = new_uuid()
            user_id = user.id
    if not user_id and getattr(obj, "rx_id", None):
        from dedan_platform.models import Prescription

        prescription = session.get(Prescription, obj.rx_id)
        user_id = prescription.user_id if prescription is not None else None
    if not user_id:
        raise crypto.CryptoError(f"{table_of(obj)} row {getattr(obj, 'id', None)} has no owner to encrypt it for")
    if getattr(obj, "user_id", None) != user_id:
        obj.user_id = user_id
    return user_id


def _row_id(obj: Any) -> str:
    if getattr(obj, "id", None) is None:
        obj.id = new_uuid()
    return obj.id


def _pending_values(session: Session) -> List[Tuple[Any, str, str]]:
    work = []
    for obj in list(session.new) + list(session.dirty):
        columns: Iterable[str] = getattr(type(obj), "__encrypted__", ())
        if not columns:
            continue
        state = sa_inspect(obj)
        is_new = obj in session.new
        moved = not is_new and _modified(state, "user_id")
        for column in columns:
            if column not in state.dict:
                continue  # never loaded, so unchanged in the database
            value = state.dict[column]
            if not isinstance(value, str):
                continue
            if is_new or moved or _modified(state, column):
                work.append((obj, column, value))
    return work


@event.listens_for(Session, "before_flush")
def _encrypt_before_flush(session: Session, _flush_context, _instances) -> None:
    work = _pending_values(session)
    if not work:
        return
    keys: Dict[str, Tuple[int, bytes]] = {}
    written = session.info.setdefault(_WRITTEN, [])
    with session.no_autoflush:
        for obj, column, plaintext in work:
            row_id = _row_id(obj)
            user_id = _owner(session, obj)
            if user_id not in keys:
                keys[user_id] = crypto.active_key(session, user_id)
            version, key = keys[user_id]
            ciphertext = crypto.encrypt_value(plaintext, key=key, version=version,
                                              aad=crypto.value_aad(table_of(obj), column, row_id, user_id))
            setattr(obj, column, ciphertext)
            written.append((obj, column, plaintext, ciphertext))


@event.listens_for(Session, "after_flush_postexec")
def _restore_after_flush(session: Session, _flush_context) -> None:
    for obj, column, plaintext, ciphertext in session.info.get(_WRITTEN, []):
        if obj.__dict__.get(column) == ciphertext:
            # As if loaded: the object reads plaintext, and it is not "changed".
            set_committed_value(obj, column, plaintext)


@event.listens_for(Session, "after_soft_rollback")
def _undo_after_rollback(session: Session, _previous_transaction) -> None:
    """A flush failed, or a transaction or savepoint rolled back: whatever it
    encrypted may name a data key that rolled back with it. Values still
    holding that ciphertext become plaintext again (still to be written), and
    keys made in this session are dropped from the cache."""
    for obj, column, plaintext, ciphertext in session.info.pop(_WRITTEN, []):
        if obj.__dict__.get(column) == ciphertext:
            setattr(obj, column, plaintext)
    for user_id, version in session.info.pop(crypto.CREATED_KEYS, set()):
        crypto.evict(user_id, version)


@event.listens_for(Session, "after_commit")
def _forget_after_commit(session: Session) -> None:
    session.info.pop(_WRITTEN, None)
    session.info.pop(crypto.CREATED_KEYS, None)


def decrypt_object(obj: Any, session: Session, only: Optional[Iterable[str]] = None) -> None:
    columns = getattr(type(obj), "__encrypted__", ())
    wanted = set(only) if only is not None else None
    for column in columns:
        if wanted is not None and column not in wanted:
            continue
        value = obj.__dict__.get(column)
        if not isinstance(value, str):
            continue
        # Plaintext too: returned as it is, or refused once encryption is enforced.
        plaintext = crypto.decrypt_field(session, table=table_of(obj), column=column, row_id=obj.__dict__.get("id"),
                                         user_id=obj.__dict__.get("user_id"), value=value)
        if plaintext is not value:
            set_committed_value(obj, column, plaintext)


def _on_load(target: Any, context) -> None:
    if getattr(type(target), "__encrypted__", None):
        decrypt_object(target, context.session)


def _on_refresh(target: Any, context, attrs) -> None:
    if getattr(type(target), "__encrypted__", None):
        decrypt_object(target, context.session, attrs)


event.listen(Base, "load", _on_load, propagate=True)
event.listen(Base, "refresh", _on_refresh, propagate=True)
