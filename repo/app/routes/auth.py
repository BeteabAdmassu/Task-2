import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from markupsafe import escape
from app.extensions import db
from app.models.user import User, LoginAttempt
from app.utils.audit import log_action
from app.utils.antireplay import antireplay
from app.utils.reminders import generate_pending_reminders

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

RATE_LIMIT_ATTEMPTS = 10
RATE_LIMIT_WINDOW = timedelta(minutes=10)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,50}$")
PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$")


def _get_client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr) or "unknown"


def _check_rate_limit(username=None, ip_address=None):
    """Check if login is rate-limited. Returns (is_limited, seconds_remaining)."""
    cutoff = datetime.now(timezone.utc) - RATE_LIMIT_WINDOW

    if username:
        account_attempts = LoginAttempt.query.filter(
            LoginAttempt.username == username,
            LoginAttempt.success == False,
            LoginAttempt.attempted_at >= cutoff,
        ).count()
        if account_attempts >= RATE_LIMIT_ATTEMPTS:
            oldest = (
                LoginAttempt.query.filter(
                    LoginAttempt.username == username,
                    LoginAttempt.success == False,
                    LoginAttempt.attempted_at >= cutoff,
                )
                .order_by(LoginAttempt.attempted_at.asc())
                .first()
            )
            if oldest:
                attempted = oldest.attempted_at.replace(tzinfo=timezone.utc) if oldest.attempted_at.tzinfo is None else oldest.attempted_at
                unlock_at = attempted + RATE_LIMIT_WINDOW
                remaining = (unlock_at - datetime.now(timezone.utc)).total_seconds()
                return True, max(0, int(remaining))

    if ip_address:
        ip_attempts = LoginAttempt.query.filter(
            LoginAttempt.ip_address == ip_address,
            LoginAttempt.success == False,
            LoginAttempt.attempted_at >= cutoff,
        ).count()
        if ip_attempts >= RATE_LIMIT_ATTEMPTS:
            oldest = (
                LoginAttempt.query.filter(
                    LoginAttempt.ip_address == ip_address,
                    LoginAttempt.success == False,
                    LoginAttempt.attempted_at >= cutoff,
                )
                .order_by(LoginAttempt.attempted_at.asc())
                .first()
            )
            if oldest:
                attempted = oldest.attempted_at.replace(tzinfo=timezone.utc) if oldest.attempted_at.tzinfo is None else oldest.attempted_at
                unlock_at = attempted + RATE_LIMIT_WINDOW
                remaining = (unlock_at - datetime.now(timezone.utc)).total_seconds()
                return True, max(0, int(remaining))

    return False, 0


def _record_attempt(username, ip_address, user_agent, success):
    attempt = LoginAttempt(
        username=username,
        ip_address=ip_address,
        user_agent=user_agent[:500] if user_agent else None,
        success=success,
    )
    db.session.add(attempt)
    db.session.commit()


def _is_safe_redirect_url(url):
    """Return True only for same-origin relative paths (no scheme, no netloc)."""
    if not url:
        return False
    parsed = urlparse(url)
    return not parsed.scheme and not parsed.netloc and url.startswith("/")


def _get_dashboard_for_role(role):
    role_dashboards = {
        "administrator": "main.index",
        "clinician": "main.index",
        "front_desk": "main.index",
        "patient": "main.index",
    }
    return role_dashboards.get(role, "main.index")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for(_get_dashboard_for_role(current_user.role)))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        errors = []
        if not USERNAME_RE.match(username):
            errors.append(
                "Username must be 3-50 characters, alphanumeric and underscores only."
            )
        if not PASSWORD_RE.match(password):
            errors.append(
                "Password must be at least 8 characters with uppercase, lowercase, and a digit."
            )
        if password != password_confirm:
            errors.append("Passwords do not match.")
        if User.query.filter_by(username=username).first():
            errors.append("Username is already taken.")

        if errors:
            if request.headers.get("HX-Request"):
                return render_template(
                    "auth/_register_form.html",
                    errors=errors,
                    username=username,
                ), 200
            for e in errors:
                flash(e, "danger")
            return render_template("auth/register.html", username=username)

        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Account created successfully!", "success")
        if request.headers.get("HX-Request"):
            resp = jsonify({"redirect": url_for(_get_dashboard_for_role(user.role))})
            resp.headers["HX-Redirect"] = url_for(_get_dashboard_for_role(user.role))
            return resp
        return redirect(url_for(_get_dashboard_for_role(user.role)))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(_get_dashboard_for_role(current_user.role)))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = _get_client_ip()
        ua = request.headers.get("User-Agent", "")

        # Check rate limit
        is_limited, remaining = _check_rate_limit(username=username, ip_address=ip)
        if is_limited:
            minutes = remaining // 60
            seconds = remaining % 60
            msg = f"Too many login attempts. Please try again in {minutes}m {seconds}s."
            if request.headers.get("HX-Request"):
                return render_template(
                    "auth/_login_form.html",
                    error=msg,
                    username=username,
                    locked_seconds=remaining,
                )
            flash(msg, "danger")
            return render_template(
                "auth/login.html", username=username, locked_seconds=remaining
            )

        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(password):
            _record_attempt(username, ip, ua, success=True)
            log_action("login_success", "user", user.id, {"username": username, "ip": ip})
            login_user(user)
            try:
                generate_pending_reminders(user_id=user.id)
            except Exception:
                pass  # never block login on reminder generation errors
            next_page = request.args.get("next")
            destination = next_page if _is_safe_redirect_url(next_page) else url_for(_get_dashboard_for_role(user.role))
            if request.headers.get("HX-Request"):
                resp = jsonify({"redirect": destination})
                resp.headers["HX-Redirect"] = destination
                return resp
            return redirect(destination)
        else:
            _record_attempt(username, ip, ua, success=False)
            log_action("login_failed", "user", None, {"username": username, "ip": ip})
            msg = "Invalid username or password."
            if request.headers.get("HX-Request"):
                return render_template(
                    "auth/_login_form.html", error=msg, username=username
                )
            flash(msg, "danger")
            return render_template("auth/login.html", username=username)

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
@antireplay
def change_password():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        errors = []
        if not current_user.check_password(current_password):
            errors.append("Current password is incorrect.")
        if not PASSWORD_RE.match(new_password):
            errors.append("New password must be at least 8 characters with uppercase, lowercase, and a digit.")
        if new_password != confirm_password:
            errors.append("New passwords do not match.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("auth/change_password.html")

        current_user.set_password(new_password)
        db.session.commit()
        flash("Password changed successfully.", "success")
        return redirect(url_for("main.index"))

    return render_template("auth/change_password.html")


@auth_bp.route("/check-username")
def check_username():
    username = request.args.get("username", "").strip()
    if not username:
        return '<span class="field-hint">Enter a username</span>'
    if not USERNAME_RE.match(username):
        return '<span class="field-error">3-50 characters, alphanumeric and underscores only</span>'
    if User.query.filter_by(username=username).first():
        return '<span class="field-error">Username is already taken</span>'
    return '<span class="field-success">Username is available</span>'
