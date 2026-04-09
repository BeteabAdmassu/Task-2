"""Tests for prompt 05 — health assessments & risk stratification."""

import json
import pytest
from app.models.user import User
from app.models.assessment import AssessmentResult, AssessmentDraft
from app.models.visit import Visit
from app.models.scheduling import Clinician
from app.extensions import db
from app.utils.scoring import calculate_scores, calculate_risk_level
from tests.signing_helpers import signed_data, login_data

_SUBMIT_PATH = "/assessments/submit"


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


LOW_RISK_ANSWERS = {
    **{f"phq9_q{i}": "0" for i in range(1, 10)},
    **{f"gad7_q{i}": "0" for i in range(1, 8)},
    "bp_category": "Normal",
    "fall_history": "no", "mobility_aids": "no", "dizziness": "no", "balance_meds": "no",
    "med_adherence": "never_miss",
}

HIGH_RISK_ANSWERS = {
    **{f"phq9_q{i}": "3" for i in range(1, 10)},
    **{f"gad7_q{i}": "3" for i in range(1, 8)},
    "bp_category": "Crisis",
    "fall_history": "yes", "mobility_aids": "yes", "dizziness": "yes", "balance_meds": "yes",
    "med_adherence": "often_miss",
}


# ── Scoring engine unit tests ──

def test_scoring_low_risk():
    scores = calculate_scores(LOW_RISK_ANSWERS)
    risk, explanations = calculate_risk_level(scores)
    assert risk == "Low"
    assert scores["phq9"]["total"] == 0
    assert scores["gad7"]["total"] == 0


def test_scoring_high_risk():
    scores = calculate_scores(HIGH_RISK_ANSWERS)
    risk, explanations = calculate_risk_level(scores)
    assert risk == "High"
    assert scores["phq9"]["total"] == 27
    assert scores["gad7"]["total"] == 21
    assert len(explanations) >= 3


def test_scoring_moderate_phq9():
    answers = dict(LOW_RISK_ANSWERS)
    # PHQ-9 total = 12 (moderate)
    for i in range(1, 5):
        answers[f"phq9_q{i}"] = "3"
    scores = calculate_scores(answers)
    risk, _ = calculate_risk_level(scores)
    assert risk == "Moderate"


def test_scoring_moderate_bp():
    answers = dict(LOW_RISK_ANSWERS)
    answers["bp_category"] = "Stage 1"
    scores = calculate_scores(answers)
    risk, _ = calculate_risk_level(scores)
    assert risk == "Moderate"


def test_scoring_high_fall_risk():
    answers = dict(LOW_RISK_ANSWERS)
    answers["fall_history"] = "yes"
    answers["dizziness"] = "yes"
    scores = calculate_scores(answers)
    risk, _ = calculate_risk_level(scores)
    assert risk == "High"


def test_phq9_severity_labels():
    for total, expected in [(0, "Minimal"), (5, "Mild"), (10, "Moderate"), (15, "Moderately Severe"), (20, "Severe")]:
        answers = dict(LOW_RISK_ANSWERS)
        remaining = total
        for i in range(1, 10):
            val = min(3, remaining)
            answers[f"phq9_q{i}"] = str(val)
            remaining -= val
        scores = calculate_scores(answers)
        assert scores["phq9"]["severity"] == expected, f"Expected {expected} for total {total}"


# ── Route tests ──

def test_assessment_start_page(client, app):
    _create_user(app, "pat_a1")
    _login(client, "pat_a1")
    resp = client.get("/assessments/start")
    assert resp.status_code == 200
    assert b"Health Assessment" in resp.data


def test_assessment_wizard_step(client, app):
    _create_user(app, "pat_a2")
    _login(client, "pat_a2")
    client.get("/assessments/start")

    # Submit step 1 (PHQ-9)
    data = {f"phq9_q{i}": "0" for i in range(1, 10)}
    data["request_token"] = "test-token-1"
    resp = client.post("/assessments/step/1", data=data)
    assert resp.status_code == 200


