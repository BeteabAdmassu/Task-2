from datetime import datetime, timezone
from app.extensions import db
from app.utils.encryption import encrypt_value, decrypt_value


class ClinicalNote(db.Model):
    __tablename__ = "clinical_notes"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, db.ForeignKey("visits.id"), nullable=True)
    content_encrypted = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    patient = db.relationship("User", foreign_keys=[patient_id])
    author = db.relationship("User", foreign_keys=[author_id])
    visit = db.relationship("Visit", backref="clinical_notes")

    @property
    def content(self):
        """Decrypt and return note content. Call only in an authorized render context."""
        return decrypt_value(self.content_encrypted) or ""

    @classmethod
    def create(cls, patient_id, author_id, content, visit_id=None):
        """Encrypt content and return an unsaved ClinicalNote instance."""
        return cls(
            patient_id=patient_id,
            author_id=author_id,
            visit_id=visit_id,
            content_encrypted=encrypt_value(content),
        )
