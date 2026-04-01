from datetime import datetime, timezone
from app.extensions import db
from app.models.idempotency import RequestToken


def check_idempotency(token):
    """Return cached result dict if token exists and hasn't expired, else None."""
    if not token:
        return None
    record = RequestToken.query.filter_by(token=token).first()
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


def save_idempotency(token, endpoint, result):
    """Save a result for the given idempotency token."""
    if not token:
        return
    record = RequestToken.query.filter_by(token=token).first()
    if record:
        return  # already saved
    record = RequestToken(
        token=token,
        endpoint=endpoint,
        result_json=result,
    )
    db.session.add(record)
    db.session.commit()
    return record
