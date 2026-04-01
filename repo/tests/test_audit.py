"""Tests for prompt 09 — Audit Logging."""

import pytest
from app.models.user import User
from app.models.audit import AuditLog
from app.utils.audit import log_action
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


def test_log_action_creates_entry(app, db):
    with app.app_context():
        entry = log_action("test_action", "test_resource", resource_id=1, details={"key": "val"})
        assert entry.id is not None
        assert entry.action == "test_action"
        assert entry.resource_type == "test_resource"


def test_log_action_without_request_context(app, db):
    with app.app_context():
        entry = log_action("background_action", "system")
        assert entry.ip_address is None


def test_audit_log_page_requires_admin(client, app, db):
    _create_user(app, "pat_aud1")
    _login(client, "pat_aud1")
    resp = client.get("/admin/audit")
    assert resp.status_code == 403


def test_audit_log_page_accessible_by_admin(client, app, db):
    _create_user(app, "admin_aud1", role="administrator")
    _login(client, "admin_aud1")
    resp = client.get("/admin/audit")
    assert resp.status_code == 200
    assert b"Audit Log" in resp.data


def test_audit_log_captures_request_info(client, app, db):
    _create_user(app, "admin_aud2", role="administrator")
    _login(client, "admin_aud2")
    with app.app_context():
        # The login itself won't auto-log, but we can manually call in request context
        pass
    # Create an audit entry via a test request
    with app.test_request_context("/test", headers={"User-Agent": "TestAgent"}):
        from flask_login import login_user
        user = User.query.filter_by(username="admin_aud2").first()
        login_user(user)
        entry = log_action("manual_test", "test", resource_id=42)
        assert entry.user_agent == "TestAgent"
        assert entry.user_id == user.id


def test_audit_log_pagination(client, app, db):
    _create_user(app, "admin_aud3", role="administrator")
    _login(client, "admin_aud3")
    with app.app_context():
        for i in range(5):
            log_action(f"action_{i}", "test")
    resp = client.get("/admin/audit?page=1")
    assert resp.status_code == 200


def test_audit_model_fields(app, db):
    with app.app_context():
        entry = AuditLog(
            action="test", resource_type="widget", resource_id="99",
            details_json={"foo": "bar"}, ip_address="1.2.3.4", user_agent="Bot/1.0"
        )
        db.session.add(entry)
        db.session.commit()
        fetched = db.session.get(AuditLog, entry.id)
        assert fetched.details_json == {"foo": "bar"}
        assert fetched.ip_address == "1.2.3.4"
