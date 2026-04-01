from datetime import datetime, timezone, timedelta
from flask import request, has_request_context
from flask_login import current_user
from app.extensions import db
from app.models.audit import AuditLog, AnomalyAlert
from app.models.user import LoginAttempt


def log_action(action, resource_type, resource_id=None, details=None):
    """Log an audit event capturing the current user and request context."""
    user_id = None
    ip_address = None
    user_agent = None

    if has_request_context():
        if current_user and hasattr(current_user, "id") and current_user.is_authenticated:
            user_id = current_user.id
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"
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
