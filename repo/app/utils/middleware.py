import uuid
import time
from datetime import datetime, timezone, timedelta
from flask import g, request, session, redirect, url_for, flash
from flask_login import current_user, logout_user
import logging

SESSION_TIMEOUT_MINUTES = 30


def register_middleware(app):
    @app.before_request
    def set_correlation_id():
        g.correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))

    @app.before_request
    def record_request_start():
        g.request_start_time = time.time()

    @app.before_request
    def check_session_timeout():
        exempt_paths = ("/auth/login", "/auth/register", "/auth/logout", "/health", "/static")
        if any(request.path.startswith(p) for p in exempt_paths):
            return
        if current_user and hasattr(current_user, "is_authenticated") and current_user.is_authenticated:
            last_active = session.get("last_active")
            now = datetime.now(timezone.utc)
            if last_active:
                try:
                    last_dt = datetime.fromisoformat(last_active)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if now - last_dt > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                        logout_user()
                        flash("Session expired due to inactivity.", "warning")
                        return redirect(url_for("auth.login"))
                except (ValueError, TypeError):
                    pass
            session["last_active"] = now.isoformat()

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return response

    @app.after_request
    def log_request(response):
        correlation_id = getattr(g, "correlation_id", "unknown")
        response.headers["X-Correlation-ID"] = correlation_id
        logger = logging.getLogger("meridiancare.request")
        extra = {"correlation_id": correlation_id}

        start_time = getattr(g, "request_start_time", None)
        if start_time is not None:
            duration_ms = (time.time() - start_time) * 1000
            if duration_ms > 500:
                logger.warning(
                    "%s %s %s duration=%.1fms (SLOW)",
                    request.method, request.path, response.status_code, duration_ms,
                    extra=extra,
                )
                # Persist slow-query record for admin operations UI.
                try:
                    from app.models.audit import SlowQuery
                    from app.extensions import db
                    sq = SlowQuery(
                        endpoint=request.path,
                        duration_ms=duration_ms,
                        correlation_id=correlation_id,
                    )
                    db.session.add(sq)
                    db.session.commit()
                except Exception:
                    try:
                        from app.extensions import db
                        db.session.rollback()
                    except Exception:
                        pass
            else:
                logger.info(
                    "%s %s %s duration=%.1fms",
                    request.method, request.path, response.status_code, duration_ms,
                    extra=extra,
                )
        else:
            logger.info(
                "%s %s %s", request.method, request.path, response.status_code, extra=extra
            )
        return response
