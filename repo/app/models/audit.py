from datetime import datetime, timezone
from app.extensions import db


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(100), nullable=False)
    resource_id = db.Column(db.String(100), nullable=True)
    details_json = db.Column(db.JSON, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    user = db.relationship("User", backref="audit_logs")


class AnomalyAlert(db.Model):
    __tablename__ = "anomaly_alerts"
    id = db.Column(db.Integer, primary_key=True)
    alert_type = db.Column(db.String(50), nullable=False)  # failed_logins, new_ip, high_error_rate
    severity = db.Column(db.String(20), nullable=False, default="warning")  # info, warning, critical
    message = db.Column(db.Text, nullable=False)
    details_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    acknowledged_at = db.Column(db.DateTime, nullable=True)
    acknowledged_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


class SlowQuery(db.Model):
    __tablename__ = "slow_queries"
    id = db.Column(db.Integer, primary_key=True)
    query_text = db.Column(db.Text, nullable=True)
    duration_ms = db.Column(db.Float, nullable=False)
    endpoint = db.Column(db.String(255), nullable=True)
    correlation_id = db.Column(db.String(64), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class SignedRequest(db.Model):
    __tablename__ = "signed_requests"
    id = db.Column(db.Integer, primary_key=True)
    nonce = db.Column(db.String(64), unique=True, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
