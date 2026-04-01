import os
import uuid
from flask import Flask
from app.config import config_by_name
from app.extensions import db, csrf, migrate, login_manager
from app.utils.logging import setup_logging
from app.utils.middleware import register_middleware


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

    # Template helpers
    @app.context_processor
    def inject_request_token():
        def request_token():
            token = str(uuid.uuid4())
            return token
        return dict(generate_request_token=request_token)

    @app.context_processor
    def inject_antireplay_helpers():
        from datetime import datetime, timezone as _tz
        def generate_nonce():
            return str(uuid.uuid4())
        def generate_timestamp():
            return datetime.now(_tz.utc).isoformat()
        return dict(generate_nonce=generate_nonce, generate_timestamp=generate_timestamp)

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

    return app
