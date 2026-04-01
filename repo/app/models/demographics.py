from datetime import datetime, timezone
from app.extensions import db


class PatientDemographics(db.Model):
    __tablename__ = "patient_demographics"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20), nullable=True)
    phone = db.Column(db.String(20), nullable=False)
    address_street = db.Column(db.String(255), nullable=True)
    address_city = db.Column(db.String(100), nullable=True)
    address_state = db.Column(db.String(50), nullable=True)
    address_zip = db.Column(db.String(10), nullable=True)
    emergency_contact_name = db.Column(db.String(200), nullable=True)
    emergency_contact_phone = db.Column(db.String(20), nullable=True)
    emergency_contact_relationship = db.Column(db.String(50), nullable=True)
    insurance_id_encrypted = db.Column(db.Text, nullable=True)
    government_id_encrypted = db.Column(db.Text, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = db.relationship("User", backref=db.backref("demographics", uselist=False))


class DemographicsChangeLog(db.Model):
    __tablename__ = "demographics_change_log"

    id = db.Column(db.Integer, primary_key=True)
    demographics_id = db.Column(db.Integer, db.ForeignKey("patient_demographics.id"), nullable=False)
    changed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    changed_by = db.relationship("User", foreign_keys=[changed_by_id])
