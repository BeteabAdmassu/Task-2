import json
from datetime import time as dt_time
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import current_user
from app.extensions import db
from app.models.user import User
from app.models.scheduling import Clinician, ScheduleTemplate
from app.utils.auth import role_required
from app.utils.antireplay import antireplay
from app.utils.audit import log_action

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/users")
@role_required("administrator")
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users)


@admin_bp.route("/users/<int:user_id>/role", methods=["PUT", "POST"])
@role_required("administrator")
@antireplay
def change_role(user_id):
    user = db.session.get(User, user_id)
    if not user:
        if request.headers.get("HX-Request"):
            return '<span class="field-error">User not found</span>', 404
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))

    if user.id == current_user.id:
        msg = "Cannot change your own role."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 400
        flash(msg, "danger")
        return redirect(url_for("admin.users"))

    new_role = request.form.get("role", "").strip().lower()
    if new_role not in User.VALID_ROLES:
        msg = "Invalid role."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 400
        flash(msg, "danger")
        return redirect(url_for("admin.users"))

    reason = request.form.get("reason", "").strip()
    if not reason:
        msg = "A reason is required for role changes."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 400
        flash(msg, "danger")
        return redirect(url_for("admin.users"))

    # Prevent demoting the last admin
    if user.role == "administrator" and new_role != "administrator":
        admin_count = User.query.filter_by(role="administrator", is_active=True).count()
        if admin_count <= 1:
            msg = "Cannot demote the last administrator."
            if request.headers.get("HX-Request"):
                return f'<span class="field-error">{msg}</span>', 400
            flash(msg, "danger")
            return redirect(url_for("admin.users"))

    old_role = user.role
    user.role = new_role
    db.session.commit()

    log_action(
        action="change_role",
        resource_type="user",
        resource_id=user.id,
        details=json.dumps({
            "target_username": user.username,
            "before": old_role,
            "after": new_role,
            "reason": reason,
        }),
    )

    if request.headers.get("HX-Request"):
        return render_template("admin/_user_row.html", user=user)
    flash(f"Role updated for {user.username}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/status", methods=["PUT", "POST"])
@role_required("administrator")
@antireplay
def change_status(user_id):
    user = db.session.get(User, user_id)
    if not user:
        if request.headers.get("HX-Request"):
            return '<span class="field-error">User not found</span>', 404
        flash("User not found.", "danger")
        return redirect(url_for("admin.users"))

    if user.id == current_user.id:
        msg = "Cannot deactivate your own account."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 400
        flash(msg, "danger")
        return redirect(url_for("admin.users"))

    reason = request.form.get("reason", "").strip()
    if not reason:
        msg = "A reason is required for status changes."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 400
        flash(msg, "danger")
        return redirect(url_for("admin.users"))

    new_status_raw = request.form.get("is_active", "").strip().lower()
    old_active = user.is_active
    user.is_active = new_status_raw in ("true", "1", "yes", "on")
    db.session.commit()

    log_action(
        action="change_status",
        resource_type="user",
        resource_id=user.id,
        details=json.dumps({
            "target_username": user.username,
            "before": old_active,
            "after": user.is_active,
            "reason": reason,
        }),
    )

    if request.headers.get("HX-Request"):
        return render_template("admin/_user_row.html", user=user)
    flash(f"Status updated for {user.username}.", "success")
    return redirect(url_for("admin.users"))


# ── Admin: Clinician profile management ──────────────────────────────────────

@admin_bp.route("/clinicians")
@role_required("administrator")
def clinicians():
    """List all clinician profiles and allow creating new ones."""
    all_clinicians = Clinician.query.join(Clinician.user).order_by(User.username).all()
    # Users with clinician role who do not yet have a clinician profile
    existing_user_ids = {c.user_id for c in all_clinicians}
    eligible_users = User.query.filter(
        User.role == "clinician",
        User.id.notin_(existing_user_ids),
    ).order_by(User.username).all()
    return render_template(
        "admin/clinicians.html",
        clinicians=all_clinicians,
        eligible_users=eligible_users,
    )


