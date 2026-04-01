import hmac
import hashlib
import time
from datetime import datetime, timezone, timedelta
from flask import request, current_app, jsonify
from functools import wraps
from app.extensions import db
from app.models.audit import SignedRequest

REPLAY_WINDOW = timedelta(minutes=5)


def antireplay(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Only enforce anti-replay on state-mutating methods.
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return f(*args, **kwargs)

        # Lazily purge expired nonces so the table doesn't grow unbounded.
        try:
            SignedRequest.query.filter(
                SignedRequest.expires_at < datetime.now(timezone.utc)
            ).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()

        nonce = request.headers.get("X-Nonce") or request.form.get("_nonce")
        ts_header = request.headers.get("X-Timestamp") or request.form.get("_timestamp")
        if not nonce or not ts_header:
            return jsonify({"error": "Missing nonce or timestamp"}), 400
        try:
            ts = datetime.fromisoformat(ts_header)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return jsonify({"error": "Request expired, please try again"}), 400
        now = datetime.now(timezone.utc)
        if abs(now - ts) > REPLAY_WINDOW:
            return jsonify({"error": "Request expired, please try again"}), 400
        existing = SignedRequest.query.filter_by(nonce=nonce).first()
        if existing:
            return jsonify({"error": "Request expired, please try again"}), 409
        sr = SignedRequest(nonce=nonce, timestamp=ts, expires_at=ts + REPLAY_WINDOW)
        db.session.add(sr)
        db.session.commit()
        return f(*args, **kwargs)
    return decorated
