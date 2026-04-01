import atexit
import os
import uuid
from flask import Flask
from app.config import config_by_name
from app.extensions import db, csrf, migrate, login_manager
from app.utils.logging import setup_logging
from app.utils.middleware import register_middleware


def _start_background_scheduler(app):
    """Start a background thread with periodic maintenance jobs.

    Jobs registered:
    - hold_expiry        : expire stale reservation holds every 1 minute.
    - reminder_generation: generate pending reminders every 15 minutes.

    Guards:
    - Skipped entirely in testing mode.
    - In debug mode with the Werkzeug reloader, only the worker subprocess starts
      the scheduler (avoids double-scheduling in the monitor/reloader process).
    - Registered with atexit for graceful shutdown.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        app.logger.warning(
            "APScheduler is not installed — background jobs disabled. "
            "Run: pip install APScheduler>=3.10,<4.0"
        )
        return None
    from app.utils.reminders import generate_pending_reminders
    from app.models.scheduling import expire_stale_holds

    scheduler = BackgroundScheduler(daemon=True)

    def _reminder_job():
        with app.app_context():
            try:
                generate_pending_reminders()
            except Exception:
                pass  # never let a DB error crash the scheduler thread

    def _hold_expiry_job():
        """Expire overdue reservation holds on a fixed schedule.

        This is the authoritative expiry mechanism — holds expire regardless of
        whether any user navigates to the schedule page (which only triggers the
        lazy cleanup).  Running every 1 minute ensures holds never linger more
        than ~11 minutes past their 10-minute window (10 min hold + up to 1 min
        until the next sweep).
        """
        with app.app_context():
            try:
                expire_stale_holds()
            except Exception:
                pass

    scheduler.add_job(_hold_expiry_job, "interval", minutes=1, id="hold_expiry")
    scheduler.add_job(_reminder_job, "interval", minutes=15, id="reminder_generation")
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler


# Keep old name as alias so any external reference still works.
_start_reminder_scheduler = _start_background_scheduler


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get("FLASK_ENV", "production")

    cfg = config_by_name[config_name]
    if hasattr(cfg, "validate"):
        cfg.validate()

    app = Flask(__name__)
    app.config.from_object(cfg)

    # Initialize extensions
    db.init_app(app)
    csrf.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # Setup logging and middleware
    setup_logging(app)
    register_middleware(app)

    # Register blueprints
    from app.routes.main import main_bp
    from app.routes.health import health_bp
    from app.routes.auth import auth_bp
    from app.routes.admin import admin_bp
    from app.routes.patient import patient_bp
    from app.routes.staff import staff_bp
    from app.routes.assessments import assessments_bp
    from app.routes.schedule import schedule_bp
    from app.routes.visits import visits_bp
    from app.routes.coverage import coverage_bp
    from app.routes.audit import audit_bp
    from app.routes.reminders import reminders_bp
    from app.routes.observability import observability_bp
    from app.routes.notes import notes_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(staff_bp)
    app.register_blueprint(assessments_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(coverage_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(observability_bp)
    app.register_blueprint(notes_bp)

    # Template helpers
    @app.context_processor
    def inject_request_token():
        def request_token():
            token = str(uuid.uuid4())
            return token
        return dict(generate_request_token=request_token)

    @app.context_processor
    def inject_antireplay_helpers():
        import hmac as _hmac
        import hashlib as _hashlib
        import json as _json
        from datetime import datetime, timezone as _tz
        from markupsafe import Markup

        def _build_sig(method, path, nonce, timestamp):
            secret = app.config.get("REQUEST_SIGNING_SECRET", "")
            payload = f"{method.upper()}|{path}|{nonce}|{timestamp}"
            return _hmac.new(secret.encode(), payload.encode(), _hashlib.sha256).hexdigest()

        def antireplay_inputs(method, path):
            """Render three hidden fields: _nonce, _timestamp, _signature.

            The signature is HMAC-SHA256 over 'METHOD|path|nonce|timestamp'
            using REQUEST_SIGNING_SECRET.  All values are server-generated so
            the secret never reaches the browser.
            """
            nonce = str(uuid.uuid4())
            timestamp = datetime.now(_tz.utc).isoformat()
            sig = _build_sig(method, path, nonce, timestamp)
            return Markup(
                f'<input type="hidden" name="_nonce" value="{nonce}">'
                f'<input type="hidden" name="_timestamp" value="{timestamp}">'
                f'<input type="hidden" name="_signature" value="{sig}">'
            )

        def antireplay_headers(method, path):
            """Return a JSON string suitable for HTMX hx-headers containing
            X-Nonce, X-Timestamp, and X-Signature for the given endpoint.

            Usage in templates:
                hx-headers='{{ antireplay_headers("POST", url_for("...")) }}'
            """
            nonce = str(uuid.uuid4())
            timestamp = datetime.now(_tz.utc).isoformat()
            sig = _build_sig(method, path, nonce, timestamp)
            return Markup(_json.dumps({
                "X-Nonce": nonce,
                "X-Timestamp": timestamp,
                "X-Signature": sig,
            }))

        # Kept for any template that still calls them individually.
        def generate_nonce():
            return str(uuid.uuid4())

        def generate_timestamp():
            return datetime.now(_tz.utc).isoformat()

        return dict(
            antireplay_inputs=antireplay_inputs,
            antireplay_headers=antireplay_headers,
            generate_nonce=generate_nonce,
            generate_timestamp=generate_timestamp,
        )

    # Error handlers
    from flask import render_template, jsonify, request as flask_request

    @app.errorhandler(403)
    def forbidden(e):
        if flask_request.headers.get("HX-Request"):
            return jsonify({"error": "Access denied"}), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        if flask_request.headers.get("HX-Request"):
            return jsonify({"error": "Not found"}), 404
        return render_template("errors/404.html"), 404

    # Create database tables
    with app.app_context():
        from app import models  # noqa: F401
        db.create_all()

    # Start in-process background scheduler (skipped in testing and in the
    # Werkzeug reloader monitor process to avoid duplicate jobs).
    if not app.testing:
        from werkzeug.serving import is_running_from_reloader
        if not app.debug or is_running_from_reloader():
            _start_background_scheduler(app)

    return app
