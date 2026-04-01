"""Tests for prompt 07 — Visit State Machine & Dashboard."""

import uuid
import pytest
from datetime import date, time, timedelta, datetime, timezone
from app.models.user import User
from app.models.scheduling import Clinician, Slot
from app.models.visit import Visit, VisitTransition
from app.utils.state_machine import transition_visit, VALID_TRANSITIONS, TERMINAL_STATES
from app.extensions import db


def _nonce_data():
    return {
        "_nonce": str(uuid.uuid4()),
        "_timestamp": datetime.now(timezone.utc).isoformat(),
    }


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


def _create_visit(app, patient_id, clinician_id, status="booked"):
    with app.app_context():
        visit = Visit(patient_id=patient_id, clinician_id=clinician_id, status=status)
        db.session.add(visit)
        db.session.commit()
        return visit.id


def _create_clinician(app, username="doc_v"):
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id, specialty="General")
        db.session.add(clinician)
        db.session.commit()
        return user.id, clinician.id


def test_valid_transition_booked_to_checked_in(app, db):
    uid, cid = _create_clinician(app, "doc_t1")
    pat_id = _create_user(app, "pat_t1")
    vid = _create_visit(app, pat_id, cid)
    with app.app_context():
        visit = db.session.get(Visit, vid)
        t = transition_visit(visit, "checked_in", uid)
        assert t.from_status == "booked"
        assert t.to_status == "checked_in"
        assert visit.status == "checked_in"


def test_invalid_transition_raises(app, db):
    uid, cid = _create_clinician(app, "doc_t2")
    pat_id = _create_user(app, "pat_t2")
    vid = _create_visit(app, pat_id, cid)
    with app.app_context():
        visit = db.session.get(Visit, vid)
        with pytest.raises(ValueError, match="Invalid transition"):
            transition_visit(visit, "seen", uid)


def test_terminal_state_no_transition(app, db):
    uid, cid = _create_clinician(app, "doc_t3")
    pat_id = _create_user(app, "pat_t3")
    vid = _create_visit(app, pat_id, cid, status="canceled")
    with app.app_context():
        visit = db.session.get(Visit, vid)
        with pytest.raises(ValueError, match="terminal state"):
            transition_visit(visit, "booked", uid)


def test_transition_with_request_token_idempotent(app, db):
    uid, cid = _create_clinician(app, "doc_t4")
    pat_id = _create_user(app, "pat_t4")
    vid = _create_visit(app, pat_id, cid)
    with app.app_context():
        visit = db.session.get(Visit, vid)
        t1 = transition_visit(visit, "checked_in", uid, request_token="tok123")
        assert t1.from_status == "booked"
        # Second call with same token returns the cached transition
        t2 = transition_visit(visit, "seen", uid, request_token="tok123")
        assert t1.id == t2.id
        # Visit should still be checked_in (second transition was idempotent/skipped)
        assert visit.status == "checked_in"


def test_dashboard_requires_auth(client, app, db):
    resp = client.get("/visits/dashboard")
    assert resp.status_code in (302, 401)


def test_dashboard_accessible_by_admin(client, app, db):
    _create_user(app, "admin_v1", role="administrator")
    _login(client, "admin_v1")
    resp = client.get("/visits/dashboard")
    assert resp.status_code == 200
    assert b"Visit Dashboard" in resp.data


def test_transition_endpoint(client, app, db):
    uid, cid = _create_clinician(app, "doc_t6")
    _create_user(app, "admin_v2", role="administrator")
    pat_id = _create_user(app, "pat_t6")
    vid = _create_visit(app, pat_id, cid)
    _login(client, "admin_v2")
    resp = client.post(
        f"/visits/{vid}/transition",
        data={"target_state": "checked_in", **_nonce_data()},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_timeline_endpoint(client, app, db):
    uid, cid = _create_clinician(app, "doc_t7")
    _create_user(app, "admin_v3", role="administrator")
    pat_id = _create_user(app, "pat_t7")
    vid = _create_visit(app, pat_id, cid)
    _login(client, "admin_v3")
    resp = client.get(f"/visits/{vid}/timeline")
    assert resp.status_code == 200


def test_dashboard_poll_endpoint(client, app, db):
    _create_user(app, "admin_v4", role="administrator")
    _login(client, "admin_v4")
    resp = client.get("/visits/dashboard/poll")
    assert resp.status_code == 200


def test_transition_chain(app, db):
    """Test a full transition chain: booked -> checked_in -> seen."""
    uid, cid = _create_clinician(app, "doc_t8")
    pat_id = _create_user(app, "pat_t8")
    vid = _create_visit(app, pat_id, cid)
    with app.app_context():
        visit = db.session.get(Visit, vid)
        transition_visit(visit, "checked_in", uid)
        transition_visit(visit, "seen", uid)
        assert visit.status == "seen"
        transitions = VisitTransition.query.filter_by(visit_id=vid).all()
        assert len(transitions) == 2
