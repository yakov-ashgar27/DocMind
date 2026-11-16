"""Envelope encryption.

master key (env)  --wraps-->  per-user data key (DEK)  --encrypts-->  text fields, OAuth tokens
master key (env)  --wraps-->  per-file key              --encrypts-->  document bytes

Deleting a wrapped key renders the ciphertext unrecoverable (crypto-shredding), which is how
"secure deletion" is guaranteed even on SSDs / backups where overwrite is unreliable.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE = 12
_VERSION = b"\x01"


def new_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt(key: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
    nonce = secrets.token_bytes(_NONCE)
    return _VERSION + nonce + AESGCM(key).encrypt(nonce, plaintext, aad or None)


def decrypt(key: bytes, blob: bytes, aad: bytes = b"") -> bytes:
    if not blob or blob[:1] != _VERSION:
        raise ValueError("unknown ciphertext version")
    nonce, ct = blob[1:1 + _NONCE], blob[1 + _NONCE:]
    return AESGCM(key).decrypt(nonce, ct, aad or None)


def wrap_key(master: bytes, key: bytes, context: str) -> bytes:
    return encrypt(master, key, aad=context.encode())


def unwrap_key(master: bytes, wrapped: bytes, context: str) -> bytes:
    return decrypt(master, wrapped, aad=context.encode())


def encrypt_text(dek: bytes, text: str | None, context: str) -> bytes | None:
    if text is None:
        return None
    return encrypt(dek, text.encode("utf-8"), aad=context.encode())


def decrypt_text(dek: bytes, blob: bytes | None, context: str) -> str:
    if not blob:
        return ""
    return decrypt(dek, blob, aad=context.encode()).decode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hmac_hex(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


# ---- password hashing (scrypt, stdlib) -------------------------------------------------
_SCRYPT = dict(n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                              maxmem=64 * 1024 * 1024, dklen=len(bytes.fromhex(dk)))
        return hmac.compare_digest(calc, bytes.fromhex(dk))
    except Exception:
        return False


# ---- encrypted blob store -------------------------------------------------------------
class BlobStore:
    """Local encrypted object store. Swap for S3/GCS with server-side + client-side encryption."""

    def __init__(self, root: Path, master: bytes):
        self.root = Path(root)
        self.master = master

    def _path(self, storage_key: str) -> Path:
        if not storage_key.isalnum():
            raise ValueError("bad storage key")
        return self.root / storage_key[:2] / storage_key

    def put(self, data: bytes) -> tuple[str, bytes]:
        storage_key = secrets.token_hex(20)
        file_key = new_key()
        p = self._path(storage_key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(encrypt(file_key, data, aad=storage_key.encode()))
        os.chmod(p, 0o600)
        return storage_key, wrap_key(self.master, file_key, f"file:{storage_key}")

    def get(self, storage_key: str, wrapped_file_key: bytes) -> bytes:
        file_key = unwrap_key(self.master, wrapped_file_key, f"file:{storage_key}")
        return decrypt(file_key, self._path(storage_key).read_bytes(), aad=storage_key.encode())

    def delete(self, storage_key: str) -> None:
        p = self._path(storage_key)
        if p.exists():
            # Best-effort overwrite; the real guarantee is that the wrapped key is deleted too.
            size = p.stat().st_size
            with open(p, "r+b") as fh:
                fh.write(secrets.token_bytes(size))
                fh.flush()
                os.fsync(fh.fileno())
            p.unlink()
