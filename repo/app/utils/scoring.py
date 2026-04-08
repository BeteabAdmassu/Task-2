"""Risk stratification scoring engine."""

import json


def calculate_scores(answers):
    """Calculate individual scale scores from answers dict."""
    scores = {}

    # PHQ-9: sum of 9 questions (0-3 each, total 0-27)
    phq9_total = sum(int(answers.get(f"phq9_q{i}", 0)) for i in range(1, 10))
    if phq9_total <= 4:
        phq9_severity = "Minimal"
    elif phq9_total <= 9:
        phq9_severity = "Mild"
    elif phq9_total <= 14:
        phq9_severity = "Moderate"
    elif phq9_total <= 19:
        phq9_severity = "Moderately Severe"
    else:
        phq9_severity = "Severe"
    scores["phq9"] = {"total": phq9_total, "severity": phq9_severity}

    # GAD-7: sum of 7 questions (0-3 each, total 0-21)
    gad7_total = sum(int(answers.get(f"gad7_q{i}", 0)) for i in range(1, 8))
    if gad7_total <= 4:
        gad7_severity = "Minimal"
    elif gad7_total <= 9:
        gad7_severity = "Mild"
    elif gad7_total <= 14:
        gad7_severity = "Moderate"
    else:
        gad7_severity = "Severe"
    scores["gad7"] = {"total": gad7_total, "severity": gad7_severity}

    # Blood pressure
    bp_category = answers.get("bp_category", "Normal")
    scores["blood_pressure"] = {"category": bp_category}

    # Fall risk: count of Yes answers
    fall_risk_flags = sum(
        1 for q in ["fall_history", "mobility_aids", "dizziness", "balance_meds"]
        if answers.get(q) == "yes"
    )
    scores["fall_risk"] = {"flags": fall_risk_flags, "total_questions": 4}

    # Medication adherence: 4-question scale (each 0-3, total 0-12)
    med_total = sum(int(answers.get(f"med_adherence_q{i}", 0)) for i in range(1, 5))
    if med_total <= 2:
        adherence_level = "never_miss"
    elif med_total <= 5:
        adherence_level = "rarely_miss"
    elif med_total <= 8:
        adherence_level = "sometimes_miss"
    else:
        adherence_level = "often_miss"
    scores["medication_adherence"] = {"level": adherence_level, "total": med_total, "total_questions": 4}

    return scores


def calculate_risk_level(scores):
    """Determine overall risk level and generate explanation."""
    risk_level = "Low"
    explanations = []

    phq9 = scores.get("phq9", {})
    gad7 = scores.get("gad7", {})
    bp = scores.get("blood_pressure", {})
    fall = scores.get("fall_risk", {})
    med = scores.get("medication_adherence", {})

    # High risk rules
    if phq9.get("total", 0) >= 15:
        risk_level = "High"
        explanations.append(f"PHQ-9 score {phq9['total']} ({phq9['severity']}) >= 15 threshold")

    if gad7.get("total", 0) >= 15:
        risk_level = "High"
        explanations.append(f"GAD-7 score {gad7['total']} ({gad7['severity']}) >= 15 threshold")

    if bp.get("category") == "Crisis":
        risk_level = "High"
        explanations.append("Blood pressure category: Crisis")

    if fall.get("flags", 0) >= 2:
        if risk_level != "High":
            risk_level = "High"
        explanations.append(f"Fall risk: {fall['flags']} flags (>= 2 threshold)")

    # Moderate risk rules (only upgrade if currently Low)
    if risk_level == "Low":
        if phq9.get("total", 0) >= 10:
            risk_level = "Moderate"
            explanations.append(f"PHQ-9 score {phq9['total']} ({phq9['severity']}) >= 10 threshold")

        if gad7.get("total", 0) >= 10:
            risk_level = "Moderate"
            explanations.append(f"GAD-7 score {gad7['total']} ({gad7['severity']}) >= 10 threshold")

        if bp.get("category") in ("Stage 1", "Stage 2"):
            risk_level = "Moderate"
            explanations.append(f"Blood pressure category: {bp['category']}")

        if fall.get("flags", 0) >= 1:
            risk_level = "Moderate"
            explanations.append(f"Fall risk: {fall['flags']} flag(s)")

        if med.get("level") in ("sometimes_miss", "often_miss"):
            risk_level = "Moderate"
            explanations.append(f"Medication adherence: {med['level'].replace('_', ' ')}")

    if not explanations:
        explanations.append("All indicators within normal range")

    return risk_level, explanations


