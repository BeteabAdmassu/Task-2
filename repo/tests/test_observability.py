"""Tests for prompt 12 — Observability & Admin Operations."""

import pytest
from app.models.user import User
from app.extensions import db
from tests.signing_helpers import login_data


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


def test_observability_requires_admin(client, app, db):
    _create_user(app, "pat_obs1")
    _login(client, "pat_obs1")
    resp = client.get("/admin/observability")
    assert resp.status_code == 403


def test_observability_accessible_by_admin(client, app, db):
    _create_user(app, "admin_obs1", role="administrator")
    _login(client, "admin_obs1")
    resp = client.get("/admin/observability")
    assert resp.status_code == 200
    assert b"System Observability" in resp.data


def test_observability_shows_table_stats(client, app, db):
    _create_user(app, "admin_obs2", role="administrator")
    _login(client, "admin_obs2")
    resp = client.get("/admin/observability")
    assert b"users" in resp.data
    assert b"visits" in resp.data


def test_observability_requires_login(client, app, db):
    resp = client.get("/admin/observability")
    assert resp.status_code in (302, 401)


def test_observability_table_counts(client, app, db):
    _create_user(app, "admin_obs3", role="administrator")
    _create_user(app, "user_obs3a")
    _create_user(app, "user_obs3b")
    _login(client, "admin_obs3")
    resp = client.get("/admin/observability")
    assert resp.status_code == 200
    # Should contain numeric row counts
    assert b"Database Statistics" in resp.data


def test_health_detailed_returns_json(client, app, db):
    # /health/detailed is now gated to administrators
    _create_user(app, "admin_hd1", role="administrator")
    _login(client, "admin_hd1")
    resp = client.get("/health/detailed")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert "tables" in data
    assert "timestamp" in data
    assert isinstance(data["tables"], dict)
    assert "users" in data["tables"]


def test_health_detailed_requires_auth(client, app, db):
    # Unauthenticated requests must be rejected (not publicly accessible)
    resp = client.get("/health/detailed")
    assert resp.status_code in (302, 401, 403)


def test_health_detailed_requires_admin_role(client, app, db):
    # Non-admin users must be forbidden
    _create_user(app, "patient_hd1", role="patient")
    _login(client, "patient_hd1")
    resp = client.get("/health/detailed")
    assert resp.status_code in (302, 403)
