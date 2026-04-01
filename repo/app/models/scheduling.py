from datetime import datetime, timezone, timedelta, time, date
from app.extensions import db


class Clinician(db.Model):
    __tablename__ = "clinicians"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    specialty = db.Column(db.String(100), nullable=True)
    default_slot_duration_minutes = db.Column(db.Integer, nullable=False, default=15)

    user = db.relationship("User", backref=db.backref("clinician_profile", uselist=False))


class ScheduleTemplate(db.Model):
    __tablename__ = "schedule_templates"

    id = db.Column(db.Integer, primary_key=True)
    clinician_id = db.Column(db.Integer, db.ForeignKey("clinicians.id"), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday, 6=Sunday
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    slot_duration = db.Column(db.Integer, nullable=False, default=15)
    capacity = db.Column(db.Integer, nullable=False, default=1)

    clinician = db.relationship("Clinician", backref="schedule_templates")


class Room(db.Model):
    __tablename__ = "rooms"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Slot(db.Model):
    __tablename__ = "slots"

    id = db.Column(db.Integer, primary_key=True)
    clinician_id = db.Column(db.Integer, db.ForeignKey("clinicians.id"), nullable=False, index=True)
    room_id = db.Column(db.Integer, db.ForeignKey("rooms.id"), nullable=True)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=1)
    booked_count = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="available")  # available, holiday, blocked

    clinician = db.relationship("Clinician", backref="slots")
    room = db.relationship("Room", backref="slots")

    __table_args__ = (
        db.UniqueConstraint("clinician_id", "date", "start_time", name="uq_clinician_slot"),
    )

    @property
    def is_available(self):
        if self.status != "available":
            return False
        # Count active holds + confirmed bookings
        active = Reservation.query.filter(
            Reservation.slot_id == self.id,
            Reservation.status.in_(["held", "confirmed"]),
        ).count()
        return active < self.capacity


class Reservation(db.Model):
    __tablename__ = "reservations"

    id = db.Column(db.Integer, primary_key=True)
    slot_id = db.Column(db.Integer, db.ForeignKey("slots.id"), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="held")  # held, confirmed, expired, canceled
    held_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    request_token = db.Column(db.String(64), unique=True, nullable=True)

    slot = db.relationship("Slot", backref="reservations")
    patient = db.relationship("User", foreign_keys=[patient_id])

    def is_expired(self):
        if self.status != "held":
            return False
        if self.expires_at:
            now = datetime.now(timezone.utc)
            exp = self.expires_at.replace(tzinfo=timezone.utc) if self.expires_at.tzinfo is None else self.expires_at
            return now > exp
        return False


class Holiday(db.Model):
    __tablename__ = "holidays"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    name = db.Column(db.String(100), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)


def expire_stale_holds():
    """Expire held reservations past their expiry time."""
    now = datetime.now(timezone.utc)
    stale = Reservation.query.filter(
        Reservation.status == "held",
        Reservation.expires_at <= now,
    ).all()
    for res in stale:
        res.status = "expired"
    if stale:
        db.session.commit()
    return len(stale)
