from datetime import date
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort
from flask_login import current_user, login_required
from app.extensions import db
from app.models.visit import Visit, VisitTransition
from app.utils.auth import role_required
from app.utils.state_machine import transition_visit, VALID_TRANSITIONS, TERMINAL_STATES
from app.utils.audit import log_action
from app.utils.antireplay import antireplay

visits_bp = Blueprint("visits", __name__, url_prefix="/visits")


@visits_bp.route("/dashboard")
@role_required("administrator", "clinician", "front_desk")
def dashboard():
    today = date.today()
    visits = Visit.query.filter(
        db.func.date(Visit.created_at) <= today
    ).order_by(Visit.created_at.desc()).all()
    return render_template(
        "visits/dashboard.html",
        visits=visits,
        valid_transitions=VALID_TRANSITIONS,
        terminal_states=TERMINAL_STATES,
    )


@visits_bp.route("/dashboard/poll")
@role_required("administrator", "clinician", "front_desk")
def dashboard_poll():
    today = date.today()
    visits = Visit.query.filter(
        db.func.date(Visit.created_at) <= today
    ).order_by(Visit.created_at.desc()).all()
    return render_template(
        "visits/_visit_rows.html",
        visits=visits,
        valid_transitions=VALID_TRANSITIONS,
        terminal_states=TERMINAL_STATES,
    )


@visits_bp.route("/<int:visit_id>/transition", methods=["POST"])
@role_required("administrator", "clinician", "front_desk")
@antireplay
def transition(visit_id):
    visit = db.session.get(Visit, visit_id)
    if not visit:
        flash("Visit not found.", "danger")
        return redirect(url_for("visits.dashboard"))

    target_state = request.form.get("target_state", "").strip()
    reason = request.form.get("reason", "").strip() or None
    request_token = request.form.get("request_token", "").strip() or None

    try:
        t = transition_visit(visit, target_state, current_user.id, reason=reason, request_token=request_token)
        log_action("visit_transition", "visit", visit.id, {
            "from": t.from_status, "to": t.to_status, "reason": reason
        })
        flash(f"Visit transitioned to {target_state}.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    if request.headers.get("HX-Request"):
        visits = Visit.query.order_by(Visit.created_at.desc()).all()
        return render_template(
            "visits/_visit_rows.html",
            visits=visits,
            valid_transitions=VALID_TRANSITIONS,
            terminal_states=TERMINAL_STATES,
        )
    return redirect(url_for("visits.dashboard"))


@visits_bp.route("/<int:visit_id>/timeline")
@login_required
def timeline(visit_id):
    visit = db.session.get(Visit, visit_id)
    if not visit:
        return "Visit not found", 404
    staff_roles = ("administrator", "clinician", "front_desk")
    if current_user.role not in staff_roles and visit.patient_id != current_user.id:
        abort(403)
    transitions = VisitTransition.query.filter_by(visit_id=visit_id).order_by(VisitTransition.timestamp.asc()).all()
    return render_template("visits/_timeline.html", visit=visit, transitions=transitions)
