from datetime import datetime, timezone
from flask import Blueprint, jsonify
from flask_login import login_required
from app.extensions import csrf, db
from app.utils.auth import role_required

health_bp = Blueprint("health", __name__)


@health_bp.route("/health")
@csrf.exempt
def health_check():
    return jsonify(
        {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )


@health_bp.route("/health/detailed")
@role_required("administrator")
def health_detailed():
    # Check database connectivity
    try:
        db.session.execute(db.text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    # Get table row counts
    tables = [
        "users", "visits", "visit_transitions", "audit_logs", "coverage_zones",
        "reminders", "slots", "reservations", "clinicians",
    ]
    table_counts = {}
    for table in tables:
        try:
            result = db.session.execute(db.text(f"SELECT COUNT(*) FROM {table}"))
            table_counts[table] = result.scalar()
        except Exception:
            table_counts[table] = None

    return jsonify(
        {
            "status": "ok",
            "database": db_status,
            "tables": table_counts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
