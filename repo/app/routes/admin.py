import json
from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from flask_login import current_user
from app.extensions import db
from app.models.user import User
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
