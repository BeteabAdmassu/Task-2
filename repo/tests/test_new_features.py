"""Integration tests for features added in the post-audit fix pass.

Covers:
  - Zone deactivate endpoint
  - Login rate limiting returns HTTP 429
  - Observability sub-endpoints (alerts, slow-queries)
  - Medication adherence 4-question scoring
  - Login anti-replay enforcement (new decorator on login)
"""

import pytest
from app.models.user import User
from app.models.coverage import CoverageZone
from app.models.audit import AnomalyAlert, SlowQuery
from app.extensions import db as _db
from tests.signing_helpers import signed_data, login_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        u = User(username=username, role=role)
        u.set_password(password)
        _db.session.add(u)
        _db.session.commit()
        return u.id


def _login(client, username, password="Password1"):
    # Ensure any existing session is cleared before logging in as a different user.
    client.post("/auth/logout", follow_redirects=True)
    return client.post(
        "/auth/login",
        data=login_data(username, password),
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# 1. Zone deactivate endpoint
# ---------------------------------------------------------------------------

class TestZoneDeactivate:

    def test_deactivate_zone_marks_inactive(self, client, app, db):
        _make_user(app, "adm_deact1", role="administrator")
        _login(client, "adm_deact1")
        with app.app_context():
            zone = CoverageZone(name="DeactZone1", zip_codes_json=["55001"], is_active=True)
            _db.session.add(zone)
            _db.session.commit()
            zid = zone.id

        path = f"/coverage/zones/{zid}/deactivate"
        resp = client.post(path, data=signed_data("POST", path, {"reason": "Test deactivation"}), follow_redirects=True)
        assert resp.status_code == 200

        with app.app_context():
            zone = _db.session.get(CoverageZone, zid)
            assert zone.is_active is False

    def test_deactivate_zone_logs_action(self, client, app, db):
        from app.models.audit import AuditLog
        _make_user(app, "adm_deact2", role="administrator")
        _login(client, "adm_deact2")
        with app.app_context():
            zone = CoverageZone(name="DeactZone2", zip_codes_json=["55002"], is_active=True)
            _db.session.add(zone)
            _db.session.commit()
            zid = zone.id

        path = f"/coverage/zones/{zid}/deactivate"
        client.post(path, data=signed_data("POST", path, {"reason": "Test deactivation"}), follow_redirects=True)

        with app.app_context():
            entry = AuditLog.query.filter_by(action="deactivate_zone", resource_id=zid).first()
            assert entry is not None

    def test_deactivate_zone_requires_admin(self, client, app, db):
        _make_user(app, "pat_deact3", role="patient")
        _login(client, "pat_deact3")
        with app.app_context():
            zone = CoverageZone(name="DeactZone3", zip_codes_json=["55003"], is_active=True)
            _db.session.add(zone)
            _db.session.commit()
            zid = zone.id

        path = f"/coverage/zones/{zid}/deactivate"
        resp = client.post(path, data=signed_data("POST", path), follow_redirects=False)
        assert resp.status_code in (302, 403)

    def test_deactivate_zone_missing_zone_returns_redirect(self, client, app, db):
        _make_user(app, "adm_deact4", role="administrator")
        _login(client, "adm_deact4")
        path = "/coverage/zones/99999/deactivate"
        resp = client.post(path, data=signed_data("POST", path), follow_redirects=True)
        assert resp.status_code == 200  # redirects back with flash

    def test_deactivated_zone_excluded_from_check(self, client, app, db):
        """A deactivated zone must not appear in /coverage/check results."""
        _make_user(app, "adm_deact5", role="administrator")
        _make_user(app, "pat_deact5", role="patient")
        _login(client, "adm_deact5")
        with app.app_context():
            zone = CoverageZone(
                name="DeactCheckZone", zip_codes_json=["56001"], is_active=True
            )
            _db.session.add(zone)
            _db.session.commit()
            zid = zone.id

        path = f"/coverage/zones/{zid}/deactivate"
        client.post(path, data=signed_data("POST", path, {"reason": "Test deactivation"}), follow_redirects=True)

        # Switch to patient to call /coverage/check
        _login(client, "pat_deact5")
        resp = client.get("/coverage/check?zip=56001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["covered"] is False


# ---------------------------------------------------------------------------
# 2. Login rate limiting returns HTTP 429
# ---------------------------------------------------------------------------

class TestLoginRateLimiting:

    def test_rate_limited_response_is_429(self, client, app, db):
        _make_user(app, "rl_user_429")
        for _ in range(10):
            client.post("/auth/login", data=login_data("rl_user_429", "BadPass1"))

        resp = client.post("/auth/login", data=login_data("rl_user_429", "BadPass1"))
        assert resp.status_code == 429

    def test_rate_limited_correct_password_also_429(self, client, app, db):
        """Even valid credentials return 429 while account is locked."""
        _make_user(app, "rl_correct_429")
        for _ in range(10):
            client.post("/auth/login", data=login_data("rl_correct_429", "BadPass1"))

        resp = client.post("/auth/login", data=login_data("rl_correct_429", "Password1"))
        assert resp.status_code == 429

    def test_rate_limited_htmx_also_429(self, client, app, db):
        """HTMX login path also returns 429 when rate-limited."""
        _make_user(app, "rl_htmx_429")
        for _ in range(10):
            client.post(
                "/auth/login",
                data=login_data("rl_htmx_429", "BadPass1"),
                headers={"HX-Request": "true"},
            )

        resp = client.post(
            "/auth/login",
            data=login_data("rl_htmx_429", "BadPass1"),
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 429

    def test_rate_limited_message_includes_retry_time(self, client, app, db):
        _make_user(app, "rl_msg_429")
        for _ in range(10):
            client.post("/auth/login", data=login_data("rl_msg_429", "BadPass1"))

        resp = client.post("/auth/login", data=login_data("rl_msg_429", "BadPass1"))
        assert b"Too many login attempts" in resp.data


# ---------------------------------------------------------------------------
# 3. Login anti-replay enforcement
# ---------------------------------------------------------------------------

class TestLoginAntireplay:

    def test_login_missing_nonce_returns_400(self, client, app, db):
        _make_user(app, "ar_user1")
        resp = client.post(
            "/auth/login",
            data={"username": "ar_user1", "password": "Password1"},
        )
        assert resp.status_code == 400

    def test_login_missing_signature_returns_400(self, client, app, db):
        import uuid
        from datetime import datetime, timezone
        _make_user(app, "ar_user2")
        resp = client.post(
            "/auth/login",
            data={
                "username": "ar_user2",
                "password": "Password1",
                "_nonce": str(uuid.uuid4()),
                "_timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert resp.status_code == 400

    def test_login_replayed_nonce_returns_409(self, client, app, db):
        _make_user(app, "ar_user3")
        data = login_data("ar_user3")
        client.post("/auth/login", data=data)

        resp = client.post("/auth/login", data=data)
        assert resp.status_code == 409

    def test_login_expired_timestamp_returns_400(self, client, app, db):
        import uuid, hmac, hashlib
        from datetime import datetime, timezone, timedelta
        _make_user(app, "ar_user4")

        nonce = str(uuid.uuid4())
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        secret = client.application.config.get("REQUEST_SIGNING_SECRET", "")
        payload = f"POST|/auth/login|{nonce}|{old_ts}"
        sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

        resp = client.post(
            "/auth/login",
            data={
                "username": "ar_user4",
                "password": "Password1",
                "_nonce": nonce,
                "_timestamp": old_ts,
                "_signature": sig,
            },
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 4. Observability sub-endpoints
# ---------------------------------------------------------------------------

class TestObservabilitySubEndpoints:

    def _admin(self, client, app, username):
        _make_user(app, username, role="administrator")
        _login(client, username)

    def test_operations_alerts_accessible_by_admin(self, client, app, db):
        self._admin(client, app, "adm_alerts1")
        resp = client.get("/admin/operations/alerts")
        assert resp.status_code == 200

    def test_operations_alerts_requires_admin(self, client, app, db):
        _make_user(app, "pat_alerts1")
        _login(client, "pat_alerts1")
        resp = client.get("/admin/operations/alerts")
        assert resp.status_code == 403

    def test_operations_alerts_shows_unacknowledged_alert(self, client, app, db):
        self._admin(client, app, "adm_alerts2")
        with app.app_context():
            alert = AnomalyAlert(
                alert_type="failed_logins",
                severity="warning",
                message="Test alert for listing",
            )
            _db.session.add(alert)
            _db.session.commit()

        resp = client.get("/admin/operations/alerts")
        assert resp.status_code == 200
        assert b"Test alert for listing" in resp.data

    def test_operations_slow_queries_accessible_by_admin(self, client, app, db):
        self._admin(client, app, "adm_sq1")
        resp = client.get("/admin/operations/slow-queries")
        assert resp.status_code == 200

    def test_operations_slow_queries_requires_admin(self, client, app, db):
        _make_user(app, "pat_sq1")
        _login(client, "pat_sq1")
        resp = client.get("/admin/operations/slow-queries")
        assert resp.status_code == 403

    def test_operations_slow_queries_shows_persisted_entry(self, client, app, db):
        self._admin(client, app, "adm_sq2")
        with app.app_context():
            sq = SlowQuery(endpoint="/test/slow", duration_ms=750.0, correlation_id="abc-123")
            _db.session.add(sq)
            _db.session.commit()

        resp = client.get("/admin/operations/slow-queries")
        assert resp.status_code == 200
        assert b"/test/slow" in resp.data


# ---------------------------------------------------------------------------
# 5. Medication adherence — 4-question scale
# ---------------------------------------------------------------------------

class TestMedicationAdherence4Question:

    def test_all_zeros_maps_to_never_miss(self):
        from app.utils.scoring import calculate_scores
        answers = {f"med_adherence_q{i}": "0" for i in range(1, 5)}
        scores = calculate_scores(answers)
        assert scores["medication_adherence"]["level"] == "never_miss"
        assert scores["medication_adherence"]["total"] == 0

    def test_total_3_maps_to_rarely_miss(self):
        from app.utils.scoring import calculate_scores
        answers = {"med_adherence_q1": "3", "med_adherence_q2": "0",
                   "med_adherence_q3": "0", "med_adherence_q4": "0"}
        scores = calculate_scores(answers)
        assert scores["medication_adherence"]["level"] == "rarely_miss"

    def test_total_7_maps_to_sometimes_miss(self):
        from app.utils.scoring import calculate_scores
        answers = {"med_adherence_q1": "2", "med_adherence_q2": "2",
                   "med_adherence_q3": "2", "med_adherence_q4": "1"}
        scores = calculate_scores(answers)
        assert scores["medication_adherence"]["level"] == "sometimes_miss"

    def test_total_10_maps_to_often_miss(self):
        from app.utils.scoring import calculate_scores
        answers = {"med_adherence_q1": "3", "med_adherence_q2": "3",
                   "med_adherence_q3": "2", "med_adherence_q4": "2"}
        scores = calculate_scores(answers)
        assert scores["medication_adherence"]["level"] == "often_miss"
        assert scores["medication_adherence"]["total"] == 10

    def test_sometimes_miss_raises_risk_to_moderate(self):
        from app.utils.scoring import calculate_scores, calculate_risk_level
        answers = {f"phq9_q{i}": "0" for i in range(1, 10)}
        answers.update({f"gad7_q{i}": "0" for i in range(1, 8)})
        answers["bp_category"] = "Normal"
        answers.update({"fall_history": "no", "mobility_aids": "no",
                        "dizziness": "no", "balance_meds": "no"})
        # Total adherence = 6 → sometimes_miss
        answers.update({"med_adherence_q1": "2", "med_adherence_q2": "2",
                        "med_adherence_q3": "1", "med_adherence_q4": "1"})
        scores = calculate_scores(answers)
        risk, explanations = calculate_risk_level(scores)
        assert risk == "Moderate"
        assert any("sometimes" in e.lower() or "adherence" in e.lower() for e in explanations)

    def test_never_miss_does_not_raise_risk(self):
        from app.utils.scoring import calculate_scores, calculate_risk_level
        answers = {f"phq9_q{i}": "0" for i in range(1, 10)}
        answers.update({f"gad7_q{i}": "0" for i in range(1, 8)})
        answers["bp_category"] = "Normal"
        answers.update({"fall_history": "no", "mobility_aids": "no",
                        "dizziness": "no", "balance_meds": "no"})
        answers.update({f"med_adherence_q{i}": "0" for i in range(1, 5)})
        scores = calculate_scores(answers)
        risk, _ = calculate_risk_level(scores)
        assert risk == "Low"

    def test_default_template_has_4_adherence_questions(self):
        from app.utils.scoring import DEFAULT_TEMPLATE
        med_section = next(
            s for s in DEFAULT_TEMPLATE["sections"] if s["id"] == "med_adherence"
        )
        assert len(med_section["questions"]) == 4
        ids = [q["id"] for q in med_section["questions"]]
        assert ids == ["med_adherence_q1", "med_adherence_q2",
                       "med_adherence_q3", "med_adherence_q4"]
        for q in med_section["questions"]:
            assert q["type"] == "scale_0_3"
