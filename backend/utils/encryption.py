from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def get_fernet_key(secret_key: str) -> bytes:
    """Derive a Fernet-compatible key from an arbitrary secret string."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(value: str, secret_key: str) -> str:
    """Encrypt a plaintext value and return a base64-encoded ciphertext string."""
    key = get_fernet_key(secret_key)
    f = Fernet(key)
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str, secret_key: str) -> str:
    """Decrypt a base64-encoded ciphertext string and return the plaintext."""
    key = get_fernet_key(secret_key)
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()