@admin_bp.route("/clinicians", methods=["POST"])
@role_required("administrator")
@antireplay
def create_clinician():
    """Create a clinician profile for an existing clinician-role user."""
    user_id = request.form.get("user_id", type=int)
    specialty = request.form.get("specialty", "").strip()
    slot_duration = request.form.get("default_slot_duration_minutes", 15, type=int)

    if not user_id:
        flash("User is required.", "danger")
        return redirect(url_for("admin.clinicians"))

    user = db.session.get(User, user_id)
    if not user:
        flash("User not found.", "danger")
        return redirect(url_for("admin.clinicians"))

    if user.role != "clinician":
        flash("Selected user does not have the clinician role.", "danger")
        return redirect(url_for("admin.clinicians"))

    existing = Clinician.query.filter_by(user_id=user_id).first()
    if existing:
        flash("Clinician profile already exists for this user.", "danger")
        return redirect(url_for("admin.clinicians"))

    if slot_duration < 5 or slot_duration > 120:
        flash("Slot duration must be between 5 and 120 minutes.", "danger")
        return redirect(url_for("admin.clinicians"))

    clinician = Clinician(
        user_id=user_id,
        specialty=specialty or None,
        default_slot_duration_minutes=slot_duration,
    )
    db.session.add(clinician)
    db.session.commit()

    log_action("create_clinician", "clinician", clinician.id, {
        "username": user.username,
        "specialty": specialty,
        "slot_duration": slot_duration,
    })
    flash(f"Clinician profile created for {user.username}.", "success")
    return redirect(url_for("admin.clinicians"))


# ── Admin: Schedule template management ──────────────────────────────────────

DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
             4: "Friday", 5: "Saturday", 6: "Sunday"}


@admin_bp.route("/clinicians/<int:clinician_id>/templates")
@role_required("administrator")
def clinician_templates(clinician_id):
    """List and manage schedule templates for a clinician."""
    clinician = db.session.get(Clinician, clinician_id)
    if not clinician:
        flash("Clinician not found.", "danger")
        return redirect(url_for("admin.clinicians"))
    templates = ScheduleTemplate.query.filter_by(clinician_id=clinician_id).order_by(
        ScheduleTemplate.day_of_week, ScheduleTemplate.start_time
    ).all()
    return render_template(
        "admin/clinician_templates.html",
        clinician=clinician,
        templates=templates,
        day_names=DAY_NAMES,
    )


@admin_bp.route("/clinicians/<int:clinician_id>/templates", methods=["POST"])
@role_required("administrator")
@antireplay
def create_template(clinician_id):
    """Create a schedule template for a clinician."""
    clinician = db.session.get(Clinician, clinician_id)
    if not clinician:
        flash("Clinician not found.", "danger")
        return redirect(url_for("admin.clinicians"))

    day_of_week = request.form.get("day_of_week", type=int)
    start_str = request.form.get("start_time", "").strip()
    end_str = request.form.get("end_time", "").strip()
    slot_duration = request.form.get("slot_duration", clinician.default_slot_duration_minutes, type=int)
    capacity = request.form.get("capacity", 1, type=int)

    if day_of_week is None or day_of_week not in range(7):
        flash("Day of week must be 0 (Monday) through 6 (Sunday).", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))

    def _parse(s):
        try:
            parts = s.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            return None

    start_time = _parse(start_str)
    end_time = _parse(end_str)

    if start_time is None:
        flash("Invalid start time format -- use HH:MM.", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))
    if end_time is None:
        flash("Invalid end time format -- use HH:MM.", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))
    if start_time >= end_time:
        flash("Start time must be before end time.", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))
    if slot_duration < 5 or slot_duration > 120:
        flash("Slot duration must be between 5 and 120 minutes.", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))
    if capacity < 1:
        flash("Capacity must be at least 1.", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))

    template = ScheduleTemplate(
        clinician_id=clinician_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        slot_duration=slot_duration,
        capacity=capacity,
    )
    db.session.add(template)
    db.session.commit()

    log_action("create_schedule_template", "schedule_template", template.id, {
        "clinician_id": clinician_id,
        "day_of_week": day_of_week,
        "start_time": start_str,
        "end_time": end_str,
        "slot_duration": slot_duration,
        "capacity": capacity,
    })
    flash("Schedule template created.", "success")
    return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))


@admin_bp.route("/clinicians/<int:clinician_id>/templates/<int:template_id>/delete", methods=["POST"])
@role_required("administrator")
@antireplay
def delete_template(clinician_id, template_id):
    """Delete a schedule template."""
    template = db.session.get(ScheduleTemplate, template_id)
    if not template or template.clinician_id != clinician_id:
        flash("Template not found.", "danger")
        return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))

    db.session.delete(template)
    db.session.commit()

    log_action("delete_schedule_template", "schedule_template", template_id, {
        "clinician_id": clinician_id,
    })
    flash("Schedule template deleted.", "info")
    return redirect(url_for("admin.clinician_templates", clinician_id=clinician_id))
