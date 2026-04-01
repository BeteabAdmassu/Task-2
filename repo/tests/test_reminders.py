"""Tests for prompt 11 — Reminders & Reassessments."""

import pytest
from datetime import date, datetime, timedelta, timezone
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
        assert r.dismissed_at is not None


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


def test_reminder_new_fields(app, db):
    """Test that the new model fields exist and work correctly."""
    uid = _create_user(app, "pat_rem_fields")
    with app.app_context():
        now = datetime.now(timezone.utc)
        r = Reminder(
            patient_id=uid, type="appointment",
            message="Test fields", due_date=date.today(), status="pending",
            related_entity_type="reservation",
            related_entity_id=42,
            seen_at=now,
            acted_at=now,
            dismissed_at=now,
            expires_at=now,
        )
        db.session.add(r)
        db.session.commit()
        fetched = db.session.get(Reminder, r.id)
        assert fetched.related_entity_type == "reservation"
        assert fetched.related_entity_id == 42
        assert fetched.seen_at is not None
        assert fetched.acted_at is not None
        assert fetched.dismissed_at is not None
        assert fetched.expires_at is not None


def test_auto_generate_appointment_reminder(client, app, db):
    """Confirmed reservation with slot 24h away should generate an appointment reminder."""
    from datetime import time
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
        assert reminder.related_entity_type == "reservation"
        assert reminder.related_entity_id == res.id


def test_auto_generate_reassessment_reminder(client, app, db):
    """Patient with last assessment >90 days ago should get a reassessment reminder."""
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
        assert reminder.related_entity_type == "assessment"
        assert reminder.related_entity_id == result.id


def test_auto_generate_no_duplicate_reminders(client, app, db):
    """Running generate_pending_reminders twice should not create duplicates."""
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


