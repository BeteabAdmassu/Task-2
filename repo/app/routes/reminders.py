from datetime import datetime, timezone
from flask import Blueprint, render_template, flash, redirect, url_for, request
from flask_login import current_user, login_required
from app.extensions import db
from app.models.reminder import Reminder
from app.utils.auth import role_required
from app.utils.reminders import generate_pending_reminders

reminders_bp = Blueprint("reminders", __name__, url_prefix="/reminders")


@reminders_bp.route("")
@login_required
def my_reminders():
    generate_pending_reminders()
    reminders = Reminder.query.filter_by(
        patient_id=current_user.id,
        status="pending",
    ).order_by(Reminder.due_date.asc()).all()
    return render_template("reminders/list.html", reminders=reminders)


@reminders_bp.route("/<int:reminder_id>/dismiss", methods=["POST"])
@login_required
def dismiss(reminder_id):
    reminder = db.session.get(Reminder, reminder_id)
    if not reminder:
        flash("Reminder not found.", "danger")
        return redirect(url_for("reminders.my_reminders"))
    if reminder.patient_id != current_user.id and current_user.role != "administrator":
        flash("Access denied.", "danger")
        return redirect(url_for("reminders.my_reminders"))
    reminder.status = "dismissed"
    reminder.dismissed_at = datetime.now(timezone.utc)
    db.session.commit()
    flash("Reminder dismissed.", "success")
    return redirect(url_for("reminders.my_reminders"))


@reminders_bp.route("/admin")
@role_required("administrator")
def admin_reminders():
    reminders = Reminder.query.order_by(Reminder.due_date.asc()).all()
    return render_template("reminders/admin.html", reminders=reminders)


@reminders_bp.route("/patient/count")
@login_required
def reminder_count():
    """Return badge count of pending reminders (for HTMX polling)."""
    count = Reminder.query.filter_by(
        patient_id=current_user.id,
        status="pending",
    ).count()
    if count > 0:
        return f'<span class="badge badge-danger">{count}</span>'
    return ""


@reminders_bp.route("/admin/config")
@role_required("administrator")
def admin_config():
    """Admin page showing reassessment interval configuration."""
    # Default config — in a real app this would come from a DB table
    config = {"reassessment_interval_days": 90}
    return render_template("reminders/config.html", config=config)


@reminders_bp.route("/admin/config/<int:template_id>", methods=["POST"])
@role_required("administrator")
def update_config(template_id):
    """Update reassessment interval for a template (stub — stores default 90 days)."""
    interval = request.form.get("interval_days", 90, type=int)
    # In a real app, persist to a config table keyed by template_id
    flash(f"Reassessment interval updated to {interval} days for template {template_id}.", "success")
    return redirect(url_for("reminders.admin_config"))
