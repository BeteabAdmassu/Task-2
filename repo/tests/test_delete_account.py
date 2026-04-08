"""Tests for account deletion anonymization policy.

Verifies that POST /patient/delete-account:
- Anonymizes demographics, clinical notes, change logs, and login attempts
- Preserves assessment results, visits, and reservations for audit
- Keeps audit_logs intact
- Deactivates the account so the user cannot log back in
- Leaves no old identifying values exposed
"""

import pytest
from datetime import date, time, timedelta
from app.models.user import User, LoginAttempt
from app.models.demographics import PatientDemographics, DemographicsChangeLog
from app.models.assessment import AssessmentResult, AssessmentDraft
from app.models.clinical_note import ClinicalNote
from app.models.visit import Visit
from app.models.scheduling import Clinician, Slot, Reservation
from app.models.audit import AuditLog
from app.extensions import db
from tests.signing_helpers import signed_data, login_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _create_clinician(app, username):
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        c = Clinician(user_id=user.id)
        db.session.add(c)
        db.session.commit()
        return user.id, c.id


def _login(client, username, password="Password1"):
    return client.post(
        "/auth/login",
        data=login_data(username, password),
        follow_redirects=True,
    )


def _delete_account(client, password="Password1"):
    path = "/patient/delete-account"
    return client.post(
        path,
        data=signed_data("POST", path, {"password": password}),
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Endpoint contract: existing behavior preserved
# ---------------------------------------------------------------------------

def test_delete_account_requires_auth(client, app):
    resp = client.post("/patient/delete-account", data={})
    assert resp.status_code in (302, 400, 401)


def test_delete_account_wrong_password_rejected(client, app):
    _create_user(app, "pat_del_wp")
    _login(client, "pat_del_wp")
    path = "/patient/delete-account"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"password": "WrongPass1"}),
        follow_redirects=True,
    )
    assert b"incorrect" in resp.data.lower()

    with app.app_context():
        user = User.query.filter_by(username="pat_del_wp").first()
        assert user is not None
        assert user.is_active is True


def test_delete_account_redirects_to_login(client, app):
    _create_user(app, "pat_del_redir")
    _login(client, "pat_del_redir")
    resp = _delete_account(client)
    assert resp.status_code == 200
    assert b"Log In" in resp.data or b"login" in resp.data.lower()


# ---------------------------------------------------------------------------
# User account deactivation
# ---------------------------------------------------------------------------

def test_deleted_user_is_deactivated(client, app):
    pid = _create_user(app, "pat_del_deact")
    _login(client, "pat_del_deact")
    _delete_account(client)

    with app.app_context():
        user = db.session.get(User, pid)
        assert user.is_active is False


def test_deleted_user_username_pseudonymized(client, app):
    pid = _create_user(app, "pat_del_pseudo")
    _login(client, "pat_del_pseudo")
    _delete_account(client)

    with app.app_context():
        user = db.session.get(User, pid)
        assert user.username == f"deleted_{pid}"
        assert "pat_del_pseudo" not in user.username


def test_deleted_user_cannot_log_back_in(client, app):
    _create_user(app, "pat_del_nologin")
    _login(client, "pat_del_nologin")
    _delete_account(client)

    resp = _login(client, "pat_del_nologin")
    # Original username gone, account inactive — login must fail
    assert resp.status_code == 200
    # Should NOT be authenticated — no patient-specific nav content
    assert b"My Profile" not in resp.data


# ---------------------------------------------------------------------------
# Demographics anonymization
# ---------------------------------------------------------------------------

def test_demographics_anonymized_after_deletion(client, app):
    pid = _create_user(app, "pat_del_demo")

    with app.app_context():
        demo = PatientDemographics(
            user_id=pid,
            full_name="Alice Smith",
            phone="555-1234",
            date_of_birth=date(1990, 5, 15),
        )
        db.session.add(demo)
        db.session.commit()

    _login(client, "pat_del_demo")
    _delete_account(client)

    with app.app_context():
        demo = PatientDemographics.query.filter_by(user_id=pid).first()
        assert demo is not None
        assert demo.full_name == "Deleted User"
        # NOT NULL columns use placeholder values rather than None
        assert demo.phone == "0000000"
        assert demo.date_of_birth == date(1900, 1, 1)
        assert demo.gender is None
        assert demo.address_street is None
        assert demo.insurance_id_encrypted is None
        assert demo.government_id_encrypted is None


def test_demographics_change_log_pii_scrubbed(client, app):
    pid = _create_user(app, "pat_del_clog")

    with app.app_context():
        demo = PatientDemographics(
            user_id=pid,
            full_name="Bob Jones",
            phone="555-9999",
            date_of_birth=date(1985, 3, 10),
        )
        db.session.add(demo)
        db.session.commit()
        # Simulate a change log entry with PII in old/new values
        log = DemographicsChangeLog(
            demographics_id=demo.id,
            changed_by_id=pid,
            field_name="full_name",
            old_value="Bobby Jones",
            new_value="Bob Jones",
        )
        db.session.add(log)
        db.session.commit()
        log_id = log.id

    _login(client, "pat_del_clog")
    _delete_account(client)

    with app.app_context():
        log = db.session.get(DemographicsChangeLog, log_id)
        assert log is not None  # record retained for audit
        assert log.old_value is None
        assert log.new_value is None
        assert log.field_name == "full_name"  # field name retained


# ---------------------------------------------------------------------------
# Clinical notes anonymization
# ---------------------------------------------------------------------------

