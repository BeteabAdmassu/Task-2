"""Tests for on-behalf workflows and notes object-level validation.

Covers:
  A) Notes: staff cannot create/read notes for non-patient targets.
  B) On-behalf assessments: front_desk/admin can submit for a patient;
     result.patient_id == patient; unauthorized roles rejected; invalid targets rejected.
  C) On-behalf scheduling: front_desk/admin can hold+confirm for a patient;
     reservation.patient_id == patient; unauthorized roles rejected; invalid targets rejected.
  D) Regression: existing self-service paths unchanged.
"""

import pytest
from datetime import date, time, timedelta, datetime, timezone
from app.models.user import User
from app.models.assessment import AssessmentResult, AssessmentDraft
from app.models.scheduling import Clinician, Slot, Reservation
from app.models.audit import AuditLog
from app.extensions import db
from tests.signing_helpers import signed_data, login_data


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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
        data=login_data(username, password),
        follow_redirects=True,
    )


def _logout(client):
    return client.post("/auth/logout", follow_redirects=True)


def _create_clinician_with_slot(app, username):
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        c = Clinician(user_id=user.id)
        db.session.add(c)
        db.session.commit()
        slot = Slot(
            clinician_id=c.id,
            date=date.today() + timedelta(days=3),
            start_time=time(10, 0),
            end_time=time(10, 30),
            capacity=5,
            status="available",
        )
        db.session.add(slot)
        db.session.commit()
        return c.id, slot.id


LOW_RISK_ANSWERS = {
    **{f"phq9_q{i}": "0" for i in range(1, 10)},
    **{f"gad7_q{i}": "0" for i in range(1, 8)},
    "bp_category": "Normal",
    "fall_history": "no", "mobility_aids": "no", "dizziness": "no", "balance_meds": "no",
    "med_adherence": "never_miss",
}


def _behalf_submit_assessment(client, patient_id, token):
    """Walk a full behalf assessment wizard and submit."""
    client.get(f"/assessments/behalf/{patient_id}/start")
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = token
    for step in range(1, 6):
        client.post(f"/assessments/behalf/{patient_id}/step/{step}", data=all_data)
    path = f"/assessments/behalf/{patient_id}/submit"
    return client.post(
        path,
        data=signed_data("POST", path, {"request_token": token}),
        follow_redirects=True,
    )


# ===========================================================================
# A) Notes object-level validation
# ===========================================================================

def test_notes_rejects_non_patient_target(client, app):
    """Staff must get an error when trying to view/create notes for a non-patient user."""
    _create_user(app, "ob_notes_staff", role="front_desk")
    clinician_id = _create_user(app, "ob_notes_clinician", role="clinician")

    _login(client, "ob_notes_staff")
    path = f"/notes/patient/{clinician_id}"
    # GET request — should redirect away (not render notes)
    resp = client.get(path, follow_redirects=True)
    assert resp.status_code == 200
    assert b"not a patient" in resp.data.lower() or b"patient not found" in resp.data.lower() or b"patient list" in resp.data.lower()


def test_notes_rejects_non_patient_target_post(client, app):
    """POST to notes for a non-patient target must be rejected."""
    _create_user(app, "ob_notes_staff2", role="administrator")
    fd_id = _create_user(app, "ob_notes_fd_target", role="front_desk")

    _login(client, "ob_notes_staff2")
    path = f"/notes/patient/{fd_id}"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"content": "some note"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # No note should have been created
    with app.app_context():
        from app.models.clinical_note import ClinicalNote
        notes = ClinicalNote.query.filter_by(patient_id=fd_id).all()
        assert len(notes) == 0


def test_notes_accepts_patient_target(client, app):
    """Staff can create notes for a patient-role user — sanity check."""
    _create_user(app, "ob_notes_staff3", role="clinician")
    patient_id = _create_user(app, "ob_notes_patient3", role="patient")

    _login(client, "ob_notes_staff3")
    path = f"/notes/patient/{patient_id}"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"content": "Routine checkup note"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        from app.models.clinical_note import ClinicalNote
        notes = ClinicalNote.query.filter_by(patient_id=patient_id).all()
        assert len(notes) == 1


# ===========================================================================
# B) On-behalf assessments
# ===========================================================================

