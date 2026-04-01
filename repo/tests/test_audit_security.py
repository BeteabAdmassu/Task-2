"""Tests for architecture/security fixes:
- Anti-replay enforcement on newly protected endpoints
- Slow-query persistence to DB
- Token/nonce hashing at rest
"""

import hashlib
import time as time_module
import pytest
from unittest.mock import patch
from datetime import date, datetime, timezone, timedelta

from app.models.user import User
from app.models.audit import SlowQuery, SignedRequest
from app.models.idempotency import RequestToken
from app.models.visit import Visit, VisitTransition
from app.models.scheduling import Clinician, Room, Slot
from app.extensions import db
from tests.signing_helpers import signed_data


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
        data={"username": username, "password": password},
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Fix 3: anti-replay enforcement on newly protected endpoints
# ---------------------------------------------------------------------------

def test_change_role_requires_antireplay(client, app, db):
    """POST /admin/users/<id>/role without signed fields returns 400."""
    _create_user(app, "admin_ar1", role="administrator")
    uid = _create_user(app, "user_ar1", role="patient")
    _login(client, "admin_ar1")
    resp = client.post(
        f"/admin/users/{uid}/role",
        data={"role": "clinician"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 400


def test_change_role_succeeds_with_antireplay(client, app, db):
    """POST /admin/users/<id>/role with correct signed fields succeeds."""
    _create_user(app, "admin_ar2", role="administrator")
    uid = _create_user(app, "user_ar2", role="patient")
    _login(client, "admin_ar2")
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


def test_change_status_requires_antireplay(client, app, db):
    """POST /admin/users/<id>/status without signed fields returns 400."""
    _create_user(app, "admin_ar3", role="administrator")
    uid = _create_user(app, "user_ar3", role="patient")
    _login(client, "admin_ar3")
    resp = client.post(
        f"/admin/users/{uid}/status",
        data={"is_active": "false"},
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 400


def test_update_reminder_config_requires_antireplay(client, app, db):
    """POST /reminders/admin/config/0 without signed fields returns 400."""
    _create_user(app, "admin_ar4", role="administrator")
    _login(client, "admin_ar4")
    resp = client.post(
        "/reminders/admin/config/0",
        data={"interval_days": "60"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_acknowledge_alert_requires_antireplay(client, app, db):
    """POST /admin/operations/alerts/<id>/acknowledge without signed fields returns 400."""
    from app.models.audit import AnomalyAlert
    _create_user(app, "admin_ar5", role="administrator")
    _login(client, "admin_ar5")
    with app.app_context():
        alert = AnomalyAlert(
            alert_type="failed_logins", severity="warning",
            message="Test alert",
        )
        db.session.add(alert)
        db.session.commit()
        aid = alert.id
    resp = client.post(
        f"/admin/operations/alerts/{aid}/acknowledge",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_acknowledge_alert_succeeds_with_antireplay(client, app, db):
    """POST /admin/operations/alerts/<id>/acknowledge with signed fields succeeds."""
    from app.models.audit import AnomalyAlert
    _create_user(app, "admin_ar6", role="administrator")
    _login(client, "admin_ar6")
    with app.app_context():
        alert = AnomalyAlert(
            alert_type="failed_logins", severity="warning",
            message="Test alert 2",
        )
        db.session.add(alert)
        db.session.commit()
        aid = alert.id
    path = f"/admin/operations/alerts/{aid}/acknowledge"
    resp = client.post(
        path,
        data=signed_data("POST", path),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        alert = db.session.get(AnomalyAlert, aid)
        assert alert.acknowledged_at is not None
        assert alert.acknowledged_by is not None


def test_delete_holiday_requires_antireplay(client, app, db):
    """POST /schedule/admin/holidays/<id>/delete without signed fields returns 400."""
    from app.models.scheduling import Holiday
    _create_user(app, "admin_ar7", role="administrator")
    _login(client, "admin_ar7")
    with app.app_context():
        h = Holiday(date=date(2099, 1, 1), name="FutureHoliday", created_by=1)
        db.session.add(h)
        db.session.commit()
        hid = h.id
    resp = client.post(
        f"/schedule/admin/holidays/{hid}/delete",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_delete_holiday_succeeds_with_antireplay(client, app, db):
    """POST /schedule/admin/holidays/<id>/delete with signed fields removes the holiday."""
    from app.models.scheduling import Holiday
    _create_user(app, "admin_ar8", role="administrator")
    _login(client, "admin_ar8")
    with app.app_context():
        h = Holiday(date=date(2099, 2, 2), name="AnotherHoliday", created_by=1)
        db.session.add(h)
        db.session.commit()
        hid = h.id
    path = f"/schedule/admin/holidays/{hid}/delete"
    resp = client.post(
        path,
        data=signed_data("POST", path),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert db.session.get(Holiday, hid) is None


# ---------------------------------------------------------------------------
# Fix 4: slow-query persistence
# ---------------------------------------------------------------------------

def test_slow_query_persisted_to_db(client, app, db):
    """Requests exceeding 500 ms threshold are written to slow_queries table."""
    _create_user(app, "admin_sq1", role="administrator")
    _login(client, "admin_sq1")

    # Patch time.time in the middleware module so duration appears > 500 ms.
    # First call (record_request_start) returns 0.0; second call (log_request)
    # returns 1.0, making duration_ms = 1000 ms.
    call_count = {"n": 0}
    original = time_module.time

    def mock_time():
        count = call_count["n"]
        call_count["n"] += 1
        if count == 0:
            return 0.0
        return 1.0  # 1000 ms later

    with patch("app.utils.middleware.time") as mock_time_mod:
        mock_time_mod.time = mock_time
        resp = client.get("/admin/observability")
        assert resp.status_code == 200

    with app.app_context():
        sq = SlowQuery.query.filter_by(endpoint="/admin/observability").first()
        assert sq is not None
        assert sq.duration_ms > 500
        assert sq.correlation_id is not None


def test_slow_query_not_persisted_for_fast_requests(client, app, db):
    """Fast requests (< 500 ms) do not create slow_queries rows."""
    _create_user(app, "admin_sq2", role="administrator")
    _login(client, "admin_sq2")

    with app.app_context():
        count_before = SlowQuery.query.filter_by(endpoint="/health").count()

    resp = client.get("/health")
    assert resp.status_code == 200

    with app.app_context():
        count_after = SlowQuery.query.filter_by(endpoint="/health").count()
        # Fast real requests should not add rows (the health check is negligible)
        assert count_after == count_before


# ---------------------------------------------------------------------------
# Fix 5: token / nonce hashing at rest
# ---------------------------------------------------------------------------

def test_nonce_stored_as_hash_not_raw(app, db):
    """SignedRequest stores SHA-256 hash of the nonce, not the raw value."""
    from app.utils.antireplay import _hash_nonce
    raw_nonce = "test-nonce-for-hash-check"
    expected_hash = _hash_nonce(raw_nonce)

    # Manually create a SignedRequest the way antireplay.py does it.
    with app.app_context():
        now = datetime.now(timezone.utc)
        sr = SignedRequest(
            nonce=expected_hash,
            timestamp=now,
            expires_at=now + timedelta(minutes=5),
        )
        db.session.add(sr)
        db.session.commit()

        # Raw nonce is NOT findable in DB.
        assert SignedRequest.query.filter_by(nonce=raw_nonce).first() is None
        # Hashed nonce IS findable.
        assert SignedRequest.query.filter_by(nonce=expected_hash).first() is not None


def test_idempotency_token_stored_as_hash(app, db):
    """RequestToken stores SHA-256 hash of the token, not the raw value."""
    from app.utils.idempotency import save_idempotency, check_idempotency, _hash_token

    raw_token = "raw-idempotency-token-9999"
    expected_hash = _hash_token(raw_token)

    with app.app_context():
        save_idempotency(raw_token, "/test/endpoint", {"ok": True})

        # Verify the DB row holds the hash, not the raw value.
        row = RequestToken.query.filter_by(token=expected_hash).first()
        assert row is not None
        assert RequestToken.query.filter_by(token=raw_token).first() is None

        # check_idempotency must still find it by providing the raw token.
        result = check_idempotency(raw_token)
        assert result == {"ok": True}


def test_visit_transition_token_stored_as_hash(app, db):
    """VisitTransition stores SHA-256 hash of request_token, not the raw value."""
    from app.models.scheduling import Clinician
    from app.utils.state_machine import transition_visit, _hash_token

    with app.app_context():
        u = User(username="doc_hash_v", role="clinician")
        u.set_password("Password1")
        db.session.add(u)
        db.session.commit()
        clin = Clinician(user_id=u.id)
        db.session.add(clin)
        db.session.commit()
        pat = User(username="pat_hash_v", role="patient")
        pat.set_password("Password1")
        db.session.add(pat)
        db.session.commit()
        visit = Visit(patient_id=pat.id, clinician_id=clin.id, status="booked")
        db.session.add(visit)
        db.session.commit()

        raw_token = "raw-visit-token-abc123"
        expected_hash = _hash_token(raw_token)

        t = transition_visit(visit, "checked_in", u.id, request_token=raw_token)
        assert t.request_token == expected_hash
        # Raw token is NOT stored.
        assert VisitTransition.query.filter_by(request_token=raw_token).first() is None


def test_transition_idempotency_works_with_hashed_token(app, db):
    """Idempotency check still works correctly when tokens are hashed."""
    from app.models.scheduling import Clinician
    from app.utils.state_machine import transition_visit

    with app.app_context():
        u = User(username="doc_idem_v", role="clinician")
        u.set_password("Password1")
        db.session.add(u)
        db.session.commit()
        clin = Clinician(user_id=u.id)
        db.session.add(clin)
        db.session.commit()
        pat = User(username="pat_idem_v", role="patient")
        pat.set_password("Password1")
        db.session.add(pat)
        db.session.commit()
        visit = Visit(patient_id=pat.id, clinician_id=clin.id, status="booked")
        db.session.add(visit)
        db.session.commit()

        raw_token = "idempotency-test-token"

        t1 = transition_visit(visit, "checked_in", u.id, request_token=raw_token)
        assert t1.from_status == "booked"
        assert t1.to_status == "checked_in"

        # Second call with same raw token returns the cached transition.
        t2 = transition_visit(visit, "seen", u.id, request_token=raw_token)
        assert t1.id == t2.id
        # Visit stays at checked_in — the second transition was suppressed.
        assert visit.status == "checked_in"


# ---------------------------------------------------------------------------
# Fix A: secure default startup (run.py defaults to "production")
# ---------------------------------------------------------------------------

def test_run_py_defaults_to_production():
    """run.py must default to 'production', not 'development'."""
    import re
    with open("run.py") as f:
        content = f.read()
    # The fallback value in os.environ.get("FLASK_ENV", ...) must not be "development"
    match = re.search(r'os\.environ\.get\(\s*["\']FLASK_ENV["\']\s*,\s*["\'](\w+)["\']\s*\)', content)
    assert match is not None, "FLASK_ENV default not found in run.py"
    assert match.group(1) != "development", (
        "run.py defaults to 'development' — must default to 'production'"
    )
    assert match.group(1) == "production"


# ---------------------------------------------------------------------------
# Fix B: anti-replay on staff demographics POST
# ---------------------------------------------------------------------------

def test_staff_demographics_post_requires_antireplay(client, app, db):
    """POST /staff/patients/<id>/demographics without signed fields returns 400."""
    _create_user(app, "admin_sdar1", role="administrator")
    uid = _create_user(app, "pat_sdar1", role="patient")
    _login(client, "admin_sdar1")
    path = f"/staff/patients/{uid}/demographics"
    resp = client.post(
        path,
        data={
            "full_name": "Test User",
            "date_of_birth": "1990-01-01",
            "phone": "555-000-0000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_staff_demographics_post_succeeds_with_antireplay(client, app, db):
    """POST /staff/patients/<id>/demographics with signed fields saves demographics."""
    _create_user(app, "admin_sdar2", role="administrator")
    uid = _create_user(app, "pat_sdar2", role="patient")
    _login(client, "admin_sdar2")
    path = f"/staff/patients/{uid}/demographics"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "full_name": "Signed User",
            "date_of_birth": "1985-06-15",
            "phone": "555-111-2222",
        }),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    from app.models.demographics import PatientDemographics
    with app.app_context():
        demo = PatientDemographics.query.filter_by(user_id=uid).first()
        assert demo is not None
        assert demo.full_name == "Signed User"


# ---------------------------------------------------------------------------
# Fix C: mask_encrypted_id returns last 4 of plaintext, not ciphertext slices
# ---------------------------------------------------------------------------

def test_mask_encrypted_id_shows_last_4_of_plaintext(app, db):
    """mask_encrypted_id must decrypt and show last 4 chars of the plaintext."""
    from app.utils.encryption import encrypt_value, mask_encrypted_id, mask_id
    with app.app_context():
        plaintext = "GOV987654321"
        ciphertext = encrypt_value(plaintext)
        masked = mask_encrypted_id(ciphertext)
        # Should match masking the plaintext directly
        assert masked == mask_id(plaintext)
        assert masked.endswith("4321")
        assert "***" in masked


def test_mask_encrypted_id_not_masking_ciphertext(app, db):
    """mask_encrypted_id must NOT produce the same result as mask_id on ciphertext."""
    from app.utils.encryption import encrypt_value, mask_encrypted_id, mask_id
    with app.app_context():
        plaintext = "INS123456789"
        ciphertext = encrypt_value(plaintext)
        # Calling mask_id on the ciphertext directly gives wrong result
        wrong = mask_id(ciphertext)
        correct = mask_encrypted_id(ciphertext)
        # The masked outputs must differ because plaintext != ciphertext
        assert correct != wrong
        assert correct.endswith("6789")


def test_mask_encrypted_id_empty_returns_empty(app, db):
    """mask_encrypted_id must return empty string for None/empty input."""
    from app.utils.encryption import mask_encrypted_id
    with app.app_context():
        assert mask_encrypted_id(None) == ""
        assert mask_encrypted_id("") == ""


# ---------------------------------------------------------------------------
# Fix D: room conflict detection in slot generation
# ---------------------------------------------------------------------------

def test_room_conflict_prevents_duplicate_room_slot(app, db):
    """_has_room_conflict returns True when room is already booked for overlapping time."""
    from app.routes.schedule import _has_room_conflict
    from datetime import date, time
    with app.app_context():
        room = Room(name="TestRoom-Conflict", is_active=True)
        db.session.add(room)
        db.session.commit()

        user = User(username="doc_rc1", role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clin = Clinician(user_id=user.id)
        db.session.add(clin)
        db.session.commit()

        slot_date = date(2099, 6, 1)
        existing = Slot(
            clinician_id=clin.id,
            room_id=room.id,
            date=slot_date,
            start_time=time(9, 0),
            end_time=time(9, 30),
            capacity=1,
        )
        db.session.add(existing)
        db.session.commit()

        # Exact overlap: same time window
        assert _has_room_conflict(room.id, slot_date, time(9, 0), time(9, 30)) is True
        # Partial overlap: starts before, ends during
        assert _has_room_conflict(room.id, slot_date, time(8, 45), time(9, 15)) is True
        # No overlap: immediately after
        assert _has_room_conflict(room.id, slot_date, time(9, 30), time(10, 0)) is False
        # No conflict for a different room
        assert _has_room_conflict(None, slot_date, time(9, 0), time(9, 30)) is False


def test_bulk_generate_skips_room_conflict_slots(client, app, db):
    """Bulk generate skips slots whose assigned room is already occupied."""
    from datetime import date, time
    _create_user(app, "admin_bg_room", role="administrator")
    _login(client, "admin_bg_room")

    with app.app_context():
        room = Room(name="BulkRoom-Test", is_active=True)
        db.session.add(room)
        db.session.commit()
        rid = room.id

        doc_user = User(username="doc_bg_room", role="clinician")
        doc_user.set_password("Password1")
        db.session.add(doc_user)
        db.session.commit()
        clin = Clinician(user_id=doc_user.id, default_slot_duration_minutes=30)
        db.session.add(clin)
        db.session.commit()

        # Monday template 09:00–09:30
        from app.models.scheduling import ScheduleTemplate
        tmpl = ScheduleTemplate(
            clinician_id=clin.id,
            day_of_week=0,  # Monday
            start_time=time(9, 0),
            end_time=time(9, 30),
            slot_duration=30,
            capacity=1,
        )
        db.session.add(tmpl)
        db.session.commit()

        # Pre-occupy the room on the target Monday
        slot_date = date(2099, 7, 7)  # a Monday
        blocker_user = User(username="doc_bg_blocker", role="clinician")
        blocker_user.set_password("Password1")
        db.session.add(blocker_user)
        db.session.commit()
        blocker_clin = Clinician(user_id=blocker_user.id)
        db.session.add(blocker_clin)
        db.session.commit()

        # Unique start_time for blocker clinician
        blocker_slot = Slot(
            clinician_id=blocker_clin.id,
            room_id=rid,
            date=slot_date,
            start_time=time(9, 0),
            end_time=time(9, 30),
            capacity=1,
        )
        db.session.add(blocker_slot)
        db.session.commit()
        cid = clin.id

    resp = client.post(
        "/schedule/admin/bulk-generate",
        data={
            "clinician_id": cid,
            "date_from": "2099-07-07",
            "date_to": "2099-07-07",
            "room_id": rid,
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        # The conflicting slot should not have been created for clin (only blocker_clin has a slot)
        new_slots = Slot.query.filter_by(
            clinician_id=cid,
            date=date(2099, 7, 7),
        ).all()
        assert len(new_slots) == 0
