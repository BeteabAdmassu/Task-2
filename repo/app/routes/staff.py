from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required
from markupsafe import escape
from app.extensions import db
from app.models.user import User
from app.models.demographics import PatientDemographics, DemographicsChangeLog
from app.utils.encryption import encrypt_value, decrypt_value, mask_id, mask_encrypted_id
from app.utils.auth import role_required
from app.utils.antireplay import antireplay
from app.routes.patient import _parse_demographics_form, _save_demographics, PLAIN_FIELDS

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")


@staff_bp.route("/patients")
@role_required("administrator", "clinician", "front_desk")
def patient_list():
    patients = User.query.filter_by(role="patient").order_by(User.username).all()
    demographics = {d.user_id: d for d in PatientDemographics.query.all()}
    return render_template("staff/patient_list.html", patients=patients, demographics=demographics, mask_id=mask_id)


@staff_bp.route("/patients/<int:patient_id>/demographics", methods=["GET", "POST"])
@role_required("administrator", "clinician", "front_desk")
@antireplay
def patient_demographics(patient_id):
    patient = db.session.get(User, patient_id)
    if not patient or patient.role != "patient":
        flash("Patient not found.", "danger")
        return redirect(url_for("staff.patient_list"))

    demo = PatientDemographics.query.filter_by(user_id=patient_id).first()
    read_only = current_user.role == "clinician"

    if request.method == "POST":
        if read_only:
            flash("You do not have permission to edit demographics.", "danger")
            return redirect(url_for("staff.patient_demographics", patient_id=patient_id))

        data, errors = _parse_demographics_form(request.form)
        form_version = request.form.get("version", type=int)

        if demo and form_version and demo.version != form_version:
            errors.append("This record was modified by someone else. Please review and try again.")

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "staff/patient_demographics.html",
                patient=patient, demo=demo, data=data, mask_id=mask_id,
                mask_encrypted_id=mask_encrypted_id, read_only=read_only,
            )

        if not demo:
            demo = PatientDemographics(user_id=patient_id)
            for field in PLAIN_FIELDS:
                setattr(demo, field, data.get(field))
            for raw_field, db_field in [("insurance_id", "insurance_id_encrypted"), ("government_id", "government_id_encrypted")]:
                raw_val = data.get(raw_field)
                setattr(demo, db_field, encrypt_value(raw_val) if raw_val else None)
            db.session.add(demo)
            db.session.commit()
            flash("Demographics created.", "success")
        else:
            _save_demographics(demo, data, current_user.id)
            db.session.commit()
            flash("Demographics updated.", "success")

        return redirect(url_for("staff.patient_demographics", patient_id=patient_id))

    return render_template(
        "staff/patient_demographics.html",
        patient=patient, demo=demo, mask_id=mask_id,
        mask_encrypted_id=mask_encrypted_id, read_only=read_only,
    )


@staff_bp.route("/patients/<int:patient_id>/demographics/reveal", methods=["POST"])
@role_required("administrator", "front_desk")
@antireplay
def reveal_field(patient_id):
    demo = PatientDemographics.query.filter_by(user_id=patient_id).first()
    if not demo:
        return "", 404

    field = request.form.get("field", "")
    if field == "insurance_id" and demo.insurance_id_encrypted:
        return str(escape(decrypt_value(demo.insurance_id_encrypted)))
    elif field == "government_id" and demo.government_id_encrypted:
        return str(escape(decrypt_value(demo.government_id_encrypted)))
    return "", 404
