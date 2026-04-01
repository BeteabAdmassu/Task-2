"""Auto-generation of pending reminders for appointments and reassessments."""

from datetime import datetime, timezone, timedelta, date
from app.extensions import db
from app.models.reminder import Reminder
from app.models.scheduling import Reservation, Slot
from app.models.assessment import AssessmentResult
from app.models.user import User


def generate_pending_reminders():
    """Generate reminders for upcoming appointments and overdue reassessments.

    - Confirmed reservations with slot date ~24h from now that lack an appointment reminder.
    - Patients whose last assessment was >90 days ago that lack a reassessment reminder.
    """
    _generate_appointment_reminders()
    _generate_reassessment_reminders()


def _generate_appointment_reminders():
    """Create appointment reminders for confirmed reservations with slot date within 24 hours."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(hours=24)).date()

    # Find confirmed reservations whose slot date is tomorrow (within 24h)
    confirmed = (
        db.session.query(Reservation)
        .join(Slot, Reservation.slot_id == Slot.id)
        .filter(
            Reservation.status == "confirmed",
            Slot.date == tomorrow,
        )
        .all()
    )

    for res in confirmed:
        # Check if an appointment reminder already exists for this patient + date
        existing = Reminder.query.filter_by(
            patient_id=res.patient_id,
            type="appointment",
            due_date=res.slot.date,
        ).first()
        if not existing:
            reminder = Reminder(
                patient_id=res.patient_id,
                type="appointment",
                message=f"You have an appointment on {res.slot.date}.",
                due_date=res.slot.date,
                status="pending",
            )
            db.session.add(reminder)

    db.session.commit()


def _generate_reassessment_reminders():
    """Create reassessment reminders for patients whose last assessment was >90 days ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    today = date.today()

    # Find all patients (active users with role=patient)
    patients = User.query.filter_by(role="patient", is_active=True).all()

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
                existing = Reminder.query.filter_by(
                    patient_id=patient.id,
                    type="reassessment",
                    status="pending",
                ).first()
                if not existing:
                    reminder = Reminder(
                        patient_id=patient.id,
                        type="reassessment",
                        message="It has been over 90 days since your last assessment. Please schedule a reassessment.",
                        due_date=today,
                        status="pending",
                    )
                    db.session.add(reminder)

    db.session.commit()
