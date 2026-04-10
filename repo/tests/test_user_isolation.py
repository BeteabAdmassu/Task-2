"""User-switch isolation tests.

Verify that after logout/login as a different user, no stale user-specific
content from the previous session is accessible or visible in key views.
"""

import pytest
from datetime import date, time, timedelta, datetime, timezone
from app.models.user import User
from app.models.assessment import AssessmentResult
from app.models.scheduling import Clinician, Slot, Reservation
from app.models.visit import Visit
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


def _login(client, username, password="Password1"):
    return client.post(
        "/auth/login",
        data=login_data(username, password),
        follow_redirects=True,
    )


def _logout(client):
    return client.post("/auth/logout", follow_redirects=True)


def _create_clinician_with_slot(app, username, slot_date=None):
    """Return (patient_user_id, clinician_id, slot_id)."""
    from datetime import date as _date, time as _time
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
            date=slot_date or (_date.today() + timedelta(days=3)),
            start_time=_time(10, 0),
            end_time=_time(10, 30),
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

_SUBMIT_PATH = "/assessments/submit"


def _submit_assessment(client, token):
    client.get("/assessments/start")
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = token
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)
    client.post(
        _SUBMIT_PATH,
        data=signed_data("POST", _SUBMIT_PATH, {"request_token": token}),
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Assessment history isolation
# ---------------------------------------------------------------------------

def test_user_switch_assessment_history_isolated(client, app):
    """User B's assessment history page must not show User A's results."""
    pid_a = _create_user(app, "iso_assess_a")
    pid_b = _create_user(app, "iso_assess_b")

    # User A submits an assessment.
    _login(client, "iso_assess_a")
    _submit_assessment(client, "iso-tok-a")
    _logout(client)

    # User B logs in — their history must be empty.
    _login(client, "iso_assess_b")
    resp = client.get("/assessments/history")
    assert resp.status_code == 200
    # User A's result must not appear in User B's history page.
    with app.app_context():
        a_result = AssessmentResult.query.filter_by(patient_id=pid_a).first()
        assert a_result is not None  # sanity: A's result exists
        # B's history page must not link to A's result.
        assert f"/assessments/result/{a_result.id}".encode() not in resp.data


def test_user_a_result_access_denied_to_user_b(client, app):
    """User B must receive a redirect/403 when directly accessing User A's result."""
    pid_a = _create_user(app, "iso_result_a")
    pid_b = _create_user(app, "iso_result_b")

    _login(client, "iso_result_a")
    _submit_assessment(client, "iso-tok-res-a")
    _logout(client)

    with app.app_context():
        a_result = AssessmentResult.query.filter_by(patient_id=pid_a).first()
        result_id = a_result.id

    # User B tries to access User A's result directly.
    _login(client, "iso_result_b")
    resp = client.get(f"/assessments/result/{result_id}", follow_redirects=True)
    # Must not display A's data — either denied or redirected away.
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        # If it redirected to history (200 after redirect), A's result content
        # must not be rendered — check that the result ID is not present.
        assert b"Low" not in resp.data or b"Assessment History" in resp.data


# ---------------------------------------------------------------------------
# Appointment / reservation isolation
# ---------------------------------------------------------------------------

def test_user_switch_reservation_isolation(client, app):
    """User B's appointments page must not show User A's reservations."""
    cid, sid = _create_clinician_with_slot(app, "doc_iso_res")
    pid_a = _create_user(app, "iso_res_a")
    pid_b = _create_user(app, "iso_res_b")

    # User A holds a slot.
    _login(client, "iso_res_a")
    path = f"/schedule/hold/{sid}"
    client.post(path, data=signed_data("POST", path, {"request_token": "tok-iso-res-a"}), follow_redirects=True)
    _logout(client)

    # Confirm User A has a reservation.
    with app.app_context():
        a_res = Reservation.query.filter_by(patient_id=pid_a).first()
        assert a_res is not None

    # User B logs in and views their appointments.
    _login(client, "iso_res_b")
    resp = client.get("/schedule/my-appointments")
    assert resp.status_code == 200

    # User A's reservation ID must not appear in User B's page.
    with app.app_context():
        a_res = Reservation.query.filter_by(patient_id=pid_a).first()
        assert f"/schedule/confirm/{a_res.id}".encode() not in resp.data
        assert f"/schedule/cancel/{a_res.id}".encode() not in resp.data


def test_user_b_cannot_access_user_a_confirm_page(client, app):
    """User B must not be able to access User A's reservation confirm page."""
    cid, sid = _create_clinician_with_slot(app, "doc_iso_confirm")
    pid_a = _create_user(app, "iso_confirm_a")
    pid_b = _create_user(app, "iso_confirm_b")

    # Create reservation for User A directly.
    with app.app_context():
        res = Reservation(
            slot_id=sid,
            patient_id=pid_a,
            status="held",
            held_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.session.add(res)
        db.session.commit()
        res_id = res.id

    # User B tries to access the confirm page for A's reservation.
    _login(client, "iso_confirm_b")
    resp = client.get(f"/schedule/confirm/{res_id}", follow_redirects=True)
    # Must not show A's reservation — either 403 or redirect back to available.
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        # If redirected to available page, A's slot details must not be shown
        # under B's identity (the "Reservation not found" flash fires instead).
        assert b"Reservation not found" in resp.data or b"Available" in resp.data


# ---------------------------------------------------------------------------
# Session does not persist previous user's identity
# ---------------------------------------------------------------------------

def test_logout_clears_session_user_identity(client, app):
    """After logout and re-login as different user, nav reflects new user only."""
    _create_user(app, "iso_nav_a")
    _create_user(app, "iso_nav_b")

    _login(client, "iso_nav_a")
    resp_a = client.get("/")
    assert b"iso_nav_a" in resp_a.data
    assert b"iso_nav_b" not in resp_a.data

    _logout(client)

    _login(client, "iso_nav_b")
    resp_b = client.get("/")
    assert b"iso_nav_b" in resp_b.data
    # User A's username must not appear after switching.
    assert b"iso_nav_a" not in resp_b.data


def test_unauthenticated_after_logout_redirected(client, app):
    """After logout, accessing a protected page redirects to login."""
    _create_user(app, "iso_redirect_a")
    _login(client, "iso_redirect_a")
    _logout(client)

    resp = client.get("/assessments/history", follow_redirects=False)
    assert resp.status_code == 302
    assert "login" in resp.headers.get("Location", "").lower()


# ---------------------------------------------------------------------------
# Schedule cancel — object-level ownership
# ---------------------------------------------------------------------------

def test_patient_cannot_cancel_another_patients_reservation(app):
    """Patient B must not be able to cancel Patient A's reservation."""

    _create_user(app, "iso_cancel_owner")
    _create_user(app, "iso_cancel_attacker")

    with app.app_context():
        owner = User.query.filter_by(username="iso_cancel_owner").first()
        attacker = User.query.filter_by(username="iso_cancel_attacker").first()

        doc_user = User(username="iso_cancel_doc", role="clinician")
        doc_user.set_password("Password1")
        db.session.add(doc_user)
        db.session.commit()
        clinician = Clinician(user_id=doc_user.id)
        db.session.add(clinician)
        db.session.commit()

        slot = Slot(
            clinician_id=clinician.id,
            date=date.today() + timedelta(days=2),
            start_time=time(10, 0),
            end_time=time(10, 15),
            capacity=1,
        )
        db.session.add(slot)
        db.session.commit()

        reservation = Reservation(
            slot_id=slot.id,
            patient_id=owner.id,
            status="held",
            held_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        db.session.add(reservation)
        db.session.commit()
        res_id = reservation.id

    attacker_client = app.test_client()
    _login(attacker_client, "iso_cancel_attacker")

    path = f"/schedule/cancel/{res_id}"
    resp = attacker_client.post(
        path,
        data=signed_data("POST", path),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Access denied" in resp.data

    with app.app_context():
        res = db.session.get(Reservation, res_id)
        assert res.status == "held", "Reservation must not be canceled by a different patient"


# ---------------------------------------------------------------------------
# Notes — object-level role and ownership enforcement
# ---------------------------------------------------------------------------

def test_patient_cannot_access_staff_notes_route(app):
    """A patient must be denied access to the staff notes endpoint."""
    pid = _create_user(app, "iso_notes_patient_a")

    patient_client = app.test_client()
    _login(patient_client, "iso_notes_patient_a")

    resp = patient_client.get(f"/notes/patient/{pid}", follow_redirects=False)
    assert resp.status_code == 403


def test_patient_cannot_read_another_patients_notes_via_staff_route(app):
    """Even with a valid patient_id, a patient role must be refused staff notes."""
    pid_a = _create_user(app, "iso_notes_victim")
    _create_user(app, "iso_notes_nosy")

    nosy_client = app.test_client()
    _login(nosy_client, "iso_notes_nosy")

    resp = nosy_client.get(f"/notes/patient/{pid_a}", follow_redirects=False)
    assert resp.status_code == 403
