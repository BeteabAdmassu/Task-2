"""Tests for prompt 01 — project foundation."""

import json


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_index_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"MeridianCare" in resp.data


def test_index_has_htmx(client):
    resp = client.get("/")
    assert b"htmx.min.js" in resp.data


def test_index_has_csrf_token(client):
    resp = client.get("/")
    assert b"csrf-token" in resp.data


def test_correlation_id_in_response(client):
    resp = client.get("/health")
    assert "X-Correlation-ID" in resp.headers


def test_custom_correlation_id(client):
    resp = client.get("/health", headers={"X-Correlation-ID": "test-123"})
    assert resp.headers["X-Correlation-ID"] == "test-123"


def test_static_css(client):
    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200


def test_static_htmx(client):
    resp = client.get("/static/js/htmx.min.js")
    assert resp.status_code == 200


def test_app_factory_configs():
    from app import create_app

    dev_app = create_app("development")
    assert dev_app.debug is True

    test_app = create_app("testing")
    assert test_app.testing is True

    import os
    from cryptography.fernet import Fernet
    os.environ.setdefault("SECRET_KEY", "stable-test-secret-key-1234567890ab")
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    prod_app = create_app("production")
    assert prod_app.debug is False
    assert prod_app.testing is False
