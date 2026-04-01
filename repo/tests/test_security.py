"""Tests for prompt 10 — Security & Privacy."""

import pytest
from app.models.user import User
from app.extensions import db
from tests.signing_helpers import signed_data


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


def test_security_headers_present(client, app, db):
    resp = client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "max-age" in resp.headers.get("Strict-Transport-Security", "")
    assert "default-src" in resp.headers.get("Content-Security-Policy", "")


def test_correlation_id_header(client, app, db):
    resp = client.get("/health")
    assert "X-Correlation-ID" in resp.headers


def test_change_password_page(client, app, db):
    _create_user(app, "pat_sec1")
    _login(client, "pat_sec1")
    resp = client.get("/auth/change-password")
    assert resp.status_code == 200
    assert b"Change Password" in resp.data


def test_change_password_success(client, app, db):
    _create_user(app, "pat_sec2")
    _login(client, "pat_sec2")
    resp = client.post(
        "/auth/change-password",
        data=signed_data("POST", "/auth/change-password", {
            "current_password": "Password1",
            "new_password": "NewPass1a",
            "confirm_password": "NewPass1a",
        }),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Verify new password works
    client.post("/auth/logout", follow_redirects=True)
    resp = _login(client, "pat_sec2", "NewPass1a")
    assert resp.status_code == 200


def test_change_password_wrong_current(client, app, db):
    _create_user(app, "pat_sec3")
    _login(client, "pat_sec3")
    resp = client.post(
        "/auth/change-password",
        data=signed_data("POST", "/auth/change-password", {
            "current_password": "WrongPass1",
            "new_password": "NewPass1a",
            "confirm_password": "NewPass1a",
        }),
        follow_redirects=True,
    )
    assert b"Current password is incorrect" in resp.data


def test_change_password_mismatch(client, app, db):
    _create_user(app, "pat_sec4")
    _login(client, "pat_sec4")
    resp = client.post(
        "/auth/change-password",
        data=signed_data("POST", "/auth/change-password", {
            "current_password": "Password1",
            "new_password": "NewPass1a",
            "confirm_password": "Different1a",
        }),
        follow_redirects=True,
    )
    assert b"do not match" in resp.data


def test_change_password_weak(client, app, db):
    _create_user(app, "pat_sec5")
    _login(client, "pat_sec5")
    resp = client.post(
        "/auth/change-password",
        data=signed_data("POST", "/auth/change-password", {
            "current_password": "Password1",
            "new_password": "weak",
            "confirm_password": "weak",
        }),
        follow_redirects=True,
    )
    assert b"at least 8 characters" in resp.data


def test_change_password_requires_login(client, app, db):
    resp = client.get("/auth/change-password")
    assert resp.status_code in (302, 401)


def test_export_data_requires_login(client, app, db):
    resp = client.get("/patient/export")
    assert resp.status_code in (302, 401)


def test_export_data_returns_json_download(client, app, db):
    uid = _create_user(app, "pat_exp1")
    _login(client, "pat_exp1")
    resp = client.get("/patient/export")
    assert resp.status_code == 200
    assert resp.content_type.startswith("application/json")
    assert "attachment" in resp.headers.get("Content-Disposition", "")
    data = resp.get_json()
    assert "user" in data
    assert data["user"]["username"] == "pat_exp1"
    assert "assessments" in data
    assert "appointments" in data


def test_export_data_denied_for_non_patient(client, app, db):
    _create_user(app, "admin_exp1", role="administrator")
    _login(client, "admin_exp1")
    resp = client.get("/patient/export")
    assert resp.status_code == 403


def test_delete_account_requires_password(client, app, db):
    uid = _create_user(app, "pat_del1")
    _login(client, "pat_del1")
    resp = client.post(
        "/patient/delete-account",
        data=signed_data("POST", "/patient/delete-account", {"password": "WrongPass1"}),
        follow_redirects=True,
    )
    assert b"Password is incorrect" in resp.data
    # User should still be active
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.is_active is True


def test_delete_account_anonymizes_user(client, app, db):
    uid = _create_user(app, "pat_del2")
    _login(client, "pat_del2")
    resp = client.post(
        "/patient/delete-account",
        data=signed_data("POST", "/patient/delete-account", {"password": "Password1"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.username == f"deleted_{uid}"
        assert user.is_active is False


# ---------------------------------------------------------------------------
# Reveal endpoint anti-replay tests
# ---------------------------------------------------------------------------

def _create_demographics_with_ids(app, user_id):
    """Store encrypted insurance and government IDs for a user."""
    from app.models.demographics import PatientDemographics
    from app.utils.encryption import encrypt_value
    from datetime import date
    with app.app_context():
        demo = PatientDemographics(
            user_id=user_id,
            full_name="Test Patient",
            phone="555-1111",
            date_of_birth=date(1990, 1, 1),
            insurance_id_encrypted=encrypt_value("INS-12345"),
            government_id_encrypted=encrypt_value("GOV-67890"),
        )
        db.session.add(demo)
        db.session.commit()


def test_reveal_requires_antireplay(client, app, db):
    """POST /patient/demographics/reveal without signed fields must return 400."""
    uid = _create_user(app, "pat_rev1")
    _create_demographics_with_ids(app, uid)
    _login(client, "pat_rev1")
    resp = client.post(
        "/patient/demographics/reveal",
        data={"field": "insurance_id"},
    )
    assert resp.status_code == 400


def test_reveal_rejects_invalid_signature(client, app, db):
    """POST with nonce/timestamp but wrong signature must return 400."""
    import uuid as _uuid
    from datetime import datetime, timezone
    uid = _create_user(app, "pat_rev2")
    _create_demographics_with_ids(app, uid)
    _login(client, "pat_rev2")
    resp = client.post(
        "/patient/demographics/reveal",
        data={
            "field": "insurance_id",
            "_nonce": str(_uuid.uuid4()),
            "_timestamp": datetime.now(timezone.utc).isoformat(),
            "_signature": "deadbeef" * 8,
        },
    )
    assert resp.status_code == 400


def test_reveal_succeeds_with_valid_antireplay(client, app, db):
    """POST with valid signed fields returns the decrypted value."""
    uid = _create_user(app, "pat_rev3")
    _create_demographics_with_ids(app, uid)
    _login(client, "pat_rev3")
    path = "/patient/demographics/reveal"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"field": "insurance_id"}),
    )
    assert resp.status_code == 200
    assert b"INS-12345" in resp.data


def test_reveal_government_id_succeeds(client, app, db):
    """Reveal government_id with valid anti-replay returns decrypted value."""
    uid = _create_user(app, "pat_rev4")
    _create_demographics_with_ids(app, uid)
    _login(client, "pat_rev4")
    path = "/patient/demographics/reveal"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"field": "government_id"}),
    )
    assert resp.status_code == 200
    assert b"GOV-67890" in resp.data


def test_reveal_requires_authentication(client, app, db):
    """Unauthenticated requests must not reveal data."""
    resp = client.post(
        "/patient/demographics/reveal",
        data={"field": "insurance_id"},
    )
    assert resp.status_code in (302, 400, 401)


def test_reveal_replay_rejected(client, app, db):
    """Replaying the same nonce must be rejected with 409."""
    uid = _create_user(app, "pat_rev5")
    _create_demographics_with_ids(app, uid)
    _login(client, "pat_rev5")
    path = "/patient/demographics/reveal"
    payload = signed_data("POST", path, {"field": "insurance_id"})
    resp1 = client.post(path, data=payload)
    assert resp1.status_code == 200
    resp2 = client.post(path, data=payload)
    assert resp2.status_code == 409
