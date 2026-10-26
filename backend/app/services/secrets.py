"""Encryption at rest for integration credentials (API keys / passwords for
Panorama, FortiGate, and standalone PAN-OS firewalls). See
app/models/integration.py — the API layer never returns a decrypted secret,
only `encrypt`/`decrypt` here ever see plaintext, and that only happens
in-process (on save, and when a test-connection call is made).

Fernet (AES-128-CBC + HMAC) rather than anything home-rolled: it's
authenticated (tampered ciphertext fails to decrypt rather than decrypting
to garbage) and it's what `cryptography` — already a transitive dependency
via python-jose[cryptography] — provides out of the box.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretDecryptionError(Exception):
    """Raised when a stored secret can't be decrypted — almost always
    because integrations_encryption_key changed since it was encrypted."""


def _fernet() -> Fernet:
    # settings.integrations_encryption_key can be any string (see config.py's
    # comment) — SHA-256 it down to exactly 32 bytes so it's always a valid
    # Fernet key regardless of what the operator sets it to.
    digest = hashlib.sha256(settings.integrations_encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode("utf-8")
    except InvalidToken as e:
        raise SecretDecryptionError(
            "stored secret could not be decrypted — integrations_encryption_key "
            "may have changed since it was saved",
        ) from e


def last4(plaintext: str) -> str:
    return plaintext[-4:] if len(plaintext) >= 4 else plaintext
