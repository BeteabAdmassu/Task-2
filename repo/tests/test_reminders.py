"""Tests for prompt 11 — Reminders & Reassessments."""

import pytest
from datetime import date, timedelta
from app.models.user import User
from app.models.reminder import Reminder
from app.extensions import db


def _create_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, username, password="Password1"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_reminders_page_requires_login(client, app, db):
    resp = client.get("/reminders")
    assert resp.status_code in (302, 401)


def test_reminders_page_shows_pending(client, app, db):
    uid = _create_user(app, "pat_rem1")
    with app.app_context():
        r = Reminder(
            patient_id=uid, type="appointment",
            message="Checkup tomorrow", due_date=date.today() + timedelta(days=1),
            status="pending"
        )
        db.session.add(r)
        db.session.commit()
    _login(client, "pat_rem1")
    resp = client.get("/reminders")
    assert resp.status_code == 200
    assert b"Checkup tomorrow" in resp.data


def test_dismiss_reminder(client, app, db):
    uid = _create_user(app, "pat_rem2")
    with app.app_context():
        r = Reminder(
            patient_id=uid, type="reassessment",
            message="Reassess pain", due_date=date.today(),
            status="pending"
        )
        db.session.add(r)
        db.session.commit()
        rid = r.id
    _login(client, "pat_rem2")
    resp = client.post(f"/reminders/{rid}/dismiss", follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        r = db.session.get(Reminder, rid)
        assert r.status == "dismissed"


def test_dismiss_other_user_reminder_denied(client, app, db):
    uid1 = _create_user(app, "pat_rem3")
    uid2 = _create_user(app, "pat_rem4")
    with app.app_context():
        r = Reminder(
            patient_id=uid1, type="appointment",
            message="Not yours", due_date=date.today(),
            status="pending"
        )
        db.session.add(r)
        db.session.commit()
        rid = r.id
    _login(client, "pat_rem4")
    resp = client.post(f"/reminders/{rid}/dismiss", follow_redirects=True)
    assert b"Access denied" in resp.data


def test_admin_reminders_page(client, app, db):
    _create_user(app, "admin_rem1", role="administrator")
    _login(client, "admin_rem1")
    resp = client.get("/reminders/admin")
    assert resp.status_code == 200
    assert b"All Reminders" in resp.data


def test_admin_reminders_requires_admin(client, app, db):
    _create_user(app, "pat_rem5")
    _login(client, "pat_rem5")
    resp = client.get("/reminders/admin")
    assert resp.status_code == 403


def test_reminder_model_fields(app, db):
    uid = _create_user(app, "pat_rem6")
    with app.app_context():
        r = Reminder(
            patient_id=uid, type="appointment",
            message="Test msg", due_date=date.today(), status="pending"
        )
        db.session.add(r)
        db.session.commit()
        fetched = db.session.get(Reminder, r.id)
        assert fetched.type == "appointment"
        assert fetched.status == "pending"
        assert fetched.message == "Test msg"


def test_auto_generate_appointment_reminder(client, app, db):
    """Confirmed reservation with slot 24h away should generate an appointment reminder."""
    from datetime import datetime, timezone, timedelta, time
    from app.models.scheduling import Clinician, Slot, Reservation
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_autorem1")
    clin_uid = _create_user(app, "clin_autorem1", role="clinician")
    with app.app_context():
        clinician = Clinician(user_id=clin_uid, specialty="General")
        db.session.add(clinician)
        db.session.flush()

        tomorrow = (datetime.now(timezone.utc) + timedelta(hours=24)).date()
        slot = Slot(
            clinician_id=clinician.id, date=tomorrow,
            start_time=time(9, 0), end_time=time(9, 15),
            capacity=1, booked_count=1, status="available",
        )
        db.session.add(slot)
        db.session.flush()

        res = Reservation(
            slot_id=slot.id, patient_id=uid, status="confirmed",
            confirmed_at=datetime.now(timezone.utc),
        )
        db.session.add(res)
        db.session.commit()

        generate_pending_reminders()

        reminder = Reminder.query.filter_by(
            patient_id=uid, type="appointment", due_date=tomorrow
        ).first()
        assert reminder is not None
        assert reminder.status == "pending"


def test_auto_generate_reassessment_reminder(client, app, db):
    """Patient with last assessment >90 days ago should get a reassessment reminder."""
    from datetime import datetime, timezone, timedelta
    from app.models.assessment import AssessmentTemplate, AssessmentResult
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_autorem2")
    with app.app_context():
        tmpl = AssessmentTemplate(
            name="Test", version=1,
            questions_json="[]", scoring_rules_json="{}",
        )
        db.session.add(tmpl)
        db.session.flush()

        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        result = AssessmentResult(
            patient_id=uid, template_id=tmpl.id, template_version=1,
            answers_json="{}", scores_json="{}", risk_level="Low",
            explanation_snapshot_json="{}", submitted_at=old_date,
        )
        db.session.add(result)
        db.session.commit()

        generate_pending_reminders()

        reminder = Reminder.query.filter_by(
            patient_id=uid, type="reassessment", status="pending"
        ).first()
        assert reminder is not None
        assert "90 days" in reminder.message


def test_auto_generate_no_duplicate_reminders(client, app, db):
    """Running generate_pending_reminders twice should not create duplicates."""
    from datetime import datetime, timezone, timedelta
    from app.models.assessment import AssessmentTemplate, AssessmentResult
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_autorem3")
    with app.app_context():
        tmpl = AssessmentTemplate(
            name="Test2", version=1,
            questions_json="[]", scoring_rules_json="{}",
        )
        db.session.add(tmpl)
        db.session.flush()

        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        result = AssessmentResult(
            patient_id=uid, template_id=tmpl.id, template_version=1,
            answers_json="{}", scores_json="{}", risk_level="Low",
            explanation_snapshot_json="{}", submitted_at=old_date,
        )
        db.session.add(result)
        db.session.commit()

        generate_pending_reminders()
        generate_pending_reminders()

        count = Reminder.query.filter_by(
            patient_id=uid, type="reassessment", status="pending"
        ).count()
        assert count == 1
