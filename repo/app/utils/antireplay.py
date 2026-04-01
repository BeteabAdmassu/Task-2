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
        nonce = request.headers.get("X-Nonce") or request.form.get("_nonce")
        ts_header = request.headers.get("X-Timestamp") or request.form.get("_timestamp")
        if not nonce or not ts_header:
            return f(*args, **kwargs)  # graceful fallback
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
