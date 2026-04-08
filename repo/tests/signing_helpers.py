"""Shared test helpers for anti-replay signed request data.

The secret must match TestingConfig.REQUEST_SIGNING_SECRET exactly so that the
decorator's HMAC verification passes in test runs.
"""
import hmac
import hashlib
import uuid
from datetime import datetime, timezone

TEST_SIGNING_SECRET = "test-request-signing-secret-dev-only"


def signed_data(method: str, path: str, extra: dict | None = None) -> dict:
    """Return a form-data dict with _nonce, _timestamp, and _signature.

    Parameters
    ----------
    method : HTTP verb (e.g. "POST")
    path   : URL path exactly as Flask will see it in request.path
             (e.g. "/visits/1/transition")
    extra  : additional form fields to merge in (e.g. {"target_state": "checked_in"})
    """
    nonce = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = f"{method.upper()}|{path}|{nonce}|{timestamp}"
    sig = hmac.new(
        TEST_SIGNING_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    data = {"_nonce": nonce, "_timestamp": timestamp, "_signature": sig}
    if extra:
        data.update(extra)
    return data


def login_data(username: str, password: str = "Password1") -> dict:
    """Return form data for a signed login POST."""
    return signed_data("POST", "/auth/login", {"username": username, "password": password})
