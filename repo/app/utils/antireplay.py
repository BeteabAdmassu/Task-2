import hmac
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from flask import request, current_app, jsonify
from functools import wraps
from app.extensions import db
from app.models.audit import SignedRequest

# Serialize the nonce check+insert so concurrent threads running on the same
# process (e.g. Werkzeug threaded=True + SQLite NullPool) never race on the
# unique constraint or trigger SQLITE_MISUSE from simultaneous DDL writes.
_NONCE_LOCK = threading.Lock()


def _hash_nonce(nonce: str) -> str:
    """One-way hash a nonce for safe at-rest storage."""
    return hashlib.sha256(nonce.encode()).hexdigest()

REPLAY_WINDOW = timedelta(minutes=5)


def _compute_signature(secret: str, method: str, path: str, nonce: str, timestamp: str) -> str:
    """HMAC-SHA256 over 'METHOD|path|nonce|timestamp' using the server signing secret."""
    payload = f"{method.upper()}|{path}|{nonce}|{timestamp}"
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


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
        signature = request.headers.get("X-Signature") or request.form.get("_signature")

        if not nonce or not ts_header:
            return jsonify({"error": "Missing nonce or timestamp"}), 400

        if not signature:
            return jsonify({"error": "Missing request signature"}), 400

        try:
            ts = datetime.fromisoformat(ts_header)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return jsonify({"error": "Request expired, please try again"}), 400

        now = datetime.now(timezone.utc)
        if abs(now - ts) > REPLAY_WINDOW:
            return jsonify({"error": "Request expired, please try again"}), 400

        # Signature verification — must happen before the nonce is stored so
        # an attacker cannot use a 409 response to probe whether a nonce exists.
        secret = current_app.config.get("REQUEST_SIGNING_SECRET", "")
        expected = _compute_signature(secret, request.method, request.path, nonce, ts_header)
        if not hmac.compare_digest(signature, expected):
            return jsonify({"error": "Invalid request signature"}), 400

        # Replay check — nonce must not have been seen before.
        # Store and compare the SHA-256 hash so raw nonces never reach the DB.
        # The lock prevents concurrent threads from racing on the check+insert
        # (TOCTOU) and from triggering SQLITE_MISUSE on concurrent WAL writes.
        nonce_hash = _hash_nonce(nonce)
        with _NONCE_LOCK:
            existing = SignedRequest.query.filter_by(nonce=nonce_hash).first()
            if existing:
                return jsonify({"error": "Request already processed"}), 409

            sr = SignedRequest(nonce=nonce_hash, timestamp=ts, expires_at=ts + REPLAY_WINDOW)
            db.session.add(sr)
            db.session.commit()
        return f(*args, **kwargs)
    return decorated
