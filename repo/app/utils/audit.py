from datetime import datetime, timezone, timedelta
from flask import request, has_request_context
from flask_login import current_user
from app.extensions import db
from app.models.audit import AuditLog, AnomalyAlert
from app.models.user import LoginAttempt

_NEW_DEVICE_COOLDOWN = timedelta(hours=24)


def log_action(action, resource_type, resource_id=None, details=None):
    """Log an audit event capturing the current user and request context.

    ``details`` should be a plain dict; the JSON column serialises it automatically.
    Passing a pre-serialised JSON string is deprecated and will be stored as a
    nested string — always pass a dict.
    """
    user_id = None
    ip_address = None
    user_agent = None

    if has_request_context():
        if current_user and hasattr(current_user, "id") and current_user.is_authenticated:
            user_id = current_user.id
        ip_address = request.remote_addr or "unknown"
        user_agent = (request.headers.get("User-Agent", "") or "")[:500]

    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details_json=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


def check_new_device_alert(user_id, username, ip, ua):
    """Create AnomalyAlert when a user logs in from a new IP or new device.

    A new IP/device is one not seen in any prior successful login for this user.
    Alerts are deduplicated within a 24-hour cooldown window per user+IP and
    user+device to prevent alert fatigue.  Called after _record_attempt so the
    current login is already persisted — we exclude the most-recent record.
    """
    try:
        # All successful logins for this username, oldest-first.
        # The last entry is the one just recorded (current login).
        all_ok = (
            LoginAttempt.query
            .filter_by(username=username, success=True)
            .order_by(LoginAttempt.attempted_at.asc())
            .all()
        )
        # If this is the very first login there are no prior sessions to compare.
        if len(all_ok) <= 1:
            return

        prior = all_ok[:-1]  # everything before the current login
        known_ips = {a.ip_address for a in prior if a.ip_address}
        known_uas = {a.user_agent for a in prior if a.user_agent}

        now = datetime.now(timezone.utc)
        cooldown_start = now - _NEW_DEVICE_COOLDOWN

        # ── New IP ──────────────────────────────────────────────────────────
        if ip and ip not in known_ips:
            already_alerted = AnomalyAlert.query.filter(
                AnomalyAlert.alert_type == "new_ip",
                AnomalyAlert.created_at >= cooldown_start,
                AnomalyAlert.message.contains(f"user={username}"),
                AnomalyAlert.message.contains(f"ip={ip}"),
            ).first()
            if not already_alerted:
                db.session.add(AnomalyAlert(
                    alert_type="new_ip",
                    severity="warning",
                    message=f"New IP login: user={username}, ip={ip}",
                    details_json={"user_id": user_id, "username": username, "ip": ip},
                ))

        # ── New device (user-agent) ──────────────────────────────────────────
        if ua and ua not in known_uas:
            already_alerted = AnomalyAlert.query.filter(
                AnomalyAlert.alert_type == "new_device",
                AnomalyAlert.created_at >= cooldown_start,
                AnomalyAlert.message.contains(f"user={username}"),
            ).first()
            if not already_alerted:
                ua_short = ua[:120]
                db.session.add(AnomalyAlert(
                    alert_type="new_device",
                    severity="info",
                    message=f"New device login: user={username}, ua={ua_short}",
                    details_json={"user_id": user_id, "username": username, "user_agent": ua[:200]},
                ))

        db.session.commit()
    except Exception:
        db.session.rollback()


def anomaly_detection():
    """Check for anomalous patterns and create alerts.

    Currently checks:
    - More than 5 failed login attempts in the last 10 minutes.
    """
    now = datetime.now(timezone.utc)
    window = now - timedelta(minutes=10)

    try:
        failed_count = LoginAttempt.query.filter(
            LoginAttempt.success == False,
            LoginAttempt.attempted_at >= window,
        ).count()
    except Exception:
        failed_count = 0

    if failed_count > 5:
        # Check if we already created an alert for this in the last 10 minutes
        recent_alert = AnomalyAlert.query.filter(
            AnomalyAlert.alert_type == "failed_logins",
            AnomalyAlert.created_at >= window,
        ).first()
        if not recent_alert:
            alert = AnomalyAlert(
                alert_type="failed_logins",
                severity="warning",
                message=f"{failed_count} failed login attempts in the last 10 minutes",
            )
            db.session.add(alert)
            db.session.commit()