def test_expire_canceled_reservation_reminders(client, app, db):
    """Reminders for canceled reservations should be auto-expired."""
    from datetime import time
    from app.models.scheduling import Clinician, Slot, Reservation
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_expire1")
    clin_uid = _create_user(app, "clin_expire1", role="clinician")
    with app.app_context():
        clinician = Clinician(user_id=clin_uid, specialty="General")
        db.session.add(clinician)
        db.session.flush()

        tomorrow = (datetime.now(timezone.utc) + timedelta(hours=24)).date()
        slot = Slot(
            clinician_id=clinician.id, date=tomorrow,
            start_time=time(10, 0), end_time=time(10, 15),
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

        # Generate reminder first
        generate_pending_reminders()
        reminder = Reminder.query.filter_by(
            patient_id=uid, type="appointment", related_entity_id=res.id
        ).first()
        assert reminder is not None
        assert reminder.status == "pending"

        # Cancel the reservation
        res.status = "canceled"
        db.session.commit()

        # Run again — should expire the reminder
        generate_pending_reminders()
        db.session.refresh(reminder)
        assert reminder.status == "expired"


def test_reminder_count_endpoint(client, app, db):
    """GET /reminders/patient/count returns badge HTML for pending reminders."""
    uid = _create_user(app, "pat_count1")
    with app.app_context():
        r = Reminder(
            patient_id=uid, type="appointment",
            message="Count test", due_date=date.today(),
            status="pending"
        )
        db.session.add(r)
        db.session.commit()
    _login(client, "pat_count1")
    resp = client.get("/reminders/patient/count")
    assert resp.status_code == 200
    assert b"1" in resp.data
    assert b"badge" in resp.data


def test_reminder_count_zero(client, app, db):
    """GET /reminders/patient/count returns empty when no pending reminders."""
    _create_user(app, "pat_count2")
    _login(client, "pat_count2")
    resp = client.get("/reminders/patient/count")
    assert resp.status_code == 200
    assert resp.data.strip() == b""


def test_admin_config_page(client, app, db):
    """GET /reminders/admin/config shows config page for admins."""
    _create_user(app, "admin_cfg1", role="administrator")
    _login(client, "admin_cfg1")
    resp = client.get("/reminders/admin/config")
    assert resp.status_code == 200
    assert b"Reassessment" in resp.data
    assert b"90" in resp.data


def test_admin_config_requires_admin(client, app, db):
    """Non-admin cannot access config page."""
    _create_user(app, "pat_cfg1")
    _login(client, "pat_cfg1")
    resp = client.get("/reminders/admin/config")
    assert resp.status_code == 403


def test_admin_update_config(client, app, db):
    """POST /reminders/admin/config/<template_id> updates config."""
    _create_user(app, "admin_cfg2", role="administrator")
    _login(client, "admin_cfg2")
    resp = client.post(
        "/reminders/admin/config/0",
        data={"interval_days": "60"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"updated" in resp.data.lower()


# ---------------------------------------------------------------------------
# Scheduler-driven generation (no route visit required)
# ---------------------------------------------------------------------------

def test_scheduler_job_generates_reminders_without_page_visit(app, db):
    """generate_pending_reminders() works directly — no HTTP request needed.

    This mirrors what the background scheduler job does every 15 minutes.
    """
    from app.models.assessment import AssessmentTemplate, AssessmentResult
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_sched1")
    with app.app_context():
        tmpl = AssessmentTemplate(
            name="SchedTest", version=1,
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

        # Call the generation function directly — as the scheduler job does.
        # No client.get('/reminders') is called.
        generate_pending_reminders()

        reminder = Reminder.query.filter_by(
            patient_id=uid, type="reassessment", status="pending"
        ).first()
        assert reminder is not None


def test_scheduler_uses_app_context(app, db):
    """The scheduler job function runs generate_pending_reminders inside an app context."""
    from app.utils.reminders import generate_pending_reminders

    # Verify the function can be called within app.app_context() without error,
    # which is exactly what the scheduler's _job() wrapper does.
    with app.app_context():
        generate_pending_reminders()  # should not raise


# ---------------------------------------------------------------------------
# Login-triggered reminder refresh
# ---------------------------------------------------------------------------

def test_login_generates_reminder_for_user(client, app, db):
    """A successful login triggers reminder generation for that user."""
    from app.models.assessment import AssessmentTemplate, AssessmentResult

    uid = _create_user(app, "pat_login_rem1")
    with app.app_context():
        tmpl = AssessmentTemplate(
            name="LoginTest", version=1,
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

    # Login — reminder generation should happen as a side-effect.
    # We do NOT visit /reminders.
    _login(client, "pat_login_rem1")

    with app.app_context():
        reminder = Reminder.query.filter_by(
            patient_id=uid, type="reassessment", status="pending"
        ).first()
        assert reminder is not None


def test_login_reminder_refresh_does_not_affect_other_users(client, app, db):
    """Login-time refresh only touches the logging-in user's reminders."""
    from app.models.assessment import AssessmentTemplate, AssessmentResult

    uid_a = _create_user(app, "pat_login_a")
    uid_b = _create_user(app, "pat_login_b")

    with app.app_context():
        tmpl = AssessmentTemplate(
            name="LoginTest2", version=1,
            questions_json="[]", scoring_rules_json="{}",
        )
        db.session.add(tmpl)
        db.session.flush()

        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        for uid in (uid_a, uid_b):
            result = AssessmentResult(
                patient_id=uid, template_id=tmpl.id, template_version=1,
                answers_json="{}", scores_json="{}", risk_level="Low",
                explanation_snapshot_json="{}", submitted_at=old_date,
            )
            db.session.add(result)
        db.session.commit()

    # Only pat_login_a logs in.
    _login(client, "pat_login_a")

    with app.app_context():
        count_a = Reminder.query.filter_by(patient_id=uid_a, type="reassessment").count()
        count_b = Reminder.query.filter_by(patient_id=uid_b, type="reassessment").count()
        assert count_a == 1
        assert count_b == 0  # pat_login_b did not log in — no reminder yet


# ---------------------------------------------------------------------------
# Admin config persists and affects reminder generation
# ---------------------------------------------------------------------------

def test_admin_config_persists_to_db(client, app, db):
    """POSTing a new interval saves a ReminderConfig row to the database."""
    from app.models.reminder import ReminderConfig

    _create_user(app, "admin_cfg_db", role="administrator")
    _login(client, "admin_cfg_db")
    resp = client.post(
        "/reminders/admin/config/0",
        data={"interval_days": "45"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        cfg = ReminderConfig.query.filter_by(template_id="reassessment").first()
        assert cfg is not None
        assert cfg.interval_days == 45


def test_admin_config_page_reflects_persisted_value(client, app, db):
    """After saving a custom interval, the config page shows the persisted value."""
    from app.models.reminder import ReminderConfig

    _create_user(app, "admin_cfg_page", role="administrator")
    _login(client, "admin_cfg_page")

    with app.app_context():
        cfg = ReminderConfig(template_id="reassessment", interval_days=30)
        db.session.add(cfg)
        db.session.commit()

    resp = client.get("/reminders/admin/config")
    assert resp.status_code == 200
    assert b"30" in resp.data


def test_shorter_interval_triggers_reassessment_reminder(app, db):
    """Setting a shorter interval causes reminders for patients just past that threshold."""
    from app.models.assessment import AssessmentTemplate, AssessmentResult
    from app.models.reminder import ReminderConfig
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_interval1")
    with app.app_context():
        # Persist interval of 60 days.
        cfg = ReminderConfig(template_id="reassessment", interval_days=60)
        db.session.add(cfg)

        tmpl = AssessmentTemplate(
            name="IntervalTest", version=1,
            questions_json="[]", scoring_rules_json="{}",
        )
        db.session.add(tmpl)
        db.session.flush()

        # Assessment is 75 days old — over 60-day threshold, under default 90.
        submitted = datetime.now(timezone.utc) - timedelta(days=75)
        result = AssessmentResult(
            patient_id=uid, template_id=tmpl.id, template_version=1,
            answers_json="{}", scores_json="{}", risk_level="Low",
            explanation_snapshot_json="{}", submitted_at=submitted,
        )
        db.session.add(result)
        db.session.commit()

        generate_pending_reminders()

        reminder = Reminder.query.filter_by(
            patient_id=uid, type="reassessment", status="pending"
        ).first()
        assert reminder is not None
        assert "60 days" in reminder.message


def test_default_interval_does_not_trigger_for_recent_assessment(app, db):
    """With default 90-day interval, a 75-day-old assessment produces no reminder."""
    from app.models.assessment import AssessmentTemplate, AssessmentResult
    from app.utils.reminders import generate_pending_reminders

    uid = _create_user(app, "pat_interval2")
    with app.app_context():
        # No ReminderConfig row — defaults to 90 days.
        tmpl = AssessmentTemplate(
            name="IntervalTest2", version=1,
            questions_json="[]", scoring_rules_json="{}",
        )
        db.session.add(tmpl)
        db.session.flush()

        submitted = datetime.now(timezone.utc) - timedelta(days=75)
        result = AssessmentResult(
            patient_id=uid, template_id=tmpl.id, template_version=1,
            answers_json="{}", scores_json="{}", risk_level="Low",
            explanation_snapshot_json="{}", submitted_at=submitted,
        )
        db.session.add(result)
        db.session.commit()

        generate_pending_reminders()

        reminder = Reminder.query.filter_by(
            patient_id=uid, type="reassessment", status="pending"
        ).first()
        assert reminder is None  # 75 days < 90-day default threshold
