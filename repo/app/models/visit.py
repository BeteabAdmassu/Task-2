from datetime import datetime, timezone
from app.extensions import db


class Visit(db.Model):
    __tablename__ = "visits"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    clinician_id = db.Column(db.Integer, db.ForeignKey("clinicians.id"), nullable=False, index=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("slots.id"), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="booked")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    VALID_STATUSES = ("booked", "pending_payment", "checked_in", "seen", "canceled", "no_show")

    patient = db.relationship("User", foreign_keys=[patient_id], backref="visits")
    clinician = db.relationship("Clinician", backref="visits")
    slot = db.relationship("Slot", backref="visits")


class VisitTransition(db.Model):
    __tablename__ = "visit_transitions"

    id = db.Column(db.Integer, primary_key=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=False, index=True)
    from_status = db.Column(db.String(20), nullable=False)
    to_status = db.Column(db.String(20), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    reason = db.Column(db.String(500), nullable=True)
    request_token = db.Column(db.String(64), unique=True, nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    visit = db.relationship("Visit", backref="transitions")
    changed_by_user = db.relationship("User", foreign_keys=[changed_by])
