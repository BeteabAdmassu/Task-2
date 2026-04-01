from datetime import datetime, timezone
import bcrypt
from flask_login import UserMixin
from app.extensions import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(20), nullable=False, default="patient"
    )  # administrator, clinician, front_desk, patient
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    VALID_ROLES = ("administrator", "clinician", "front_desk", "patient")

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, password):
        return bcrypt.checkpw(
            password.encode("utf-8"), self.password_hash.encode("utf-8")
        )

    @property
    def is_admin(self):
        return self.role == "administrator"


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    if user and not user.is_active:
        return None
    return user


class LoginAttempt(db.Model):
    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=True, index=True)
    ip_address = db.Column(db.String(45), nullable=False, index=True)
    user_agent = db.Column(db.String(500), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    attempted_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )
