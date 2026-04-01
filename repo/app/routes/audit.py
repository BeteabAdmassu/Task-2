from flask import Blueprint, render_template, request
from app.models.audit import AuditLog
from app.utils.auth import role_required

audit_bp = Blueprint("audit", __name__, url_prefix="/admin")


@audit_bp.route("/audit")
@role_required("administrator")
def audit_log():
    page = request.args.get("page", 1, type=int)
    per_page = 50
    pagination = AuditLog.query.order_by(AuditLog.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return render_template("admin/audit.html", pagination=pagination, logs=pagination.items)
