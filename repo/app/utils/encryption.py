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


def mask_encrypted_id(ciphertext):
    """Decrypt ciphertext then return masked form showing last 4 of plaintext."""
    if not ciphertext:
        return ""
    plaintext = decrypt_value(ciphertext)
    return mask_id(plaintext) if plaintext else ""


def reset_fernet():
    """Reset cached fernet instance (for testing)."""
    global _fernet
    _fernet = None
