"""Fernet encryption helpers for sensitive fields at rest.

Used to encrypt/decrypt values before writing to or reading from the DB.
The encryption key comes from the ENCRYPTION_KEY environment variable.

If no key is set, encryption is skipped (dev/test mode) with a warning.
This avoids breaking local development while ensuring production data
is always encrypted.

Usage:
    from crypto import encrypt, decrypt

    encrypted = encrypt("sensitive value")  # returns base64 string
    original  = decrypt(encrypted)          # returns original string
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_fernet = None
_warned = False


def _get_fernet():
    """Lazy-load the Fernet instance from ENCRYPTION_KEY."""
    global _fernet, _warned  # noqa: PLW0603

    if _fernet is not None:
        return _fernet

    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        if not _warned:
            logger.warning(
                "ENCRYPTION_KEY not set — sensitive fields will NOT be "
                "encrypted at rest. Set this in production!"
            )
            _warned = True
        return None

    from cryptography.fernet import Fernet

    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(value: str) -> str:
    """Encrypt a string value. Returns the ciphertext as a UTF-8 string.

    If ENCRYPTION_KEY is not set, returns the value unchanged.
    """
    if not value:
        return value

    f = _get_fernet()
    if f is None:
        return value

    return f.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a ciphertext string back to plaintext.

    If ENCRYPTION_KEY is not set, returns the value unchanged.
    Handles the case where a value was stored unencrypted (before
    encryption was enabled) by returning it as-is if decryption fails.
    """
    if not value:
        return value

    f = _get_fernet()
    if f is None:
        return value

    try:
        return f.decrypt(value.encode()).decode()
    except Exception:
        # Value may have been stored before encryption was enabled
        return value


def reset():
    """Reset the cached Fernet instance. Used in tests."""
    global _fernet, _warned  # noqa: PLW0603
    _fernet = None
    _warned = False
