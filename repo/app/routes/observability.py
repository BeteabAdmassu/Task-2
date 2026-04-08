from datetime import datetime, timezone
from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import current_user
from app.extensions import db
from app.models.audit import AnomalyAlert, SlowQuery
from app.utils.auth import role_required
from app.utils.antireplay import antireplay
from app.utils.audit import anomaly_detection

observability_bp = Blueprint("observability", __name__, url_prefix="/admin")


@observability_bp.route("/observability")
@role_required("administrator")
def observability():
    # Run anomaly detection lazily
    try:
        anomaly_detection()
    except Exception:
        pass

    # Database stats - row counts for key tables
    table_stats = {}
    tables = ["users", "visits", "visit_transitions", "audit_logs", "coverage_zones",
              "reminders", "slots", "reservations", "clinicians"]
    for table in tables:
        try:
            result = db.session.execute(db.text(f"SELECT COUNT(*) FROM {table}"))
            table_stats[table] = result.scalar()
        except Exception:
            table_stats[table] = "N/A"

    # Recent anomaly alerts
    alerts = AnomalyAlert.query.order_by(AnomalyAlert.created_at.desc()).limit(20).all()

    # Recent slow queries
    slow_queries = SlowQuery.query.order_by(SlowQuery.timestamp.desc()).limit(20).all()

    return render_template(
        "admin/observability.html",
        table_stats=table_stats,
        alerts=alerts,
        slow_queries=slow_queries,
    )


@observability_bp.route("/operations")
@role_required("administrator")
def operations():
    # Run anomaly detection lazily
    try:
        anomaly_detection()
    except Exception:
        pass

    # Database stats - row counts for key tables
    table_stats = {}
    tables = ["users", "visits", "visit_transitions", "audit_logs", "coverage_zones",
              "reminders", "slots", "reservations", "clinicians"]
    for table in tables:
        try:
            result = db.session.execute(db.text(f"SELECT COUNT(*) FROM {table}"))
            table_stats[table] = result.scalar()
        except Exception:
            table_stats[table] = "N/A"

    # Recent anomaly alerts
    alerts = AnomalyAlert.query.order_by(AnomalyAlert.created_at.desc()).limit(20).all()

    # Recent slow queries
    slow_queries = SlowQuery.query.order_by(SlowQuery.timestamp.desc()).limit(20).all()

    return render_template(
        "admin/observability.html",
        table_stats=table_stats,
        alerts=alerts,
        slow_queries=slow_queries,
    )


@observability_bp.route("/operations/alerts")
@role_required("administrator")
def operations_alerts():
    """HTMX partial for anomaly alerts list."""
    alerts = AnomalyAlert.query.order_by(AnomalyAlert.created_at.desc()).limit(50).all()
    return render_template("admin/_alerts.html", alerts=alerts)


@observability_bp.route("/operations/slow-queries")
@role_required("administrator")
def operations_slow_queries():
    """HTMX partial for slow query table."""
    slow_queries = SlowQuery.query.order_by(SlowQuery.timestamp.desc()).limit(50).all()
    return render_template("admin/_slow_queries.html", slow_queries=slow_queries)


@observability_bp.route("/operations/sessions")
@role_required("administrator")
def operations_sessions():
    """HTMX partial for active sessions."""
    from app.models.user import User
    active_users = User.query.filter_by(is_active=True).order_by(User.last_login_at.desc()).all()
    return render_template("admin/_sessions.html", active_users=active_users)


@observability_bp.route("/operations/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@role_required("administrator")
@antireplay
def acknowledge_alert(alert_id):
    alert = AnomalyAlert.query.get_or_404(alert_id)
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by = current_user.id
    db.session.commit()
    flash("Alert acknowledged.", "success")
    return redirect(url_for("observability.operations"))
