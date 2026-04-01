from datetime import datetime, timezone
from app.extensions import db


class CoverageZone(db.Model):
    __tablename__ = "coverage_zones"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(500), nullable=True)
    zip_codes_json = db.Column(db.JSON, nullable=False, default=list)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    assignments = db.relationship("ZoneAssignment", backref="zone", lazy="dynamic")


class ZoneAssignment(db.Model):
    __tablename__ = "zone_assignments"

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey("coverage_zones.id"), nullable=False, index=True)
    clinician_id = db.Column(db.Integer, db.ForeignKey("clinicians.id"), nullable=False, index=True)
    assignment_type = db.Column(db.String(20), nullable=False, default="primary")  # primary/backup

    clinician = db.relationship("Clinician", backref="zone_assignments")

    __table_args__ = (
        db.UniqueConstraint("zone_id", "clinician_id", name="uq_zone_clinician"),
    )