def test_full_assessment_submission(client, app):
    _create_user(app, "pat_a3")
    _login(client, "pat_a3")
    client.get("/assessments/start")

    # Walk through all steps
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "tok-full"

    for step in range(1, 6):
        resp = client.post(f"/assessments/step/{step}", data=all_data)
        assert resp.status_code == 200

    # Submit
    resp = client.post("/assessments/submit", data=signed_data("POST", _SUBMIT_PATH, {"request_token": "tok-full"}), follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        results = AssessmentResult.query.filter_by(
            patient_id=User.query.filter_by(username="pat_a3").first().id
        ).all()
        assert len(results) == 1
        assert results[0].risk_level == "Low"


def test_assessment_idempotency(client, app):
    _create_user(app, "pat_a4")
    _login(client, "pat_a4")
    client.get("/assessments/start")

    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "tok-idem"

    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)

    client.post("/assessments/submit", data=signed_data("POST", _SUBMIT_PATH, {"request_token": "tok-idem"}), follow_redirects=True)
    # Submit again with same token (different nonce — idempotency key is request_token, not nonce)
    resp = client.post("/assessments/submit", data=signed_data("POST", _SUBMIT_PATH, {"request_token": "tok-idem"}), follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        # Token is stored hashed — query by patient to verify only one result.
        import hashlib
        token_hash = hashlib.sha256("tok-idem".encode()).hexdigest()
        count = AssessmentResult.query.filter_by(request_token=token_hash).count()
        assert count == 1


def test_assessment_result_view(client, app):
    pid = _create_user(app, "pat_a5")
    _login(client, "pat_a5")
    client.get("/assessments/start")
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "tok-result"
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)
    client.post("/assessments/submit", data=signed_data("POST", _SUBMIT_PATH, {"request_token": "tok-result"}), follow_redirects=True)

    with app.app_context():
        result = AssessmentResult.query.first()
        resp = client.get(f"/assessments/result/{result.id}")
        assert resp.status_code == 200
        assert b"Low" in resp.data


def test_assessment_history(client, app):
    _create_user(app, "pat_a6")
    _login(client, "pat_a6")
    resp = client.get("/assessments/history")
    assert resp.status_code == 200
    assert b"Assessment History" in resp.data


def test_staff_can_view_patient_assessments(client, app):
    pid = _create_user(app, "pat_a7")
    _create_user(app, "clin_a1", role="clinician")

    _login(client, "pat_a7")
    client.get("/assessments/start")
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "tok-staff"
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)
    client.post("/assessments/submit", data=signed_data("POST", _SUBMIT_PATH, {"request_token": "tok-staff"}), follow_redirects=True)
    client.post("/auth/logout")

    _login(client, "clin_a1")
    resp = client.get(f"/assessments/patient/{pid}")
    assert resp.status_code == 200


def test_save_draft(client, app):
    _create_user(app, "pat_a8")
    _login(client, "pat_a8")
    client.get("/assessments/start")

    data = {"phq9_q1": "2", "phq9_q2": "1"}
    resp = client.post("/assessments/save-draft", data=data)
    assert resp.status_code == 200
    assert b"saved" in resp.data.lower()


# ---------------------------------------------------------------------------
# visit_id validation tests
# ---------------------------------------------------------------------------

def _create_clinician_for_assessment(app, username):
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        c = Clinician(user_id=user.id)
        db.session.add(c)
        db.session.commit()
        return c.id


def _create_visit_for(app, patient_id, clinician_id):
    with app.app_context():
        visit = Visit(patient_id=patient_id, clinician_id=clinician_id, status="booked")
        db.session.add(visit)
        db.session.commit()
        return visit.id


def _fill_draft(client, visit_id=None):
    """Walk through all wizard steps so a draft exists."""
    all_data = dict(LOW_RISK_ANSWERS)
    token = "tok-visit-val"
    all_data["request_token"] = token
    if visit_id:
        all_data["visit_id"] = str(visit_id)
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)
    return token


def test_submit_rejects_nonexistent_visit_id(client, app):
    """submit() must reject a visit_id that doesn't exist in the DB."""
    _create_user(app, "pat_vv1")
    _login(client, "pat_vv1")
    _fill_draft(client)

    path = "/assessments/submit"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"request_token": "tok-visit-val", "visit_id": "99999"}),
        follow_redirects=False,
    )
    # Route redirects away (does not land on result page)
    assert resp.status_code == 302
    assert "/assessments/result" not in resp.headers.get("Location", "")


def test_submit_rejects_foreign_visit(client, app):
    """Patient A cannot bind an assessment to Patient B's visit."""
    cid = _create_clinician_for_assessment(app, "doc_fv2")
    pid_a = _create_user(app, "pat_fv2a")
    pid_b = _create_user(app, "pat_fv2b")
    vid_b = _create_visit_for(app, patient_id=pid_b, clinician_id=cid)

    _login(client, "pat_fv2a")
    _fill_draft(client)

    path = "/assessments/submit"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"request_token": "tok-visit-val", "visit_id": str(vid_b)}),
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/assessments/result" not in resp.headers.get("Location", "")


