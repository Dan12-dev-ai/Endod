"""Hospital record files encrypted at rest with the patient's data key (see crypto.py).

A stored copy is::

    header   b"ENDODEF1" | key version (uint32, big-endian) | chunk size (uint32)
    chunks   nonce (12) | AES-256-GCM ciphertext | tag (16)   ... one per chunk

Every chunk holds ``chunk size`` bytes of plaintext except the last, which
holds the rest (an empty file is one empty last chunk). Each chunk has a
fresh random nonce and is bound, as associated data, to the record, the
file, the patient, its index and whether it is the last: chunks cannot be
reordered, dropped, cut off at the end or moved into another file or
account without failing. The SHA-256 the hospital announced stays the hash
of the plaintext; it is checked again on every read, before any byte is sent.

Copies stored before encryption (no header) are read as they are, until
``python -m dedan_platform.tools encrypt-existing`` encrypts them; once
encryption is enforced (``tools enforce``) the caller passes
``allow_plaintext=False`` and such a copy is refused.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import BinaryIO, Callable, Iterator, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ENDODEF1"
HEADER = struct.Struct(">8sII")
CHUNK_SIZE = 64 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
NONCE_BYTES = 12
TAG_BYTES = 16
READ_SIZE = 64 * 1024


class FileCryptoError(RuntimeError):
    """A stored copy does not decrypt, or is not the file the hospital announced."""


class PlaintextRefused(FileCryptoError):
    """A copy without encryption, while encryption is enforced."""


@dataclass(frozen=True)
class FileBinding:
    """What a stored copy belongs to (part of every chunk's associated data)."""

    record_id: str
    file_id: str
    user_id: str


def _chunk_aad(binding: FileBinding, index: int, final: bool) -> bytes:
    return (f"endod-file:v1|{binding.record_id}|{binding.file_id}|{binding.user_id}|{index}|"
            f"{1 if final else 0}").encode("utf-8")


class Encryptor:
    """Writes an encrypted copy to ``out`` from plaintext given in any pieces."""

    def __init__(self, out: BinaryIO, *, key: bytes, version: int, binding: FileBinding,
                 chunk_size: int = CHUNK_SIZE) -> None:
        if not 1 <= chunk_size <= MAX_CHUNK_SIZE:
            raise ValueError("chunk size out of range")
        self._out, self._aes, self._binding, self._chunk = out, AESGCM(key), binding, chunk_size
        self._buffer = bytearray()
        self._index = 0
        self._closed = False
        out.write(HEADER.pack(MAGIC, version, chunk_size))

    def _emit(self, plaintext: bytes, final: bool) -> None:
        nonce = os.urandom(NONCE_BYTES)
        self._out.write(nonce + self._aes.encrypt(nonce, plaintext, _chunk_aad(self._binding, self._index, final)))
        self._index += 1

    def write(self, data: bytes) -> None:
        if self._closed:
            raise ValueError("write after close")
        self._buffer += data
        # Strictly more than a chunk: the last chunk is only known at close().
        while len(self._buffer) > self._chunk:
            self._emit(bytes(self._buffer[:self._chunk]), final=False)
            del self._buffer[:self._chunk]

    def close(self) -> None:
        if not self._closed:
            self._emit(bytes(self._buffer), final=True)
            self._buffer.clear()
            self._closed = True


def read_header(handle: BinaryIO) -> Optional[int]:
    """The key version of an encrypted copy (None: stored before encryption).
    Leaves ``handle`` at the start."""
    handle.seek(0)
    head = handle.read(HEADER.size)
    handle.seek(0)
    if len(head) < HEADER.size or not head.startswith(MAGIC):
        return None
    return HEADER.unpack(head)[1]


def decrypt_chunks(handle: BinaryIO, *, key_for_version: Callable[[int], bytes],
                   binding: FileBinding) -> Iterator[bytes]:
    """The plaintext of an encrypted copy, chunk by chunk (from the start)."""
    handle.seek(0)
    magic, version, chunk_size = HEADER.unpack(handle.read(HEADER.size))
    if magic != MAGIC or not 1 <= chunk_size <= MAX_CHUNK_SIZE:
        raise FileCryptoError("not an encrypted record file")
    aes = AESGCM(key_for_version(version))
    block = NONCE_BYTES + chunk_size + TAG_BYTES
    current = handle.read(block)
    index = 0
    while True:
        if len(current) < NONCE_BYTES + TAG_BYTES:
            raise FileCryptoError(f"chunk {index} is cut short")
        following = handle.read(block) if len(current) == block else b""
        final = not following
        try:
            plaintext = aes.decrypt(current[:NONCE_BYTES], current[NONCE_BYTES:], _chunk_aad(binding, index, final))
        except InvalidTag:
            raise FileCryptoError(f"chunk {index} does not decrypt (wrong key, tampered, cut or moved)") from None
        yield plaintext
        if final:
            return
        current, index = following, index + 1


def plaintext_chunks(handle: BinaryIO, *, key_for_version: Callable[[int], bytes],
                     binding: FileBinding, allow_plaintext: bool = True) -> Iterator[bytes]:
    """The file's plaintext: decrypted, or read as is for a copy from before
    encryption (refused unless ``allow_plaintext``)."""
    if read_header(handle) is None:
        if not allow_plaintext:
            raise PlaintextRefused(f"file {binding.file_id} of record {binding.record_id} is not encrypted, "
                                   "and encryption is enforced")
        handle.seek(0)
        while True:
            piece = handle.read(READ_SIZE)
            if not piece:
                return
            yield piece
    else:
        yield from decrypt_chunks(handle, key_for_version=key_for_version, binding=binding)


def verify(handle: BinaryIO, *, key_for_version: Callable[[int], bytes], binding: FileBinding,
           sha256: str, size: Optional[int] = None, allow_plaintext: bool = True) -> int:
    """Check the whole copy decrypts to the announced SHA-256 (and size).
    Returns the plaintext size."""
    digest, total = hashlib.sha256(), 0
    for piece in plaintext_chunks(handle, key_for_version=key_for_version, binding=binding,
                                  allow_plaintext=allow_plaintext):
        digest.update(piece)
        total += len(piece)
    if digest.hexdigest() != sha256 or (size is not None and total != size):
        raise FileCryptoError("the file is not the one the hospital announced (sha256 or size differs)")
    return total


def open_verified(path, *, key_for_version: Callable[[int], bytes], binding: FileBinding, sha256: str,
                  size: Optional[int] = None, allow_plaintext: bool = True):
    """(plaintext stream, size) of a stored copy, checked in full first: nothing
    is streamed from a copy that fails to decrypt or to match its SHA-256.
    The plaintext is never written to disk."""
    handle = open(path, "rb")
    try:
        total = verify(handle, key_for_version=key_for_version, binding=binding, sha256=sha256, size=size,
                       allow_plaintext=allow_plaintext)
    except BaseException:
        handle.close()
        raise

    def stream() -> Iterator[bytes]:
        try:
            yield from plaintext_chunks(handle, key_for_version=key_for_version, binding=binding,
                                        allow_plaintext=allow_plaintext)
        finally:
            handle.close()

    return stream(), total


def encrypt_file(source: BinaryIO, out: BinaryIO, *, key: bytes, version: int, binding: FileBinding,
                 chunk_size: int = CHUNK_SIZE) -> str:
    """Encrypt all of ``source`` into ``out``; returns the plaintext's SHA-256."""
    digest = hashlib.sha256()
    encryptor = Encryptor(out, key=key, version=version, binding=binding, chunk_size=chunk_size)
    while True:
        piece = source.read(READ_SIZE)
        if not piece:
            break
        digest.update(piece)
        encryptor.write(piece)
    encryptor.close()
    return digest.hexdigest()
