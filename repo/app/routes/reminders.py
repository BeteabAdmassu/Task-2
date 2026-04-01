from datetime import datetime, timezone
from flask import Blueprint, render_template, flash, redirect, url_for, request
from flask_login import current_user, login_required
from app.extensions import db
from app.models.reminder import Reminder, ReminderConfig
from app.utils.auth import role_required
from app.utils.reminders import generate_pending_reminders

reminders_bp = Blueprint("reminders", __name__, url_prefix="/reminders")

# Maps the integer template_id used in URLs to the semantic key stored in DB.
_TEMPLATE_KEY = {0: "reassessment"}


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
    config = {
        "reassessment_interval_days": ReminderConfig.get_interval("reassessment", default=90)
    }
    return render_template("reminders/config.html", config=config)


@reminders_bp.route("/admin/config/<int:template_id>", methods=["POST"])
@role_required("administrator")
def update_config(template_id):
    """Persist reassessment interval for a template to the database."""
    interval = request.form.get("interval_days", 90, type=int)
    key = _TEMPLATE_KEY.get(template_id, str(template_id))
    cfg = ReminderConfig.query.filter_by(template_id=key).first()
    if cfg:
        cfg.interval_days = interval
        cfg.updated_at = datetime.now(timezone.utc)
    else:
        cfg = ReminderConfig(template_id=key, interval_days=interval)
        db.session.add(cfg)
    db.session.commit()
    flash(
        f"Reassessment interval updated to {interval} days for template {template_id}.",
        "success",
    )
    return redirect(url_for("reminders.admin_config"))
