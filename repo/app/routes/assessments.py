import json
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.assessment import AssessmentTemplate, AssessmentResult, AssessmentDraft
from app.models.visit import Visit
from app.utils.scoring import calculate_scores, calculate_risk_level, get_or_create_default_template, validate_assessment_answers
from app.utils.auth import role_required
from app.utils.antireplay import antireplay
from app.utils.idempotency import hash_token as _hash_token

assessments_bp = Blueprint("assessments", __name__, url_prefix="/assessments")

TOTAL_STEPS = 5  # PHQ-9, GAD-7, BP, Fall Risk, Med Adherence


def _validation_error_response(errors, fallback_redirect):
    """Return a validation-error response for both HTMX and plain-HTTP callers.

    HTMX callers receive a 422 HTML fragment; plain-HTTP callers get flash
    messages and the provided redirect.
    """
    if request.headers.get("HX-Request"):
        error_html = "".join(f"<p>{e}</p>" for e in errors)
        return f"<div class='alert alert-danger'>{error_html}</div>", 422
    for e in errors:
        flash(e, "danger")
    return fallback_redirect


@assessments_bp.route("/start")
@assessments_bp.route("/start/<int:visit_id>")
@role_required("patient")
def start(visit_id=None):
    template = get_or_create_default_template(db.session)
    sections = template.questions

    # Check for existing draft
    draft = AssessmentDraft.query.filter_by(
        patient_id=current_user.id,
        visit_id=visit_id,
        template_id=template.id,
    ).first()

    current_step = draft.current_step if draft else 0
    saved_answers = json.loads(draft.partial_answers_json) if draft else {}
    request_token = str(uuid.uuid4())

    return render_template(
        "assessments/wizard.html",
        template=template,
        sections=sections,
        section=sections[current_step],
        step=current_step,
        current_step=current_step,
        total_steps=TOTAL_STEPS,
        visit_id=visit_id,
        saved_answers=saved_answers,
        request_token=request_token,
    )


@assessments_bp.route("/step/<int:step>", methods=["POST"])
@role_required("patient")
def wizard_step(step):
    template = get_or_create_default_template(db.session)
    sections = template.questions
    visit_id = request.form.get("visit_id", type=int)

    # Collect all answers from form
    answers = {}
    for key, val in request.form.items():
        if key not in ("csrf_token", "visit_id", "request_token", "step"):
            answers[key] = val

    # Save draft
    draft = AssessmentDraft.query.filter_by(
        patient_id=current_user.id,
        visit_id=visit_id,
        template_id=template.id,
    ).first()

    if draft:
        existing = json.loads(draft.partial_answers_json)
        existing.update(answers)
        draft.partial_answers_json = json.dumps(existing)
        draft.current_step = step
    else:
        draft = AssessmentDraft(
            patient_id=current_user.id,
            visit_id=visit_id,
            template_id=template.id,
            partial_answers_json=json.dumps(answers),
            current_step=step,
        )
        db.session.add(draft)
    db.session.commit()

    saved_answers = json.loads(draft.partial_answers_json)
    request_token = request.form.get("request_token", str(uuid.uuid4()))

    if step >= TOTAL_STEPS:
        # Show review page
        return render_template(
            "assessments/_review.html",
            template=template,
            sections=sections,
            answers=saved_answers,
            visit_id=visit_id,
            request_token=request_token,
        )

    return render_template(
        "assessments/_step.html",
        template=template,
        section=sections[step],
        step=step,
        total_steps=TOTAL_STEPS,
        visit_id=visit_id,
        saved_answers=saved_answers,
        request_token=request_token,
    )


