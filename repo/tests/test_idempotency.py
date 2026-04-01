"""Tests for prompt 13 — Idempotent Transitions & Request Tokens."""

import pytest
from datetime import datetime, timezone, timedelta
from app.models.idempotency import RequestToken
from app.utils.idempotency import check_idempotency, save_idempotency
from app.extensions import db


def test_save_and_check_idempotency(app, db):
    with app.app_context():
        save_idempotency("test_tok_1", "/api/test", {"status": "ok"})
        result = check_idempotency("test_tok_1")
        assert result == {"status": "ok"}


def test_check_nonexistent_token(app, db):
    with app.app_context():
        result = check_idempotency("nonexistent_token")
        assert result is None


def test_check_none_token(app, db):
    with app.app_context():
        result = check_idempotency(None)
        assert result is None


def test_check_empty_token(app, db):
    with app.app_context():
        result = check_idempotency("")
        assert result is None


def test_save_duplicate_token_no_error(app, db):
    with app.app_context():
        save_idempotency("dup_tok", "/api/test", {"first": True})
        save_idempotency("dup_tok", "/api/test", {"second": True})
        result = check_idempotency("dup_tok")
        assert result == {"first": True}


def test_expired_token_returns_none(app, db):
    with app.app_context():
        token = RequestToken(
            token="expired_tok",
            endpoint="/api/test",
            result_json={"data": "old"},
            created_at=datetime.now(timezone.utc) - timedelta(hours=48),
            expires_at=datetime.now(timezone.utc) - timedelta(hours=24),
        )
        db.session.add(token)
        db.session.commit()
        result = check_idempotency("expired_tok")
        assert result is None


def test_request_token_model(app, db):
    with app.app_context():
        token = RequestToken(
            token="model_tok",
            endpoint="/visits/1/transition",
            result_json={"visit_id": 1, "new_status": "checked_in"},
        )
        db.session.add(token)
        db.session.commit()
        fetched = RequestToken.query.filter_by(token="model_tok").first()
        assert fetched is not None
        assert fetched.endpoint == "/visits/1/transition"
        assert fetched.result_json["visit_id"] == 1


def test_save_idempotency_with_none_token(app, db):
    with app.app_context():
        result = save_idempotency(None, "/api/test", {"data": "test"})
        assert result is None
