from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

# Cache derived keys to avoid repeated PBKDF2 (300ms per call)
_key_cache: dict[tuple[str, bytes], bytes] = {}

_PBKDF2_ITERATIONS = 600_000


def _derive_key_pbkdf2(secret_key: str, salt: bytes) -> bytes:
    """Derive a Fernet-compatible key using PBKDF2-HMAC-SHA256."""
    cache_key = (secret_key, salt)
    if cache_key in _key_cache:
        return _key_cache[cache_key]
    dk = hashlib.pbkdf2_hmac("sha256", secret_key.encode(), salt, _PBKDF2_ITERATIONS)
    key = base64.urlsafe_b64encode(dk)
    _key_cache[cache_key] = key
    return key


def get_fernet_key(secret_key: str) -> bytes:
    """Derive a Fernet-compatible key from an arbitrary secret string (legacy)."""
    digest = hashlib.sha256(secret_key.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(value: str, secret_key: str) -> str:
    """Encrypt with PBKDF2-derived key. Output: ``pbkdf2$<b64-salt>$<ciphertext>``."""
    salt = os.urandom(16)
    key = _derive_key_pbkdf2(secret_key, salt)
    f = Fernet(key)
    ct = f.encrypt(value.encode()).decode()
    b64_salt = base64.urlsafe_b64encode(salt).decode()
    return f"pbkdf2${b64_salt}${ct}"


def decrypt_value(encrypted: str, secret_key: str) -> str:
    """Decrypt. Detects format: ``pbkdf2$...`` = new, else legacy SHA-256."""
    if encrypted.startswith("pbkdf2$"):
        parts = encrypted.split("$", 2)
        if len(parts) != 3:
            raise ValueError("Invalid pbkdf2 ciphertext format")
        salt = base64.urlsafe_b64decode(parts[1])
        ct = parts[2]
        key = _derive_key_pbkdf2(secret_key, salt)
        f = Fernet(key)
        return f.decrypt(ct.encode()).decode()

    # Legacy path: bare SHA-256 key derivation
    key = get_fernet_key(secret_key)
    f = Fernet(key)
    return f.decrypt(encrypted.encode()).decode()
