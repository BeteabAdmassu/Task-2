"""Auto-generation of pending reminders for appointments and reassessments."""

from datetime import datetime, timezone, timedelta, date
from app.extensions import db
from app.models.reminder import Reminder
from app.models.scheduling import Reservation, Slot
from app.models.assessment import AssessmentResult
from app.models.user import User


def generate_pending_reminders(user_id=None):
    """Generate reminders for upcoming appointments and overdue reassessments.

    - Confirmed reservations with slot date ~24h from now that lack an appointment reminder.
    - Patients whose last assessment was >configured interval days ago that lack a
      reassessment reminder.
    - Auto-expire reminders for canceled reservations.

    Pass *user_id* to restrict all operations to a single patient (used on login
    for a lightweight per-user refresh).
    """
    _generate_appointment_reminders(user_id=user_id)
    _generate_reassessment_reminders(user_id=user_id)
    _expire_canceled_reservation_reminders(user_id=user_id)


def _generate_appointment_reminders(user_id=None):
    """Create appointment reminders for confirmed reservations whose slot starts within 24 hours.

    Eligibility window: now <= slot_datetime < now + 24h, where slot_datetime is
    derived from Slot.date + Slot.start_time (treated as UTC).  The DB query
    pre-filters by date range; the Python loop applies the exact datetime check.
    """
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(hours=24)

    # Pre-filter: at most two calendar dates can overlap the 24h window.
    date_lo = now.date()
    date_hi = window_end.date()

    query = (
        db.session.query(Reservation)
        .join(Slot, Reservation.slot_id == Slot.id)
        .filter(
            Reservation.status == "confirmed",
            Slot.date >= date_lo,
            Slot.date <= date_hi,
        )
    )
    if user_id is not None:
        query = query.filter(Reservation.patient_id == user_id)
    candidates = query.all()

    for res in candidates:
        # Exact datetime check: slot must start within [now, now+24h).
        slot_dt = datetime.combine(res.slot.date, res.slot.start_time).replace(
            tzinfo=timezone.utc
        )
        if not (now <= slot_dt < window_end):
            continue
        # Dedup by patient_id + related_entity_type + related_entity_id
        existing = Reminder.query.filter_by(
            patient_id=res.patient_id,
            related_entity_type="reservation",
            related_entity_id=res.id,
        ).first()
        if existing:
            continue
        # Also check legacy dedup by patient + type + date
        existing_legacy = Reminder.query.filter_by(
            patient_id=res.patient_id,
            type="appointment",
            due_date=res.slot.date,
        ).first()
        if not existing_legacy:
            reminder = Reminder(
                patient_id=res.patient_id,
                type="appointment",
                message=f"You have an appointment on {res.slot.date}.",
                due_date=res.slot.date,
                status="pending",
                related_entity_type="reservation",
                related_entity_id=res.id,
            )
            db.session.add(reminder)

    db.session.commit()


def _generate_reassessment_reminders(user_id=None):
    """Create reassessment reminders for patients whose last assessment is overdue."""
    from app.models.reminder import ReminderConfig

    interval_days = ReminderConfig.get_interval("reassessment", default=90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=interval_days)
    today = date.today()

    # Find all (or one) active patient(s)
    query = User.query.filter_by(role="patient", is_active=True)
    if user_id is not None:
        query = query.filter_by(id=user_id)
    patients = query.all()

    for patient in patients:
        # Find the most recent assessment
        latest = (
            AssessmentResult.query
            .filter_by(patient_id=patient.id)
            .order_by(AssessmentResult.submitted_at.desc())
            .first()
        )

        if latest and latest.submitted_at:
            submitted = latest.submitted_at
            if submitted.tzinfo is None:
                submitted = submitted.replace(tzinfo=timezone.utc)
            if submitted < cutoff:
                # Check if a pending reassessment reminder already exists
                # Dedup by patient_id + related_entity_type + related_entity_id
                existing = Reminder.query.filter_by(
                    patient_id=patient.id,
                    related_entity_type="assessment",
                    related_entity_id=latest.id,
                ).first()
                if existing:
                    continue
                # Also check legacy dedup
                existing_legacy = Reminder.query.filter_by(
                    patient_id=patient.id,
                    type="reassessment",
                    status="pending",
                ).first()
                if not existing_legacy:
                    reminder = Reminder(
                        patient_id=patient.id,
                        type="reassessment",
                        message=(
                            f"It has been over {interval_days} days since your last "
                            "assessment. Please schedule a reassessment."
                        ),
                        due_date=today,
                        status="pending",
                        related_entity_type="assessment",
                        related_entity_id=latest.id,
                    )
                    db.session.add(reminder)

    db.session.commit()


def _expire_canceled_reservation_reminders(user_id=None):
    """Auto-expire reminders whose related reservation has been canceled."""
    query = Reservation.query.filter_by(status="canceled")
    if user_id is not None:
        query = query.filter_by(patient_id=user_id)
    canceled_reservations = query.all()
    for res in canceled_reservations:
        pending_reminders = Reminder.query.filter_by(
            related_entity_type="reservation",
            related_entity_id=res.id,
            status="pending",
        ).all()
        for rem in pending_reminders:
            rem.status = "expired"
    db.session.commit()