@assessments_bp.route("/submit", methods=["POST"])
@role_required("patient")
@antireplay
def submit():
    template = get_or_create_default_template(db.session)
    visit_id = request.form.get("visit_id", type=int)
    request_token = request.form.get("request_token", "")

    # Validate visit_id if provided
    if visit_id is not None:
        visit = db.session.get(Visit, visit_id)
        if visit is None:
            flash("Invalid visit: not found.", "danger")
            return redirect(url_for("assessments.start", visit_id=visit_id))
        if visit.patient_id != current_user.id:
            flash("Invalid visit: access denied.", "danger")
            return redirect(url_for("assessments.start"))

    # Idempotency check — compare against stored hash, not raw token.
    if request_token:
        token_hash = _hash_token(request_token)
        existing = AssessmentResult.query.filter_by(request_token=token_hash).first()
        if existing:
            return redirect(url_for("assessments.result", assessment_id=existing.id))

    # Get answers from draft
    draft = AssessmentDraft.query.filter_by(
        patient_id=current_user.id,
        visit_id=visit_id,
        template_id=template.id,
    ).first()

    if not draft:
        flash("No assessment data found. Please start again.", "danger")
        return redirect(url_for("assessments.start", visit_id=visit_id))

    answers = json.loads(draft.partial_answers_json)

    # Server-side validation — prevents 500 on malformed/out-of-range values.
    validation_errors = validate_assessment_answers(answers)
    if validation_errors:
        return _validation_error_response(
            validation_errors,
            redirect(url_for("assessments.start", visit_id=visit_id)),
        )

    scores = calculate_scores(answers)
    risk_level, explanations = calculate_risk_level(scores)

    result = AssessmentResult(
        patient_id=current_user.id,
        visit_id=visit_id,
        template_id=template.id,
        template_version=template.version,
        answers_json=json.dumps(answers),
        scores_json=json.dumps(scores),
        risk_level=risk_level,
        explanation_snapshot_json=json.dumps(explanations),
        # Store SHA-256 hash of token — raw value never persisted.
        request_token=_hash_token(request_token) if request_token else None,
    )
    db.session.add(result)
    db.session.delete(draft)
    db.session.commit()

    if request.headers.get("HX-Request"):
        resp = jsonify({"redirect": url_for("assessments.result", assessment_id=result.id)})
        resp.headers["HX-Redirect"] = url_for("assessments.result", assessment_id=result.id)
        return resp
    return redirect(url_for("assessments.result", assessment_id=result.id))


@assessments_bp.route("/result/<int:assessment_id>")
@login_required
def result(assessment_id):
    assessment = db.session.get(AssessmentResult, assessment_id)
    if not assessment:
        flash("Assessment not found.", "danger")
        return redirect(url_for("assessments.history"))

    # Access check: patient can see own, staff can see assigned
    if current_user.role == "patient" and assessment.patient_id != current_user.id:
        flash("Access denied.", "danger")
        return redirect(url_for("assessments.history"))

    return render_template(
        "assessments/result.html",
        assessment=assessment,
        scores=assessment.scores,
        explanations=assessment.explanation,
    )


@assessments_bp.route("/history")
@login_required
def history():
    if current_user.role == "patient":
        results = AssessmentResult.query.filter_by(
            patient_id=current_user.id
        ).order_by(AssessmentResult.submitted_at.desc()).all()
    else:
        results = []
    return render_template("assessments/history.html", results=results)


@assessments_bp.route("/save-draft", methods=["POST"])
@role_required("patient")
def save_draft():
    template = get_or_create_default_template(db.session)
    visit_id = request.form.get("visit_id", type=int)
    answers = {}
    for key, val in request.form.items():
        if key not in ("csrf_token", "visit_id", "request_token", "step"):
            answers[key] = val

    draft = AssessmentDraft.query.filter_by(
        patient_id=current_user.id,
        visit_id=visit_id,
        template_id=template.id,
    ).first()

    if draft:
        existing = json.loads(draft.partial_answers_json)
        existing.update(answers)
        draft.partial_answers_json = json.dumps(existing)
    else:
        draft = AssessmentDraft(
            patient_id=current_user.id,
            visit_id=visit_id,
            template_id=template.id,
            partial_answers_json=json.dumps(answers),
        )
        db.session.add(draft)
    db.session.commit()
    return '<span class="field-success">Draft saved</span>'


# ── On-behalf assessment routes (administrator / front_desk only) ──

def _get_behalf_patient(patient_id):
    """Return (User, None) if patient_id resolves to a patient-role user,
    otherwise return (None, redirect_response)."""
    from app.models.user import User
    patient = db.session.get(User, patient_id)
    if not patient:
        flash("Patient not found.", "danger")
        return None, redirect(url_for("staff.patient_list"))
    if patient.role != "patient":
        flash("Selected user is not a patient.", "danger")
        return None, redirect(url_for("staff.patient_list"))
    return patient, None


@assessments_bp.route("/behalf/<int:patient_id>/start")
@role_required("administrator", "front_desk")
def behalf_start(patient_id):
    """Staff starts an assessment wizard on behalf of a patient."""
    patient, err = _get_behalf_patient(patient_id)
    if err:
        return err

    template = get_or_create_default_template(db.session)
    sections = template.questions

    draft = AssessmentDraft.query.filter_by(
        patient_id=patient_id,
        visit_id=None,
        template_id=template.id,
    ).first()

    current_step = draft.current_step if draft else 0
    saved_answers = json.loads(draft.partial_answers_json) if draft else {}
    request_token = str(uuid.uuid4())

    return render_template(
        "assessments/behalf_wizard.html",
        template=template,
        sections=sections,
        section=sections[current_step],
        step=current_step,
        current_step=current_step,
        total_steps=TOTAL_STEPS,
        saved_answers=saved_answers,
        request_token=request_token,
        patient=patient,
    )


