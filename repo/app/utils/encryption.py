from cryptography.fernet import Fernet
from flask import current_app

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        key = current_app.config.get("ENCRYPTION_KEY")
        if not key:
            raise RuntimeError("ENCRYPTION_KEY not configured")
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_value(plaintext):
    if not plaintext:
        return None
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext):
    if not ciphertext:
        return None
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def mask_id(value):
    """Show only last 4 characters, mask the rest."""
    if not value:
        return ""
    if len(value) <= 4:
        return value
    return "***-**-" + value[-4:]


def reset_fernet():
    """Reset cached fernet instance (for testing)."""
    global _fernet
    _fernet = None
