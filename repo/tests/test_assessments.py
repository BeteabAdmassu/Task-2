"""Tests for prompt 05 — health assessments & risk stratification."""

import json
import pytest
from app.models.user import User
from app.models.assessment import AssessmentResult, AssessmentDraft
from app.extensions import db
from app.utils.scoring import calculate_scores, calculate_risk_level


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
    resp = client.post("/assessments/submit", data={"request_token": "tok-full"}, follow_redirects=True)
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

    client.post("/assessments/submit", data={"request_token": "tok-idem"}, follow_redirects=True)
    # Submit again with same token
    resp = client.post("/assessments/submit", data={"request_token": "tok-idem"}, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        count = AssessmentResult.query.filter_by(request_token="tok-idem").count()
        assert count == 1


def test_assessment_result_view(client, app):
    pid = _create_user(app, "pat_a5")
    _login(client, "pat_a5")
    client.get("/assessments/start")
    all_data = dict(LOW_RISK_ANSWERS)
    all_data["request_token"] = "tok-result"
    for step in range(1, 6):
        client.post(f"/assessments/step/{step}", data=all_data)
    client.post("/assessments/submit", data={"request_token": "tok-result"}, follow_redirects=True)

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
    client.post("/assessments/submit", data={"request_token": "tok-staff"}, follow_redirects=True)
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
