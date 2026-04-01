from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from app.extensions import db
from app.models.coverage import CoverageZone, ZoneAssignment
from app.models.scheduling import Clinician
from app.utils.auth import role_required
from app.utils.audit import log_action

coverage_bp = Blueprint("coverage", __name__, url_prefix="/coverage")


@coverage_bp.route("/zones")
@role_required("administrator")
def zones():
    all_zones = CoverageZone.query.order_by(CoverageZone.name).all()
    return render_template("coverage/zones.html", zones=all_zones)


@coverage_bp.route("/zones", methods=["POST"])
@role_required("administrator")
def create_zone():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    zip_codes_raw = request.form.get("zip_codes", "").strip()

    if not name:
        flash("Zone name is required.", "danger")
        return redirect(url_for("coverage.zones"))

    zip_codes = [z.strip() for z in zip_codes_raw.split(",") if z.strip()]

    existing = CoverageZone.query.filter_by(name=name).first()
    if existing:
        flash("A zone with this name already exists.", "danger")
        return redirect(url_for("coverage.zones"))

    zone = CoverageZone(name=name, description=description, zip_codes_json=zip_codes)
    db.session.add(zone)
    db.session.commit()

    log_action("create_zone", "coverage_zone", zone.id, {"name": name})
    flash(f"Zone '{name}' created.", "success")
    return redirect(url_for("coverage.zones"))


@coverage_bp.route("/zones/<int:zone_id>")
@role_required("administrator")
def zone_detail(zone_id):
    zone = db.session.get(CoverageZone, zone_id)
    if not zone:
        flash("Zone not found.", "danger")
        return redirect(url_for("coverage.zones"))
    clinicians = Clinician.query.all()
    return render_template("coverage/zone_detail.html", zone=zone, clinicians=clinicians)


@coverage_bp.route("/zones/<int:zone_id>/assign", methods=["POST"])
@role_required("administrator")
def assign_clinician(zone_id):
    zone = db.session.get(CoverageZone, zone_id)
    if not zone:
        flash("Zone not found.", "danger")
        return redirect(url_for("coverage.zones"))

    clinician_id = request.form.get("clinician_id", type=int)
    assignment_type = request.form.get("assignment_type", "primary").strip()

    if assignment_type not in ("primary", "backup"):
        flash("Invalid assignment type.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    clinician = db.session.get(Clinician, clinician_id)
    if not clinician:
        flash("Clinician not found.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    existing = ZoneAssignment.query.filter_by(zone_id=zone_id, clinician_id=clinician_id).first()
    if existing:
        existing.assignment_type = assignment_type
    else:
        assignment = ZoneAssignment(zone_id=zone_id, clinician_id=clinician_id, assignment_type=assignment_type)
        db.session.add(assignment)

    db.session.commit()
    log_action("assign_clinician", "coverage_zone", zone_id, {
        "clinician_id": clinician_id, "type": assignment_type
    })
    flash("Clinician assigned to zone.", "success")
    return redirect(url_for("coverage.zone_detail", zone_id=zone_id))


@coverage_bp.route("/check")
def check_coverage():
    zip_code = request.args.get("zip", "").strip()
    if not zip_code:
        return jsonify({"covered": False, "message": "No ZIP code provided"}), 400

    zones = CoverageZone.query.filter_by(is_active=True).all()
    matching = []
    for zone in zones:
        zips = zone.zip_codes_json or []
        if zip_code in zips:
            matching.append({"id": zone.id, "name": zone.name})

    if matching:
        return jsonify({"covered": True, "zones": matching})
    return jsonify({"covered": False, "zones": []})