def test_front_desk_can_submit_behalf_assessment(client, app):
    """front_desk can complete and submit an assessment for a patient."""
    _create_user(app, "ob_fd_staff", role="front_desk")
    patient_id = _create_user(app, "ob_fd_patient")

    _login(client, "ob_fd_staff")
    resp = _behalf_submit_assessment(client, patient_id, "behalf-tok-fd")
    assert resp.status_code == 200


def test_admin_can_submit_behalf_assessment(client, app):
    """administrator can complete and submit an assessment for a patient."""
    _create_user(app, "ob_admin_staff", role="administrator")
    patient_id = _create_user(app, "ob_admin_patient")

    _login(client, "ob_admin_staff")
    resp = _behalf_submit_assessment(client, patient_id, "behalf-tok-admin")
    assert resp.status_code == 200


def test_behalf_assessment_result_owned_by_patient(client, app):
    """AssessmentResult.patient_id must equal the target patient, not the staff user."""
    staff_id = _create_user(app, "ob_own_staff", role="front_desk")
    patient_id = _create_user(app, "ob_own_patient")

    _login(client, "ob_own_staff")
    _behalf_submit_assessment(client, patient_id, "behalf-tok-own")

    with app.app_context():
        result = AssessmentResult.query.filter_by(patient_id=patient_id).first()
        assert result is not None, "AssessmentResult was not created"
        assert result.patient_id == patient_id
        assert result.patient_id != staff_id


def test_behalf_assessment_audit_log_created(client, app):
    """An audit log entry must be written for on-behalf assessment submission."""
    _create_user(app, "ob_audit_staff", role="front_desk")
    patient_id = _create_user(app, "ob_audit_patient")

    _login(client, "ob_audit_staff")
    _behalf_submit_assessment(client, patient_id, "behalf-tok-audit")

    with app.app_context():
        entry = AuditLog.query.filter_by(action="on_behalf_assessment").first()
        assert entry is not None
        import json
        details = json.loads(entry.details_json)
        assert details["patient_id"] == patient_id


def test_behalf_assessment_idempotency(client, app):
    """Double-submit with the same token must not create a duplicate result."""
    _create_user(app, "ob_idem_staff", role="front_desk")
    patient_id = _create_user(app, "ob_idem_patient")

    _login(client, "ob_idem_staff")
    # First submission — creates draft and result
    _behalf_submit_assessment(client, patient_id, "behalf-tok-idem")
    # Second submission — same token, should be idempotent
    # Need to restart wizard so a fresh draft exists
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "behalf-tok-idem"
    for step in range(1, 6):
        client.post(f"/assessments/behalf/{patient_id}/step/{step}", data=all_data)
    path = f"/assessments/behalf/{patient_id}/submit"
    client.post(path, data=signed_data("POST", path, {"request_token": "behalf-tok-idem"}), follow_redirects=True)

    with app.app_context():
        import hashlib
        token_hash = hashlib.sha256("behalf-tok-idem".encode()).hexdigest()
        count = AssessmentResult.query.filter_by(request_token=token_hash).count()
        assert count == 1