def test_clinical_note_content_removed_after_deletion(client, app):
    _, cid = _create_clinician(app, "doc_del_note")
    pid = _create_user(app, "pat_del_note")

    with app.app_context():
        note = ClinicalNote.create(
            patient_id=pid, author_id=cid, content="Patient reports severe symptoms"
        )
        db.session.add(note)
        db.session.commit()
        note_id = note.id

    _login(client, "pat_del_note")
    _delete_account(client)

    with app.app_context():
        note = db.session.get(ClinicalNote, note_id)
        assert note is not None  # record retained for audit
        # Content must be replaced — original text must not be recoverable
        assert note.content != "Patient reports severe symptoms"
        assert "removed" in note.content or "deleted" in note.content


def test_clinical_note_original_text_not_in_ciphertext(client, app):
    """The raw ciphertext must not contain the original plaintext."""
    _, cid = _create_clinician(app, "doc_del_cipher")
    pid = _create_user(app, "pat_del_cipher")

    with app.app_context():
        note = ClinicalNote.create(
            patient_id=pid, author_id=cid, content="Confidential medical info XYZ123"
        )
        db.session.add(note)
        db.session.commit()
        note_id = note.id

    _login(client, "pat_del_cipher")
    _delete_account(client)

    with app.app_context():
        note = db.session.get(ClinicalNote, note_id)
        assert "Confidential medical info XYZ123" not in note.content_encrypted
        assert "XYZ123" not in note.content_encrypted


# ---------------------------------------------------------------------------
# Assessment drafts deleted
# ---------------------------------------------------------------------------

def test_assessment_drafts_deleted_after_deletion(client, app):
    pid = _create_user(app, "pat_del_draft")

    with app.app_context():
        from app.utils.scoring import get_or_create_default_template
        template = get_or_create_default_template(db.session)
        draft = AssessmentDraft(
            patient_id=pid,
            template_id=template.id,
            partial_answers_json='{"phq9_q1": "1"}',
        )
        db.session.add(draft)
        db.session.commit()

    _login(client, "pat_del_draft")
    _delete_account(client)

    with app.app_context():
        count = AssessmentDraft.query.filter_by(patient_id=pid).count()
        assert count == 0


# ---------------------------------------------------------------------------
# Assessment results and visits RETAINED for audit
# ---------------------------------------------------------------------------

def test_assessment_results_retained_after_deletion(client, app):
    pid = _create_user(app, "pat_del_ar")

    with app.app_context():
        from app.utils.scoring import get_or_create_default_template
        template = get_or_create_default_template(db.session)
        result = AssessmentResult(
            patient_id=pid,
            template_id=template.id,
            template_version=1,
            answers_json="{}",
            scores_json="{}",
            risk_level="Low",
            explanation_snapshot_json="[]",
        )
        db.session.add(result)
        db.session.commit()
        result_id = result.id

    _login(client, "pat_del_ar")
    _delete_account(client)

    with app.app_context():
        result = db.session.get(AssessmentResult, result_id)
        assert result is not None
        assert result.patient_id == pid  # FK preserved


def test_visits_retained_after_deletion(client, app):
    _, cid = _create_clinician(app, "doc_del_visit")
    pid = _create_user(app, "pat_del_visit")

    with app.app_context():
        visit = Visit(patient_id=pid, clinician_id=cid, status="booked")
        db.session.add(visit)
        db.session.commit()
        visit_id = visit.id

    _login(client, "pat_del_visit")
    _delete_account(client)

    with app.app_context():
        visit = db.session.get(Visit, visit_id)
        assert visit is not None
        assert visit.patient_id == pid  # FK preserved for audit


# ---------------------------------------------------------------------------
# Login attempt username scrubbed
# ---------------------------------------------------------------------------

def test_login_attempt_username_scrubbed(client, app):
    pid = _create_user(app, "pat_del_lat")

    with app.app_context():
        attempt = LoginAttempt(
            username="pat_del_lat",
            ip_address="127.0.0.1",
            success=True,
        )
        db.session.add(attempt)
        db.session.commit()
        attempt_id = attempt.id

    _login(client, "pat_del_lat")
    _delete_account(client)

    with app.app_context():
        attempt = db.session.get(LoginAttempt, attempt_id)
        assert attempt is not None  # record retained
        assert attempt.username is None  # username scrubbed


# ---------------------------------------------------------------------------
# Audit log preserved
# ---------------------------------------------------------------------------

def test_audit_log_not_deleted_after_deletion(client, app):
    """AuditLog entries must survive account deletion (legal hold)."""
    from app.utils.audit import log_action

    pid = _create_user(app, "pat_del_audit")

    with app.app_context():
        # Simulate an existing audit entry for this patient
        entry = AuditLog(
            user_id=pid,
            action="some_action",
            resource_type="user",
            resource_id=str(pid),
        )
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    _login(client, "pat_del_audit")
    _delete_account(client)

    with app.app_context():
        entry = db.session.get(AuditLog, entry_id)
        assert entry is not None
        assert entry.user_id == pid


# ---------------------------------------------------------------------------
# Negative test: old identifier no longer accessible after deletion
# ---------------------------------------------------------------------------

def test_original_username_not_queryable_after_deletion(client, app):
    """The original username must not match any active user after deletion."""
    pid = _create_user(app, "pat_del_noquery")
    _login(client, "pat_del_noquery")
    _delete_account(client)

    with app.app_context():
        # The original username should not exist as an active user
        user = User.query.filter_by(username="pat_del_noquery", is_active=True).first()
        assert user is None
        # The original username should not exist at all
        user = User.query.filter_by(username="pat_del_noquery").first()
        assert user is None