def test_submit_accepts_own_visit(client, app):
    """Patient binding assessment to their own visit must succeed."""
    cid = _create_clinician_for_assessment(app, "doc_ov2")
    pid = _create_user(app, "pat_ov2")
    vid = _create_visit_for(app, patient_id=pid, clinician_id=cid)

    _login(client, "pat_ov2")
    _fill_draft(client, visit_id=vid)

    path = "/assessments/submit"
    resp = client.post(
        path,
        data=signed_data("POST", path, {"request_token": "tok-visit-val", "visit_id": str(vid)}),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Invalid visit" not in resp.data


# ---------------------------------------------------------------------------
# Token-at-rest protection tests
# ---------------------------------------------------------------------------

def test_assessment_request_token_stored_hashed(client, app):
    """AssessmentResult.request_token must be SHA-256 hash of the raw token."""
    import hashlib
    _create_user(app, "pat_tok_hash")
    _login(client, "pat_tok_hash")
    client.get("/assessments/start")

    raw_token = "plaintext-token-should-not-appear-in-db"
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = raw_token
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)

    client.post(
        _SUBMIT_PATH,
        data=signed_data("POST", _SUBMIT_PATH, {"request_token": raw_token}),
        follow_redirects=True,
    )

    with app.app_context():
        result = AssessmentResult.query.filter_by(
            patient_id=User.query.filter_by(username="pat_tok_hash").first().id
        ).first()
        assert result is not None
        # Raw value must NOT be stored.
        assert result.request_token != raw_token
        # Must match the SHA-256 hex digest.
        expected = hashlib.sha256(raw_token.encode()).hexdigest()
        assert result.request_token == expected


def test_assessment_idempotency_still_works_with_hashed_token(client, app):
    """Duplicate submissions with the same token return the same result after hashing."""
    import hashlib
    _create_user(app, "pat_tok_idem2")
    _login(client, "pat_tok_idem2")
    client.get("/assessments/start")

    raw_token = "idempotency-test-token-xyz"
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = raw_token
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)

    # First submit — creates the result.
    resp1 = client.post(
        _SUBMIT_PATH,
        data=signed_data("POST", _SUBMIT_PATH, {"request_token": raw_token}),
        follow_redirects=True,
    )
    assert resp1.status_code == 200

    # Second submit — must be idempotent (redirects to same result, no new row).
    resp2 = client.post(
        _SUBMIT_PATH,
        data=signed_data("POST", _SUBMIT_PATH, {"request_token": raw_token}),
        follow_redirects=True,
    )
    assert resp2.status_code == 200

    with app.app_context():
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        count = AssessmentResult.query.filter_by(request_token=token_hash).count()
        assert count == 1  # exactly one result despite two submits


# ── F-01 regression: non-patient roles must be blocked from patient-flow routes ──

@pytest.mark.parametrize("role", ["clinician", "administrator", "front_desk"])
def test_non_patient_role_blocked_from_assessment_start(client, app, role):
    """Staff/admin roles must receive 403 on the patient-only /assessments/start route."""
    username = f"np_start_{role}"
    _create_user(app, username, role=role)
    _login(client, username)
    resp = client.get("/assessments/start", follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["clinician", "administrator", "front_desk"])
def test_non_patient_role_blocked_from_wizard_step(client, app, role):
    """Staff/admin roles must receive 403 on POST /assessments/step/<n>."""
    username = f"np_step_{role}"
    _create_user(app, username, role=role)
    _login(client, username)
    resp = client.post("/assessments/step/1", data={"csrf_token": "x"}, follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["clinician", "administrator", "front_desk"])
def test_non_patient_role_blocked_from_save_draft(client, app, role):
    """Staff/admin roles must receive 403 on POST /assessments/save-draft."""
    username = f"np_draft_{role}"
    _create_user(app, username, role=role)
    _login(client, username)
    resp = client.post("/assessments/save-draft", data={"csrf_token": "x"}, follow_redirects=False)
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["clinician", "administrator", "front_desk"])
def test_non_patient_role_blocked_from_submit(client, app, role):
    """Staff/admin roles must receive 403 on POST /assessments/submit."""
    username = f"np_submit_{role}"
    _create_user(app, username, role=role)
    _login(client, username)
    resp = client.post(
        _SUBMIT_PATH,
        data=signed_data("POST", _SUBMIT_PATH, {"request_token": "tok"}),
        follow_redirects=False,
    )
    assert resp.status_code == 403