def test_unauthorized_role_cannot_use_behalf_assessment(client, app):
    """A clinician (not front_desk or admin) must be denied access to behalf routes."""
    _create_user(app, "ob_deny_clin", role="clinician")
    patient_id = _create_user(app, "ob_deny_patient")

    _login(client, "ob_deny_clin")
    resp = client.get(f"/assessments/behalf/{patient_id}/start", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_patient_cannot_use_behalf_assessment(client, app):
    """A patient must be denied access to behalf assessment routes."""
    _create_user(app, "ob_pat_self")
    patient_id = _create_user(app, "ob_pat_target")

    _login(client, "ob_pat_self")
    resp = client.get(f"/assessments/behalf/{patient_id}/start", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_behalf_assessment_rejects_nonexistent_patient(client, app):
    """behalf_start must redirect/error when patient_id does not exist."""
    _create_user(app, "ob_noexist_staff", role="front_desk")

    _login(client, "ob_noexist_staff")
    resp = client.get("/assessments/behalf/99999/start", follow_redirects=True)
    assert resp.status_code == 200
    assert b"not found" in resp.data.lower() or b"patient" in resp.data.lower()


def test_behalf_assessment_rejects_non_patient_target(client, app):
    """behalf routes must reject targets who are not patient-role users."""
    _create_user(app, "ob_nonpat_staff", role="front_desk")
    admin_id = _create_user(app, "ob_nonpat_admin_target", role="administrator")

    _login(client, "ob_nonpat_staff")
    resp = client.get(f"/assessments/behalf/{admin_id}/start", follow_redirects=True)
    assert resp.status_code == 200
    assert b"not a patient" in resp.data.lower()


# ===========================================================================
# C) On-behalf scheduling
# ===========================================================================

def test_front_desk_can_hold_slot_for_patient(client, app):
    """front_desk can create a hold on behalf of a patient."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc1")
    _create_user(app, "ob_sched_fd1", role="front_desk")
    patient_id = _create_user(app, "ob_sched_pat1")

    _login(client, "ob_sched_fd1")
    path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(path, data=signed_data("POST", path), follow_redirects=False)
    # Should redirect to behalf confirm page
    assert resp.status_code == 302


def test_behalf_hold_reservation_owned_by_patient(client, app):
    """Reservation.patient_id must equal the target patient, not the staff user."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc2")
    staff_id = _create_user(app, "ob_sched_fd2", role="front_desk")
    patient_id = _create_user(app, "ob_sched_pat2")

    _login(client, "ob_sched_fd2")
    path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    client.post(path, data=signed_data("POST", path), follow_redirects=False)

    with app.app_context():
        res = Reservation.query.filter_by(patient_id=patient_id).first()
        assert res is not None, "Reservation was not created"
        assert res.patient_id == patient_id
        assert res.patient_id != staff_id


def test_behalf_hold_audit_log_created(client, app):
    """An audit log entry must be written for on-behalf hold."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc3")
    _create_user(app, "ob_sched_fd3", role="front_desk")
    patient_id = _create_user(app, "ob_sched_pat3")

    _login(client, "ob_sched_fd3")
    path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    client.post(path, data=signed_data("POST", path), follow_redirects=False)

    with app.app_context():
        entry = AuditLog.query.filter_by(action="on_behalf_hold").first()
        assert entry is not None
        import json
        details = json.loads(entry.details_json)
        assert details["patient_id"] == patient_id
        assert details["slot_id"] == slot_id


def test_behalf_confirm_completes_booking(client, app):
    """Staff can confirm a held reservation on behalf of a patient."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc4")
    _create_user(app, "ob_sched_fd4", role="front_desk")
    patient_id = _create_user(app, "ob_sched_pat4")

    _login(client, "ob_sched_fd4")

    # Hold
    hold_path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(hold_path, data=signed_data("POST", hold_path), follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert f"/behalf/{patient_id}/confirm/" in location

    # Extract reservation id from redirect
    res_id = int(location.rstrip("/").split("/")[-1])

    # Confirm
    confirm_path = f"/schedule/behalf/{patient_id}/confirm/{res_id}"
    resp = client.post(confirm_path, data=signed_data("POST", confirm_path), follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == "confirmed"
        assert res.patient_id == patient_id


def test_behalf_confirm_audit_log_created(client, app):
    """An audit log entry must be written for on-behalf confirm."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc5")
    _create_user(app, "ob_sched_fd5", role="front_desk")
    patient_id = _create_user(app, "ob_sched_pat5")

    _login(client, "ob_sched_fd5")

    hold_path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(hold_path, data=signed_data("POST", hold_path), follow_redirects=False)
    res_id = int(resp.headers["Location"].rstrip("/").split("/")[-1])

    confirm_path = f"/schedule/behalf/{patient_id}/confirm/{res_id}"
    client.post(confirm_path, data=signed_data("POST", confirm_path), follow_redirects=True)

    with app.app_context():
        entry = AuditLog.query.filter_by(action="on_behalf_confirm").first()
        assert entry is not None
        import json
        details = json.loads(entry.details_json)
        assert details["patient_id"] == patient_id


def test_behalf_confirm_page_get(client, app):
    """GET on behalf confirm page renders the slot details."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc6")
    _create_user(app, "ob_sched_fd6", role="front_desk")
    patient_id = _create_user(app, "ob_sched_pat6")

    _login(client, "ob_sched_fd6")
    hold_path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(hold_path, data=signed_data("POST", hold_path), follow_redirects=False)
    res_id = int(resp.headers["Location"].rstrip("/").split("/")[-1])

    resp = client.get(f"/schedule/behalf/{patient_id}/confirm/{res_id}")
    assert resp.status_code == 200
    with app.app_context():
        pat = db.session.get(User, patient_id)
        assert pat.username.encode() in resp.data


def test_behalf_schedule_rejects_nonexistent_patient(client, app):
    """behalf hold must reject a patient_id that does not exist."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc7")
    _create_user(app, "ob_sched_fd7", role="front_desk")

    _login(client, "ob_sched_fd7")
    path = f"/schedule/behalf/99999/hold/{slot_id}"
    resp = client.post(path, data=signed_data("POST", path), follow_redirects=True)
    assert resp.status_code == 200
    assert b"not found" in resp.data.lower()


def test_behalf_schedule_rejects_non_patient_target(client, app):
    """behalf hold must reject targets who are not patient-role users."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc8")
    _create_user(app, "ob_sched_fd8", role="front_desk")
    non_patient_id = _create_user(app, "ob_sched_nonpat8", role="clinician")

    _login(client, "ob_sched_fd8")
    path = f"/schedule/behalf/{non_patient_id}/hold/{slot_id}"
    resp = client.post(path, data=signed_data("POST", path), follow_redirects=True)
    assert resp.status_code == 200
    assert b"not a patient" in resp.data.lower()


