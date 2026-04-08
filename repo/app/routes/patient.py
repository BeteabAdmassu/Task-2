import re
from datetime import datetime, date
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user, logout_user
from markupsafe import escape
from app.extensions import db
from app.models.demographics import PatientDemographics, DemographicsChangeLog
from app.models.assessment import AssessmentResult, AssessmentDraft
from app.models.scheduling import Reservation, Slot
from app.models.clinical_note import ClinicalNote
from app.models.user import LoginAttempt
from app.utils.encryption import encrypt_value, decrypt_value, mask_id, mask_encrypted_id
from app.utils.auth import role_required
from app.utils.antireplay import antireplay

# Placeholder written to clinical note content after account deletion.
# Computed once at import time so a single ciphertext is reused per request.
_DELETED_NOTE_PLACEHOLDER = "[content removed - account deleted]"

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")

PHONE_RE = re.compile(r"^[\d\s\-\(\)\+]{7,20}$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
ID_RE = re.compile(r"^[A-Za-z0-9\s\-\/]{1,50}$")

SENSITIVE_FIELDS = ("insurance_id_encrypted", "government_id_encrypted")
PLAIN_FIELDS = (
    "full_name", "date_of_birth", "gender", "phone",
    "address_street", "address_city", "address_state", "address_zip",
    "emergency_contact_name", "emergency_contact_phone", "emergency_contact_relationship",
)


def _parse_demographics_form(form):
    data = {}
    errors = []

    data["full_name"] = form.get("full_name", "").strip()
    if not data["full_name"]:
        errors.append("Full name is required.")

    dob_str = form.get("date_of_birth", "").strip()
    if not dob_str:
        errors.append("Date of birth is required.")
    else:
        try:
            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
            if dob > date.today():
                errors.append("Date of birth cannot be in the future.")
            data["date_of_birth"] = dob
        except ValueError:
            errors.append("Invalid date format. Use YYYY-MM-DD.")

    data["gender"] = form.get("gender", "").strip() or None

    phone = form.get("phone", "").strip()
    if not phone:
        errors.append("Phone number is required.")
    elif not PHONE_RE.match(phone):
        errors.append("Invalid phone number format.")
    data["phone"] = phone

    data["address_street"] = form.get("address_street", "").strip() or None
    data["address_city"] = form.get("address_city", "").strip() or None
    data["address_state"] = form.get("address_state", "").strip() or None

    zip_code = form.get("address_zip", "").strip()
    if zip_code and not ZIP_RE.match(zip_code):
        errors.append("Invalid ZIP code format (use 12345 or 12345-6789).")
    data["address_zip"] = zip_code or None

    data["emergency_contact_name"] = form.get("emergency_contact_name", "").strip() or None
    data["emergency_contact_phone"] = form.get("emergency_contact_phone", "").strip() or None
    data["emergency_contact_relationship"] = form.get("emergency_contact_relationship", "").strip() or None

    insurance_id = form.get("insurance_id", "").strip() or None
    if insurance_id and not ID_RE.match(insurance_id):
        errors.append("Insurance ID may only contain letters, digits, spaces, hyphens, and forward slashes (max 50 characters).")
    data["insurance_id"] = insurance_id

    government_id = form.get("government_id", "").strip() or None
    if government_id and not ID_RE.match(government_id):
        errors.append("Government ID may only contain letters, digits, spaces, hyphens, and forward slashes (max 50 characters).")
    data["government_id"] = government_id

    return data, errors


def _save_demographics(demo, data, changed_by_id):
    changes = []

    for field in PLAIN_FIELDS:
        new_val = data.get(field)
        if field == "date_of_birth" and new_val:
            new_val_str = str(new_val)
            old_val_str = str(getattr(demo, field)) if getattr(demo, field) else None
            if old_val_str != new_val_str:
                changes.append((field, old_val_str, new_val_str))
            setattr(demo, field, new_val)
        else:
            old_val = getattr(demo, field)
            if old_val != new_val:
                changes.append((field, old_val, new_val))
            setattr(demo, field, new_val)

    # Encrypted fields
    for raw_field, db_field in [("insurance_id", "insurance_id_encrypted"), ("government_id", "government_id_encrypted")]:
        new_raw = data.get(raw_field)
        old_encrypted = getattr(demo, db_field)
        old_raw = decrypt_value(old_encrypted) if old_encrypted else None
        if old_raw != new_raw:
            changes.append((raw_field, "***" if old_raw else None, "***" if new_raw else None))
            setattr(demo, db_field, encrypt_value(new_raw) if new_raw else None)

    if changes and demo.id:
        demo.version = (demo.version or 1) + 1
        for field_name, old_val, new_val in changes:
            log = DemographicsChangeLog(
                demographics_id=demo.id,
                changed_by_id=changed_by_id,
                field_name=field_name,
                old_value=str(old_val) if old_val is not None else None,
                new_value=str(new_val) if new_val is not None else None,
            )
            db.session.add(log)

    return changes


@patient_bp.route("/demographics", methods=["GET", "POST"])
@login_required
@antireplay
def demographics():
    if current_user.role != "patient":
        flash("Only patients can access this page.", "warning")
        return redirect(url_for("main.index"))

    demo = PatientDemographics.query.filter_by(user_id=current_user.id).first()

    if request.method == "POST":
        data, errors = _parse_demographics_form(request.form)
        form_version = request.form.get("version", type=int)

        if demo and form_version and demo.version != form_version:
            errors.append("This record was modified by someone else. Please review and try again.")

        if errors:
            if request.headers.get("HX-Request"):
                return render_template(
                    "patient/_demographics_form.html",
                    demo=demo, errors=errors, data=data, mask_id=mask_id,
                    mask_encrypted_id=mask_encrypted_id,
                )
            for e in errors:
                flash(e, "danger")
            return render_template(
                "patient/demographics.html", demo=demo, data=data, mask_id=mask_id,
                mask_encrypted_id=mask_encrypted_id,
            )

        if not demo:
            demo = PatientDemographics(user_id=current_user.id)
            for field in PLAIN_FIELDS:
                setattr(demo, field, data.get(field))
            for raw_field, db_field in [("insurance_id", "insurance_id_encrypted"), ("government_id", "government_id_encrypted")]:
                raw_val = data.get(raw_field)
                setattr(demo, db_field, encrypt_value(raw_val) if raw_val else None)
            db.session.add(demo)
            db.session.commit()
            flash("Demographics saved successfully!", "success")
        else:
            _save_demographics(demo, data, current_user.id)
            db.session.commit()
            flash("Demographics updated successfully!", "success")

        if request.headers.get("HX-Request"):
            resp = jsonify({"redirect": url_for("patient.demographics")})
            resp.headers["HX-Redirect"] = url_for("patient.demographics")
            return resp
        return redirect(url_for("patient.demographics"))

    return render_template(
        "patient/demographics.html", demo=demo, mask_id=mask_id,
        mask_encrypted_id=mask_encrypted_id,
    )


@patient_bp.route("/demographics/reveal", methods=["POST"])
@login_required
@antireplay
def reveal_field():
    if current_user.role != "patient":
        return jsonify({"error": "Access denied"}), 403

    demo = PatientDemographics.query.filter_by(user_id=current_user.id).first()
    if not demo:
        return "", 404

    field = request.form.get("field", "")
    if field == "insurance_id" and demo.insurance_id_encrypted:
        return str(escape(decrypt_value(demo.insurance_id_encrypted)))
    elif field == "government_id" and demo.government_id_encrypted:
        return str(escape(decrypt_value(demo.government_id_encrypted)))
    return "", 404


@patient_bp.route("/export", methods=["GET"])
@login_required
def export_data():
    if current_user.role != "patient":
        return jsonify({"error": "Access denied"}), 403

    export = {"user": {"id": current_user.id, "username": current_user.username}}

    # Demographics
    demo = PatientDemographics.query.filter_by(user_id=current_user.id).first()
    if demo:
        demo_data = {}
        for field in PLAIN_FIELDS:
            val = getattr(demo, field, None)
            demo_data[field] = str(val) if val is not None else None
        for raw_field, db_field in [("insurance_id", "insurance_id_encrypted"), ("government_id", "government_id_encrypted")]:
            encrypted = getattr(demo, db_field, None)
            demo_data[raw_field] = decrypt_value(encrypted) if encrypted else None
        export["demographics"] = demo_data

    # Assessments
    assessments = AssessmentResult.query.filter_by(patient_id=current_user.id).all()
    export["assessments"] = [
        {
            "id": a.id,
            "template_id": a.template_id,
            "risk_level": a.risk_level,
            "submitted_at": a.submitted_at.isoformat() if a.submitted_at else None,
        }
        for a in assessments
    ]

    # Appointments (reservations)
    reservations = Reservation.query.filter_by(patient_id=current_user.id).all()
    export["appointments"] = [
        {
            "id": r.id,
            "slot_id": r.slot_id,
            "status": r.status,
            "held_at": r.held_at.isoformat() if r.held_at else None,
            "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
        }
        for r in reservations
    ]

    resp = make_response(jsonify(export))
    resp.headers["Content-Disposition"] = "attachment; filename=patient_data.json"
    return resp


@patient_bp.route("/delete-account", methods=["POST"])
@login_required
@antireplay
def delete_account():
    if current_user.role != "patient":
        return jsonify({"error": "Access denied"}), 403

    password = request.form.get("password", "")
    if not current_user.check_password(password):
        flash("Password is incorrect.", "danger")
        return redirect(url_for("patient.demographics"))

    user = current_user._get_current_object()
    original_username = user.username  # capture before renaming

    # --- Anonymize demographics ---
    demo = PatientDemographics.query.filter_by(user_id=user.id).first()
    if demo:
        demo.full_name = "Deleted User"
        # phone and date_of_birth are NOT NULL in the schema; use safe
        # placeholder values rather than None to satisfy the constraint.
        demo.phone = "0000000"
        demo.date_of_birth = date(1900, 1, 1)
        demo.gender = None
        demo.address_street = None
        demo.address_city = None
        demo.address_state = None
        demo.address_zip = None
        demo.emergency_contact_name = None
        demo.emergency_contact_phone = None
        demo.emergency_contact_relationship = None
        demo.insurance_id_encrypted = None
        demo.government_id_encrypted = None

        # Scrub PII values stored in the demographics change log for this patient.
        # Timestamps and field names are retained for audit completeness.
        # Use no_autoflush to prevent SQLAlchemy from flushing the in-progress
        # demo changes (which include NOT-NULL placeholders) before we commit.
        with db.session.no_autoflush:
            DemographicsChangeLog.query.filter_by(demographics_id=demo.id).update(
                {"old_value": None, "new_value": None},
                synchronize_session=False,
            )

    # --- Anonymize clinical notes written about this patient ---
    # Replace encrypted content with an encrypted placeholder so the record
    # structure (author, timestamp, visit linkage) is preserved for audit but
    # the note body no longer reveals patient identity.
    placeholder_ciphertext = encrypt_value(_DELETED_NOTE_PLACEHOLDER)
    for note in ClinicalNote.query.filter_by(patient_id=user.id).all():
        note.content_encrypted = placeholder_ciphertext

    # --- Remove incomplete assessment drafts (no legal-hold value) ---
    AssessmentDraft.query.filter_by(patient_id=user.id).delete(
        synchronize_session=False
    )

    # --- Clear username from login attempt records ---
    # LoginAttempt stores username as a plain string; scrub it so the
    # original login name is not discoverable from the attempt history.
    LoginAttempt.query.filter_by(username=original_username).update(
        {"username": None},
        synchronize_session=False,
    )

    # --- Anonymize user account ---
    # AssessmentResult, Visit, and Reservation rows retain their patient_id FK
    # so operational and audit queries remain functional, but the referenced user
    # row is now deactivated and carries no PII beyond the surrogate ID.
    user.username = f"deleted_{user.id}"
    user.is_active = False

    db.session.commit()
    logout_user()
    flash("Your account has been deleted.", "info")
    return redirect(url_for("auth.login"))
