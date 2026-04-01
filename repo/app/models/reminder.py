from datetime import datetime, timezone
from app.extensions import db


class Reminder(db.Model):
    __tablename__ = "reminders"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    type = db.Column(db.String(30), nullable=False)  # appointment / reassessment
    message = db.Column(db.String(500), nullable=False)
    due_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending / sent / dismissed
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    VALID_TYPES = ("appointment", "reassessment")
    VALID_STATUSES = ("pending", "sent", "dismissed")

    patient = db.relationship("User", backref="reminders")
