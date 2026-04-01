from datetime import datetime, timezone, timedelta
from app.extensions import db


class RequestToken(db.Model):
    __tablename__ = "request_tokens"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False, index=True)
    endpoint = db.Column(db.String(200), nullable=False)
    result_json = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(hours=24))