def test_unauthorized_role_cannot_behalf_hold(client, app):
    """A clinician must be denied access to behalf scheduling routes."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc9")
    _create_user(app, "ob_sched_clin9", role="clinician")
    patient_id = _create_user(app, "ob_sched_pat9")

    _login(client, "ob_sched_clin9")
    path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(path, data=signed_data("POST", path), follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_patient_cannot_behalf_hold(client, app):
    """A patient must be denied access to behalf scheduling routes."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc10")
    _create_user(app, "ob_sched_pat10a")
    patient_id = _create_user(app, "ob_sched_pat10b")

    _login(client, "ob_sched_pat10a")
    path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(path, data=signed_data("POST", path), follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_admin_can_behalf_hold_and_confirm(client, app):
    """administrator role can also use behalf scheduling routes."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_sched_doc11")
    _create_user(app, "ob_sched_admin11", role="administrator")
    patient_id = _create_user(app, "ob_sched_pat11")

    _login(client, "ob_sched_admin11")
    hold_path = f"/schedule/behalf/{patient_id}/hold/{slot_id}"
    resp = client.post(hold_path, data=signed_data("POST", hold_path), follow_redirects=False)
    assert resp.status_code == 302

    res_id = int(resp.headers["Location"].rstrip("/").split("/")[-1])
    confirm_path = f"/schedule/behalf/{patient_id}/confirm/{res_id}"
    resp = client.post(confirm_path, data=signed_data("POST", confirm_path), follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == "confirmed"
        assert res.patient_id == patient_id


# ===========================================================================
# D) Regression: self-service paths unchanged
# ===========================================================================

def test_patient_self_assessment_unaffected(client, app):
    """Regular patient-initiated assessment still works after on-behalf additions."""
    _create_user(app, "ob_reg_patient")
    _login(client, "ob_reg_patient")
    client.get("/assessments/start")

    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "ob-reg-tok"
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)

    path = "/assessments/submit"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"request_token": "ob-reg-tok"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        patient = User.query.filter_by(username="ob_reg_patient").first()
        results = AssessmentResult.query.filter_by(patient_id=patient.id).all()
        assert len(results) == 1
        assert results[0].risk_level == "Low"


def test_patient_self_booking_unaffected(client, app):
    """Regular patient-initiated hold still works after on-behalf additions."""
    cid, slot_id = _create_clinician_with_slot(app, "ob_reg_doc")
    _create_user(app, "ob_reg_pat")

    _login(client, "ob_reg_pat")
    path = f"/schedule/hold/{slot_id}"
    resp = client.post(path, data=signed_data("POST", path), follow_redirects=False)
    assert resp.status_code == 302
    assert "/confirm/" in resp.headers.get("Location", "")

    with app.app_context():
        patient = User.query.filter_by(username="ob_reg_pat").first()
        res = Reservation.query.filter_by(patient_id=patient.id).first()
        assert res is not None
        assert res.status == "held"