@assessments_bp.route("/behalf/<int:patient_id>/step/<int:step>", methods=["POST"])
@role_required("administrator", "front_desk")
def behalf_step(patient_id, step):
    """Staff saves a wizard step for a patient's in-progress draft."""
    patient, err = _get_behalf_patient(patient_id)
    if err:
        return err

    template = get_or_create_default_template(db.session)
    sections = template.questions

    answers = {}
    for key, val in request.form.items():
        if key not in ("csrf_token", "request_token", "step"):
            answers[key] = val

    draft = AssessmentDraft.query.filter_by(
        patient_id=patient_id,
        visit_id=None,
        template_id=template.id,
    ).first()

    if draft:
        existing = json.loads(draft.partial_answers_json)
        existing.update(answers)
        draft.partial_answers_json = json.dumps(existing)
        draft.current_step = step
    else:
        draft = AssessmentDraft(
            patient_id=patient_id,
            visit_id=None,
            template_id=template.id,
            partial_answers_json=json.dumps(answers),
            current_step=step,
        )
        db.session.add(draft)
    db.session.commit()

    saved_answers = json.loads(draft.partial_answers_json)
    request_token = request.form.get("request_token", str(uuid.uuid4()))

    if step >= TOTAL_STEPS:
        return render_template(
            "assessments/_behalf_review.html",
            template=template,
            sections=sections,
            answers=saved_answers,
            request_token=request_token,
            patient=patient,
        )

    return render_template(
        "assessments/_behalf_step.html",
        template=template,
        section=sections[step],
        step=step,
        total_steps=TOTAL_STEPS,
        saved_answers=saved_answers,
        request_token=request_token,
        patient=patient,
    )


@assessments_bp.route("/behalf/<int:patient_id>/submit", methods=["POST"])
@role_required("administrator", "front_desk")
@antireplay
def behalf_submit(patient_id):
    """Staff submits completed assessment; result is owned by the patient."""
    from app.utils.audit import log_action

    patient, err = _get_behalf_patient(patient_id)
    if err:
        return err

    template = get_or_create_default_template(db.session)
    request_token = request.form.get("request_token", "")

    # Idempotency — compare against stored hash, not raw token.
    if request_token:
        token_hash = _hash_token(request_token)
        existing = AssessmentResult.query.filter_by(request_token=token_hash).first()
        if existing:
            return redirect(url_for("assessments.result", assessment_id=existing.id))

    draft = AssessmentDraft.query.filter_by(
        patient_id=patient_id,
        visit_id=None,
        template_id=template.id,
    ).first()

    if not draft:
        flash("No assessment data found. Please start again.", "danger")
        return redirect(url_for("assessments.behalf_start", patient_id=patient_id))

    answers = json.loads(draft.partial_answers_json)

    # Server-side validation — same guard as the patient submit path.
    validation_errors = validate_assessment_answers(answers)
    if validation_errors:
        return _validation_error_response(
            validation_errors,
            redirect(url_for("assessments.behalf_start", patient_id=patient_id)),
        )

    scores = calculate_scores(answers)
    risk_level, explanations = calculate_risk_level(scores)

    result = AssessmentResult(
        patient_id=patient_id,
        visit_id=None,
        template_id=template.id,
        template_version=template.version,
        answers_json=json.dumps(answers),
        scores_json=json.dumps(scores),
        risk_level=risk_level,
        explanation_snapshot_json=json.dumps(explanations),
        request_token=_hash_token(request_token) if request_token else None,
    )
    db.session.add(result)
    db.session.delete(draft)
    db.session.commit()

    log_action(
        action="on_behalf_assessment",
        resource_type="assessment_result",
        resource_id=result.id,
        details={
            "actor_id": current_user.id,
            "actor_role": current_user.role,
            "patient_id": patient_id,
            "risk_level": risk_level,
            "context": "staff submitted assessment on behalf of patient",
        },
    )

    return redirect(url_for("assessments.result", assessment_id=result.id))


# Staff view of patient assessments
@assessments_bp.route("/patient/<int:patient_id>")
@role_required("administrator", "clinician", "front_desk")
def patient_assessments(patient_id):
    results = AssessmentResult.query.filter_by(
        patient_id=patient_id
    ).order_by(AssessmentResult.submitted_at.desc()).all()
    from app.models.user import User
    patient = db.session.get(User, patient_id)
    return render_template("assessments/patient_history.html", results=results, patient=patient)