# Default assessment template data
DEFAULT_TEMPLATE = {
    "name": "Standard Pre-Visit Assessment",
    "version": 1,
    "sections": [
        {
            "id": "phq9",
            "title": "PHQ-9 Depression Screening",
            "description": "Over the last 2 weeks, how often have you been bothered by the following?",
            "questions": [
                {"id": "phq9_q1", "text": "Little interest or pleasure in doing things", "type": "scale_0_3"},
                {"id": "phq9_q2", "text": "Feeling down, depressed, or hopeless", "type": "scale_0_3"},
                {"id": "phq9_q3", "text": "Trouble falling/staying asleep, or sleeping too much", "type": "scale_0_3"},
                {"id": "phq9_q4", "text": "Feeling tired or having little energy", "type": "scale_0_3"},
                {"id": "phq9_q5", "text": "Poor appetite or overeating", "type": "scale_0_3"},
                {"id": "phq9_q6", "text": "Feeling bad about yourself or that you are a failure", "type": "scale_0_3"},
                {"id": "phq9_q7", "text": "Trouble concentrating on things", "type": "scale_0_3"},
                {"id": "phq9_q8", "text": "Moving or speaking slowly, or being fidgety/restless", "type": "scale_0_3"},
                {"id": "phq9_q9", "text": "Thoughts that you would be better off dead or of hurting yourself", "type": "scale_0_3"},
            ],
        },
        {
            "id": "gad7",
            "title": "GAD-7 Anxiety Screening",
            "description": "Over the last 2 weeks, how often have you been bothered by the following?",
            "questions": [
                {"id": "gad7_q1", "text": "Feeling nervous, anxious, or on edge", "type": "scale_0_3"},
                {"id": "gad7_q2", "text": "Not being able to stop or control worrying", "type": "scale_0_3"},
                {"id": "gad7_q3", "text": "Worrying too much about different things", "type": "scale_0_3"},
                {"id": "gad7_q4", "text": "Trouble relaxing", "type": "scale_0_3"},
                {"id": "gad7_q5", "text": "Being so restless that it's hard to sit still", "type": "scale_0_3"},
                {"id": "gad7_q6", "text": "Becoming easily annoyed or irritable", "type": "scale_0_3"},
                {"id": "gad7_q7", "text": "Feeling afraid as if something awful might happen", "type": "scale_0_3"},
            ],
        },
        {
            "id": "bp",
            "title": "Blood Pressure",
            "description": "Select your most recent blood pressure category.",
            "questions": [
                {
                    "id": "bp_category",
                    "text": "Blood pressure category",
                    "type": "select",
                    "options": ["Normal", "Elevated", "Stage 1", "Stage 2", "Crisis"],
                },
            ],
        },
        {
            "id": "fall_risk",
            "title": "Fall Risk Assessment",
            "description": "Answer the following fall risk questions.",
            "questions": [
                {"id": "fall_history", "text": "Have you fallen in the past 6 months?", "type": "yes_no"},
                {"id": "mobility_aids", "text": "Do you use a cane, walker, or wheelchair?", "type": "yes_no"},
                {"id": "dizziness", "text": "Do you experience dizziness or lightheadedness?", "type": "yes_no"},
                {"id": "balance_meds", "text": "Do you take medications that may affect balance?", "type": "yes_no"},
            ],
        },
        {
            "id": "med_adherence",
            "title": "Medication Adherence",
            "description": "Over the last 2 weeks, how often have you experienced the following? (0 = Never, 1 = Rarely, 2 = Sometimes, 3 = Often)",
            "questions": [
                {"id": "med_adherence_q1", "text": "Forgot to take your prescribed medications", "type": "scale_0_3"},
                {"id": "med_adherence_q2", "text": "Decided to skip a dose of your medications", "type": "scale_0_3"},
                {"id": "med_adherence_q3", "text": "Ran out of medication before getting a refill", "type": "scale_0_3"},
                {"id": "med_adherence_q4", "text": "Missed medications due to side effects or feeling unwell", "type": "scale_0_3"},
            ],
        },
    ],
}


def get_or_create_default_template(db_session):
    """Get or create the default assessment template."""
    from app.models.assessment import AssessmentTemplate

    template = AssessmentTemplate.query.filter_by(
        name=DEFAULT_TEMPLATE["name"], version=DEFAULT_TEMPLATE["version"]
    ).first()
    if not template:
        template = AssessmentTemplate(
            name=DEFAULT_TEMPLATE["name"],
            version=DEFAULT_TEMPLATE["version"],
            questions_json=json.dumps(DEFAULT_TEMPLATE["sections"]),
            scoring_rules_json=json.dumps({
                "high_rules": [
                    "PHQ-9 >= 15", "GAD-7 >= 15", "BP = Crisis", "Fall risk >= 2 flags"
                ],
                "moderate_rules": [
                    "PHQ-9 >= 10", "GAD-7 >= 10", "BP = Stage 1 or Stage 2",
                    "Fall risk >= 1 flag", "Medication: sometimes or often miss"
                ],
            }),
        )
        db_session.add(template)
        db_session.commit()
    return template
