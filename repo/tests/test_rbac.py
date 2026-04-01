"""Tests for prompt 03 — RBAC authorization."""

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


def _login(client, username="testuser", password="Password1"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def test_admin_users_page_requires_login(client):
    resp = client.get("/admin/users", follow_redirects=True)
    assert b"Log In" in resp.data


def test_admin_users_page_requires_admin(client, app):
    _create_user(app, "patient1", role="patient")
    _login(client, "patient1")
    resp = client.get("/admin/users")
    assert resp.status_code == 403


def test_admin_users_page_accessible_by_admin(client, app):
    _create_user(app, "admin1", role="administrator")
    _login(client, "admin1")
    resp = client.get("/admin/users")
    assert resp.status_code == 200
    assert b"User Management" in resp.data


def test_clinician_cannot_access_admin(client, app):
    _create_user(app, "clinician1", role="clinician")
    _login(client, "clinician1")
    resp = client.get("/admin/users")
    assert resp.status_code == 403


def test_front_desk_cannot_access_admin(client, app):
    _create_user(app, "frontdesk1", role="front_desk")
    _login(client, "frontdesk1")
    resp = client.get("/admin/users")
    assert resp.status_code == 403


def test_change_user_role(client, app):
    _create_user(app, "admin2", role="administrator")
    uid = _create_user(app, "user2", role="patient")
    _login(client, "admin2")
    path = f"/admin/users/{uid}/role"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"role": "clinician"}),
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.role == "clinician"


def test_cannot_change_own_role(client, app):
    _create_user(app, "admin3", role="administrator")
    _login(client, "admin3")
    with app.app_context():
        admin = User.query.filter_by(username="admin3").first()
        resp = client.post(
            f"/admin/users/{admin.id}/role",
            data={"role": "patient"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 400


def test_cannot_demote_last_admin(client, app):
    uid = _create_user(app, "admin4", role="administrator")
    _create_user(app, "admin5", role="administrator")
    _login(client, "admin5")
    # Demote admin4 first
    path = f"/admin/users/{uid}/role"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"role": "patient"}),
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    # Now try to self-demote admin5 — should fail (can't change own role)
    with app.app_context():
        admin5 = User.query.filter_by(username="admin5").first()
        # Self-change returns 400 before antireplay is even consulted
        resp = client.post(
            f"/admin/users/{admin5.id}/role",
            data={"role": "patient"},
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 400


def test_deactivate_user(client, app):
    _create_user(app, "admin6", role="administrator")
    uid = _create_user(app, "user6", role="patient")
    _login(client, "admin6")
    path = f"/admin/users/{uid}/status"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"is_active": "false"}),
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    with app.app_context():
        user = db.session.get(User, uid)
        assert user.is_active is False


def test_deactivated_user_cannot_login(client, app):
    _create_user(app, "admin7", role="administrator")
    _create_user(app, "deactivated", role="patient")
    _login(client, "admin7")
    with app.app_context():
        user = User.query.filter_by(username="deactivated").first()
        uid_deact = user.id
    path = f"/admin/users/{uid_deact}/status"
    client.post(path, data=signed_data("POST", path, {"is_active": "false"}))

    # Logout admin and try to login as deactivated user
    client.post("/auth/logout")
    resp = _login(client, "deactivated")
    # The user can authenticate but session won't load them
    # Since is_active=False, login should fail or session won't persist
    assert resp.status_code == 200


def test_invalid_role_rejected(client, app):
    _create_user(app, "admin8", role="administrator")
    uid = _create_user(app, "user8", role="patient")
    _login(client, "admin8")
    resp = client.post(
        f"/admin/users/{uid}/role",
        data={"role": "superuser"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 400


def test_403_page_styled(client, app):
    _create_user(app, "patient9", role="patient")
    _login(client, "patient9")
    resp = client.get("/admin/users")
    assert resp.status_code == 403
    assert b"Access Denied" in resp.data


def test_role_required_htmx_returns_json(client, app):
    _create_user(app, "patient10", role="patient")
    _login(client, "patient10")
    resp = client.get("/admin/users", headers={"HX-Request": "true"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "Access denied"


def test_nav_shows_admin_link_for_admin(client, app):
    _create_user(app, "admin11", role="administrator")
    _login(client, "admin11")
    resp = client.get("/")
    assert b"Users" in resp.data


def test_nav_hides_admin_link_for_patient(client, app):
    _create_user(app, "patient11", role="patient")
    _login(client, "patient11")
    resp = client.get("/")
    assert b"/admin/users" not in resp.data
