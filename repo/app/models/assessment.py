import json
from datetime import datetime, timezone
from app.extensions import db


class AssessmentTemplate(db.Model):
    __tablename__ = "assessment_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    questions_json = db.Column(db.Text, nullable=False)
    scoring_rules_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (db.UniqueConstraint("name", "version"),)

    @property
    def questions(self):
        return json.loads(self.questions_json)

    @property
    def scoring_rules(self):
        return json.loads(self.scoring_rules_json)


class AssessmentResult(db.Model):
    __tablename__ = "assessment_results"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    visit_id = db.Column(db.Integer, nullable=True, index=True)
    template_id = db.Column(db.Integer, db.ForeignKey("assessment_templates.id"), nullable=False)
    template_version = db.Column(db.Integer, nullable=False)
    answers_json = db.Column(db.Text, nullable=False)
    scores_json = db.Column(db.Text, nullable=False)
    risk_level = db.Column(db.String(20), nullable=False)  # Low, Moderate, High
    explanation_snapshot_json = db.Column(db.Text, nullable=False)
    request_token = db.Column(db.String(64), unique=True, nullable=True)
    submitted_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    patient = db.relationship("User", foreign_keys=[patient_id])
    template = db.relationship("AssessmentTemplate")

    @property
    def answers(self):
        return json.loads(self.answers_json)

    @property
    def scores(self):
        return json.loads(self.scores_json)

    @property
    def explanation(self):
        return json.loads(self.explanation_snapshot_json)


class AssessmentDraft(db.Model):
    __tablename__ = "assessment_drafts"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    visit_id = db.Column(db.Integer, nullable=True)
    template_id = db.Column(db.Integer, db.ForeignKey("assessment_templates.id"), nullable=False)
    partial_answers_json = db.Column(db.Text, nullable=False, default="{}")
    current_step = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
