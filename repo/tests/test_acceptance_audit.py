"""Regression tests for acceptance audit findings.

Covers:
  - Visit authorization (patient cannot transition or view others' timelines)
  - Anti-replay enforcement (missing/replayed nonce rejected)
  - Open redirect prevention on login next parameter
  - Production config requires stable keys
"""

import os
import uuid
import pytest
from datetime import datetime, timezone

from app.models.user import User
from app.models.scheduling import Clinician
from app.models.visit import Visit
from app.extensions import db as _db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nonce_data():
    return {
        "_nonce": str(uuid.uuid4()),
        "_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _create_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        _db.session.add(user)
        _db.session.commit()
        return user.id


def _create_clinician(app, username="doc_audit"):
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        _db.session.add(user)
        _db.session.commit()
        clinician = Clinician(user_id=user.id, specialty="General")
        _db.session.add(clinician)
        _db.session.commit()
        return user.id, clinician.id


def _create_visit(app, patient_id, clinician_id, status="booked"):
    with app.app_context():
        visit = Visit(patient_id=patient_id, clinician_id=clinician_id, status=status)
        _db.session.add(visit)
        _db.session.commit()
        return visit.id


def _login(client, username, password="Password1"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# A) Visit authorization — negative tests
# ---------------------------------------------------------------------------

class TestVisitAuthorization:

    def test_patient_cannot_transition_arbitrary_visit(self, client, app, db):
        """Patient role must be rejected with 403 on visit transition."""
        _, cid = _create_clinician(app, "doc_authz1")
        other_pat_id = _create_user(app, "pat_other1")
        attacker_id = _create_user(app, "pat_attacker1")
        vid = _create_visit(app, other_pat_id, cid)

        _login(client, "pat_attacker1")
        resp = client.post(
            f"/visits/{vid}/transition",
            data={"target_state": "checked_in", **_nonce_data()},
        )
        assert resp.status_code == 403

    def test_patient_cannot_view_other_patient_timeline(self, client, app, db):
        """Patient may not view timeline for a visit that belongs to someone else."""
        _, cid = _create_clinician(app, "doc_authz2")
        owner_id = _create_user(app, "pat_owner2")
        spy_id = _create_user(app, "pat_spy2")
        vid = _create_visit(app, owner_id, cid)

        _login(client, "pat_spy2")
        resp = client.get(f"/visits/{vid}/timeline")
        assert resp.status_code == 403

    def test_patient_can_view_own_timeline(self, client, app, db):
        """Patient may view timeline for their own visit."""
        _, cid = _create_clinician(app, "doc_authz3")
        pat_id = _create_user(app, "pat_own3")
        vid = _create_visit(app, pat_id, cid)

        _login(client, "pat_own3")
        resp = client.get(f"/visits/{vid}/timeline")
        assert resp.status_code == 200

    def test_staff_can_transition_visit(self, client, app, db):
        """Staff role should succeed on transition when valid nonce provided."""
        _, cid = _create_clinician(app, "doc_authz4")
        pat_id = _create_user(app, "pat_authz4")
        admin_id = _create_user(app, "admin_authz4", role="administrator")
        vid = _create_visit(app, pat_id, cid)

        _login(client, "admin_authz4")
        resp = client.post(
            f"/visits/{vid}/transition",
            data={"target_state": "checked_in", **_nonce_data()},
            follow_redirects=True,
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# B) Anti-replay tests
# ---------------------------------------------------------------------------

class TestAntiReplay:

    def test_missing_nonce_rejected_on_visit_transition(self, client, app, db):
        """Transition without nonce/timestamp must return 400."""
        _, cid = _create_clinician(app, "doc_ar1")
        pat_id = _create_user(app, "pat_ar1")
        admin_id = _create_user(app, "admin_ar1", role="administrator")
        vid = _create_visit(app, pat_id, cid)

        _login(client, "admin_ar1")
        resp = client.post(
            f"/visits/{vid}/transition",
            data={"target_state": "checked_in"},
        )
        assert resp.status_code == 400

    def test_missing_nonce_rejected_on_schedule_hold(self, client, app, db):
        """Hold without nonce/timestamp must return 400."""
        from app.models.scheduling import Slot
        from datetime import date, time, timedelta

        _, cid = _create_clinician(app, "doc_ar2")
        pat_id = _create_user(app, "pat_ar2")

        with app.app_context():
            slot = Slot(
                clinician_id=cid,
                date=date.today() + timedelta(days=1),
                start_time=time(9, 0),
                end_time=time(9, 15),
                capacity=1,
            )
            _db.session.add(slot)
            _db.session.commit()
            sid = slot.id

        _login(client, "pat_ar2")
        resp = client.post(f"/schedule/hold/{sid}")
        assert resp.status_code == 400

    def test_missing_nonce_rejected_on_delete_account(self, client, app, db):
        """Account deletion without nonce/timestamp must return 400."""
        _create_user(app, "pat_ar3")
        _login(client, "pat_ar3")
        resp = client.post("/patient/delete-account", data={"password": "Password1"})
        assert resp.status_code == 400

    def test_replayed_nonce_rejected(self, client, app, db):
        """Reusing the same nonce on two requests must return 409 on the second."""
        _, cid = _create_clinician(app, "doc_ar4")
        pat_id = _create_user(app, "pat_ar4")
        admin_id = _create_user(app, "admin_ar4", role="administrator")
        vid = _create_visit(app, pat_id, cid)

        _login(client, "admin_ar4")
        nonce_payload = _nonce_data()

        # First request — should succeed
        resp1 = client.post(
            f"/visits/{vid}/transition",
            data={"target_state": "checked_in", **nonce_payload},
            follow_redirects=False,
        )
        assert resp1.status_code != 409

        # Replay the same nonce — second visit in state checked_in -> seen
        # (we need a visit still in a transitionable state for the replay to be
        # meaningful, but the important thing is the 409 nonce check fires first)
        vid2 = _create_visit(app, pat_id, cid)
        resp2 = client.post(
            f"/visits/{vid2}/transition",
            data={"target_state": "checked_in", **nonce_payload},
        )
        assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# C) Open redirect tests
# ---------------------------------------------------------------------------

class TestOpenRedirect:

    def _register_and_login_user(self, client, app, username):
        """Register a fresh user and return a logged-in client."""
        _create_user(app, username)

    def test_external_next_rejected(self, client, app, db):
        """Login with external next URL must NOT redirect to that URL."""
        _create_user(app, "pat_redir1")
        resp = client.post(
            "/auth/login?next=http://evil.example.com/steal",
            data={"username": "pat_redir1", "password": "Password1"},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 200)
        location = resp.headers.get("Location", "")
        assert "evil.example.com" not in location

    def test_external_next_with_double_slash_rejected(self, client, app, db):
        """Protocol-relative URL (//evil.example.com) must also be blocked."""
        _create_user(app, "pat_redir2")
        resp = client.post(
            "/auth/login?next=//evil.example.com/steal",
            data={"username": "pat_redir2", "password": "Password2Aa"},
            follow_redirects=False,
        )
        # If login fails due to password, re-do with correct password
        _create_user(app, "pat_redir2b")
        resp = client.post(
            "/auth/login?next=//evil.example.com/steal",
            data={"username": "pat_redir2b", "password": "Password1"},
            follow_redirects=False,
        )
        location = resp.headers.get("Location", "")
        assert "evil.example.com" not in location

    def test_relative_internal_next_allowed(self, client, app, db):
        """A safe relative path in next must be honoured after login."""
        _create_user(app, "pat_redir3")
        resp = client.post(
            "/auth/login?next=/patient/demographics",
            data={"username": "pat_redir3", "password": "Password1"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert "/patient/demographics" in location

    def test_htmx_login_external_next_rejected(self, client, app, db):
        """HTMX login path: external next must not appear in HX-Redirect header."""
        _create_user(app, "pat_redir4")
        resp = client.post(
            "/auth/login?next=https://evil.example.com/",
            data={"username": "pat_redir4", "password": "Password1"},
            headers={"HX-Request": "true"},
        )
        hx_redirect = resp.headers.get("HX-Redirect", "")
        assert "evil.example.com" not in hx_redirect


# ---------------------------------------------------------------------------
# D) Production config tests
# ---------------------------------------------------------------------------

class TestProductionConfig:

    def test_production_fails_without_secret_key(self):
        """create_app('production') raises RuntimeError when SECRET_KEY is absent."""
        from app import create_app

        env_backup = {}
        for key in ("SECRET_KEY", "ENCRYPTION_KEY"):
            env_backup[key] = os.environ.pop(key, None)

        try:
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                create_app("production")
        finally:
            for key, val in env_backup.items():
                if val is not None:
                    os.environ[key] = val

    def test_production_fails_without_encryption_key(self):
        """create_app('production') raises RuntimeError when ENCRYPTION_KEY is absent."""
        from app import create_app
        from cryptography.fernet import Fernet

        env_backup = {}
        for key in ("SECRET_KEY", "ENCRYPTION_KEY"):
            env_backup[key] = os.environ.pop(key, None)

        os.environ["SECRET_KEY"] = "stable-test-secret-key-x1234567890"
        try:
            with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
                create_app("production")
        finally:
            os.environ.pop("SECRET_KEY", None)
            for key, val in env_backup.items():
                if val is not None:
                    os.environ[key] = val

    def test_production_succeeds_with_both_keys(self):
        """create_app('production') succeeds when both keys are supplied."""
        from app import create_app
        from cryptography.fernet import Fernet

        env_backup = {}
        for key in ("SECRET_KEY", "ENCRYPTION_KEY"):
            env_backup[key] = os.environ.pop(key, None)

        os.environ["SECRET_KEY"] = "stable-test-secret-key-x1234567890"
        os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        try:
            app = create_app("production")
            assert app is not None
        finally:
            os.environ.pop("SECRET_KEY", None)
            os.environ.pop("ENCRYPTION_KEY", None)
            for key, val in env_backup.items():
                if val is not None:
                    os.environ[key] = val
