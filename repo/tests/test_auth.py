"""Tests for prompt 02 — authentication & account management."""

import pytest
from tests.signing_helpers import login_data


def test_register_page_loads(client):
    resp = client.get("/auth/register")
    assert resp.status_code == 200
    assert b"Create Account" in resp.data


def test_login_page_loads(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b"Log In" in resp.data


def test_register_success(client, app):
    with app.app_context():
        resp = client.post(
            "/auth/register",
            data={
                "username": "testuser",
                "password": "Password1",
                "password_confirm": "Password1",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        from app.models.user import User

        user = User.query.filter_by(username="testuser").first()
        assert user is not None
        assert user.role == "patient"


def test_register_duplicate_username(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="existing")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        resp = client.post(
            "/auth/register",
            data={
                "username": "existing",
                "password": "Password1",
                "password_confirm": "Password1",
            },
        )
        assert b"already taken" in resp.data


def test_register_invalid_username(client, app):
    with app.app_context():
        resp = client.post(
            "/auth/register",
            data={
                "username": "ab",  # too short
                "password": "Password1",
                "password_confirm": "Password1",
            },
        )
        assert b"3-50 characters" in resp.data


def test_register_weak_password(client, app):
    with app.app_context():
        resp = client.post(
            "/auth/register",
            data={
                "username": "testuser2",
                "password": "weak",
                "password_confirm": "weak",
            },
        )
        assert b"at least 8 characters" in resp.data


def test_register_password_mismatch(client, app):
    with app.app_context():
        resp = client.post(
            "/auth/register",
            data={
                "username": "testuser3",
                "password": "Password1",
                "password_confirm": "Password2",
            },
        )
        assert b"do not match" in resp.data


def test_login_success(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="loginuser")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        resp = client.post(
            "/auth/login",
            data=login_data("loginuser", "Password1"),
            follow_redirects=True,
        )
        assert resp.status_code == 200


def test_login_invalid_credentials(client, app):
    with app.app_context():
        resp = client.post(
            "/auth/login",
            data=login_data("noone", "Wrong1234"),
        )
        assert b"Invalid username or password" in resp.data


def test_login_generic_error_message(client, app):
    """Should not reveal whether username or password is wrong."""
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="realuser")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        resp = client.post(
            "/auth/login",
            data=login_data("realuser", "WrongPass1"),
        )
        assert b"Invalid username or password" in resp.data
        assert b"password is wrong" not in resp.data.lower()
        assert b"username not found" not in resp.data.lower()


def test_logout(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="logoutuser")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        client.post(
            "/auth/login",
            data=login_data("logoutuser", "Password1"),
        )
        resp = client.post("/auth/logout", follow_redirects=True)
        assert resp.status_code == 200
        assert b"logged out" in resp.data.lower()


def test_rate_limiting(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="ratelimited")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        for _ in range(10):
            client.post(
                "/auth/login",
                data=login_data("ratelimited", "WrongPass1"),
            )

        resp = client.post(
            "/auth/login",
            data=login_data("ratelimited", "Password1"),
        )
        assert b"Too many login attempts" in resp.data


def test_check_username_available(client, app):
    with app.app_context():
        resp = client.get("/auth/check-username?username=newuser")
        assert b"available" in resp.data.lower()


def test_check_username_taken(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="takenuser")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        resp = client.get("/auth/check-username?username=takenuser")
        assert b"already taken" in resp.data.lower()


def test_check_username_invalid(client, app):
    with app.app_context():
        resp = client.get("/auth/check-username?username=ab")
        assert b"3-50 characters" in resp.data.lower()


def test_password_hashed_not_plaintext(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="hashtest")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        assert user.password_hash != "Password1"
        assert user.check_password("Password1")
        assert not user.check_password("wrong")


def test_deactivated_user_cannot_login(client, app):
    with app.app_context():
        from app.models.user import User
        from app.extensions import db

        user = User(username="deactivated_user", is_active=False)
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()

        resp = client.post(
            "/auth/login",
            data=login_data("deactivated_user", "Password1"),
        )
        assert b"Invalid username or password" in resp.data


def test_login_attempt_recording(client, app):
    with app.app_context():
        from app.models.user import LoginAttempt

        client.post(
            "/auth/login",
            data=login_data("nobody", "WrongPass1"),
        )
        attempts = LoginAttempt.query.filter_by(username="nobody").all()
        assert len(attempts) == 1
        assert attempts[0].success is False
