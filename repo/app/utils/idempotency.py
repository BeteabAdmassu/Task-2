import hashlib
from datetime import datetime, timezone
from functools import wraps
from flask import request, jsonify
from flask_login import current_user
from app.extensions import db
from app.models.idempotency import RequestToken


def _hash_token(token: str) -> str:
    """One-way hash an idempotency token for safe at-rest storage."""
    return hashlib.sha256(token.encode()).hexdigest()


# Public alias used by routes that persist their own token columns.
hash_token = _hash_token


def check_idempotency(token, user_id=None):
    """Return cached result dict if token exists and hasn't expired, else None."""
    if not token:
        return None
    record = RequestToken.query.filter_by(token=_hash_token(token)).first()
    if record and user_id is not None and record.user_id is not None and record.user_id != user_id:
        return None
    if record is None:
        return None
    now = datetime.now(timezone.utc)
    expires = record.expires_at
    if expires:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            db.session.delete(record)
            db.session.commit()
            return None
    return record.result_json


def save_idempotency(token, endpoint, result=None, user_id=None):
    """Save a result for the given idempotency token (stored as hash)."""
    if not token:
        return
    token_hash = _hash_token(token)
    record = RequestToken.query.filter_by(token=token_hash).first()
    if record:
        return  # already saved
    record = RequestToken(
        token=token_hash,
        endpoint=endpoint,
        result_json=result,
        user_id=user_id,
    )
    db.session.add(record)
    db.session.commit()
    return record


def idempotent(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.form.get("_request_token") or request.headers.get("X-Request-Token")
        if token:
            user_id = current_user.id if current_user.is_authenticated else None
            existing = check_idempotency(token, user_id=user_id)
            if existing:
                return jsonify({"error": "This action has already been processed"}), 409
        result = f(*args, **kwargs)
        if token:
            user_id = current_user.id if current_user.is_authenticated else None
            save_idempotency(token, request.path, result={"processed": True}, user_id=user_id)
        return result
    return decorated
