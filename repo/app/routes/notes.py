from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.extensions import db
from app.models.clinical_note import ClinicalNote
from app.models.user import User
from app.utils.auth import role_required
from app.utils.antireplay import antireplay

notes_bp = Blueprint("notes", __name__, url_prefix="/notes")

_STAFF_ROLES = ("administrator", "clinician", "front_desk")


@notes_bp.route("/patient/<int:patient_id>", methods=["GET", "POST"])
@role_required(*_STAFF_ROLES)
@antireplay
def patient_notes(patient_id):
    """Staff view: list all notes for a patient and create new ones."""
    patient = db.session.get(User, patient_id)
    if not patient:
        flash("Patient not found.", "danger")
        return redirect(url_for("staff.patient_list"))

    if request.method == "POST":
        content = request.form.get("content", "").strip()
        if not content:
            flash("Note content cannot be empty.", "danger")
        else:
            note = ClinicalNote.create(
                patient_id=patient_id,
                author_id=current_user.id,
                content=content,
            )
            db.session.add(note)
            db.session.commit()
            flash("Note saved.", "success")
        return redirect(url_for("notes.patient_notes", patient_id=patient_id))

    notes = (
        ClinicalNote.query
        .filter_by(patient_id=patient_id)
        .order_by(ClinicalNote.created_at.desc())
        .all()
    )
    return render_template("notes/patient_notes.html", patient=patient, notes=notes)


@notes_bp.route("/my")
@login_required
def my_notes():
    """Patient view: read own notes only."""
    if current_user.role not in ("patient",):
        # Staff should use the patient_notes route
        flash("Please use the staff notes view.", "info")
        return redirect(url_for("staff.patient_list"))

    notes = (
        ClinicalNote.query
        .filter_by(patient_id=current_user.id)
        .order_by(ClinicalNote.created_at.desc())
        .all()
    )
    return render_template("notes/my_notes.html", notes=notes)
