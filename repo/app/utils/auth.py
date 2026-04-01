from functools import wraps
from flask import abort, request, jsonify
from flask_login import current_user, login_required
import logging

logger = logging.getLogger("meridiancare.auth")


def role_required(*roles):
    """Decorator that requires the current user to have one of the specified roles."""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            if current_user.role not in roles:
                logger.warning(
                    "Access denied: user=%s role=%s required=%s path=%s",
                    current_user.username,
                    current_user.role,
                    roles,
                    request.path,
                )
                if request.headers.get("HX-Request"):
                    return jsonify({"error": "Access denied"}), 403
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator
