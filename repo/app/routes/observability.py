from flask import Blueprint, render_template
from app.extensions import db
from app.utils.auth import role_required

observability_bp = Blueprint("observability", __name__, url_prefix="/admin")


@observability_bp.route("/observability")
@role_required("administrator")
def observability():
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

    return render_template("admin/observability.html", table_stats=table_stats)
