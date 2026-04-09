from datetime import time as dt_time
from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required
from app.extensions import db
from app.models.coverage import CoverageZone, ZoneAssignment, ZoneDeliveryWindow
from app.models.scheduling import Clinician
from app.utils.auth import role_required
from app.utils.audit import log_action
from app.utils.antireplay import antireplay

VALID_DAYS = {
    "all", "monday", "tuesday", "wednesday",
    "thursday", "friday", "saturday", "sunday",
}


def _parse_time(value: str):
    """Parse an HH:MM string into a time object, returning None on failure."""
    try:
        parts = value.strip().split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError, AttributeError):
        return None


def _validate_window_fields(day, start_str, end_str):
    """Validate day/time fields shared by create and update.

    Returns (start_time, end_time, errors) where errors is a list of
    human-readable strings. start_time/end_time are None when parsing failed.
    """
    errors = []
    if day not in VALID_DAYS:
        errors.append(
            f"Invalid day '{day}'. Must be one of: {', '.join(sorted(VALID_DAYS))}."
        )

    start_time = _parse_time(start_str)
    end_time = _parse_time(end_str)

    if start_time is None:
        errors.append("Invalid start time format — use HH:MM.")
    if end_time is None:
        errors.append("Invalid end time format — use HH:MM.")
    if start_time and end_time and start_time >= end_time:
        errors.append("Start time must be before end time.")

    return start_time, end_time, errors


def _has_overlap(zone_id, day, start_time, end_time, exclude_id=None):
    """Return True if any window for zone_id/day overlaps the given time range.

    Overlap rule: existing.start < new_end AND new_start < existing.end.
    Pass exclude_id to skip the window being updated.
    """
    query = ZoneDeliveryWindow.query.filter_by(zone_id=zone_id, day_of_week=day)
    if exclude_id is not None:
        query = query.filter(ZoneDeliveryWindow.id != exclude_id)
    for w in query.all():
        if w.start_time < end_time and start_time < w.end_time:
            return True
    return False

coverage_bp = Blueprint("coverage", __name__, url_prefix="/coverage")


@coverage_bp.route("/zones")
@role_required("administrator")
def zones():
    all_zones = CoverageZone.query.order_by(CoverageZone.name).all()
    return render_template("coverage/zones.html", zones=all_zones)


@coverage_bp.route("/zones", methods=["POST"])
@role_required("administrator")
@antireplay
def create_zone():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    zip_codes_raw = request.form.get("zip_codes", "").strip()

    if not name:
        flash("Zone name is required.", "danger")
        return redirect(url_for("coverage.zones"))

    distance_band_min = request.form.get("distance_band_min", 0, type=float)
    distance_band_max = request.form.get("distance_band_max", 0, type=float)
    min_order_amount = request.form.get("min_order_amount", 0, type=float)
    delivery_fee = request.form.get("delivery_fee", 0, type=float)

    zip_codes = [z.strip() for z in zip_codes_raw.split(",") if z.strip()]

    neighborhoods_raw = request.form.get("neighborhoods", "").strip()
    neighborhoods = [n.strip() for n in neighborhoods_raw.split(",") if n.strip()]

    if min_order_amount < 0:
        flash("Minimum order amount must be non-negative.", "danger")
        return redirect(url_for("coverage.zones"))
    if delivery_fee < 0:
        flash("Delivery fee must be non-negative.", "danger")
        return redirect(url_for("coverage.zones"))
    if distance_band_min < 0 or distance_band_max < 0:
        flash("Distance bands must be non-negative.", "danger")
        return redirect(url_for("coverage.zones"))
    if distance_band_max > 0 and distance_band_min > distance_band_max:
        flash("Minimum distance band cannot exceed maximum.", "danger")
        return redirect(url_for("coverage.zones"))

    existing = CoverageZone.query.filter_by(name=name).first()
    if existing:
        flash("A zone with this name already exists.", "danger")
        return redirect(url_for("coverage.zones"))

    # Check ZIP uniqueness across active zones
    if zip_codes:
        active_zones = CoverageZone.query.filter_by(is_active=True).all()
        for az in active_zones:
            existing_zips = set(az.zip_codes_json or [])
            overlap = existing_zips & set(zip_codes)
            if overlap:
                flash(f"ZIP code(s) {', '.join(sorted(overlap))} already assigned to active zone '{az.name}'.", "danger")
                return redirect(url_for("coverage.zones"))

    zone = CoverageZone(
        name=name,
        description=description,
        zip_codes_json=zip_codes,
        neighborhoods_json=neighborhoods,
        distance_band_min=distance_band_min,
        distance_band_max=distance_band_max,
        min_order_amount=min_order_amount,
        delivery_fee=delivery_fee,
    )
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


@coverage_bp.route("/zones/<int:zone_id>", methods=["POST"])
@role_required("administrator")
@antireplay
def update_zone(zone_id):
    """Update an existing coverage zone."""
    zone = db.session.get(CoverageZone, zone_id)
    if not zone:
        flash("Zone not found.", "danger")
        return redirect(url_for("coverage.zones"))

    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    zip_codes_raw = request.form.get("zip_codes", "").strip()

    if not name:
        flash("Zone name is required.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    distance_band_min = request.form.get("distance_band_min", 0, type=float)
    distance_band_max = request.form.get("distance_band_max", 0, type=float)
    min_order_amount = request.form.get("min_order_amount", 0, type=float)
    delivery_fee = request.form.get("delivery_fee", 0, type=float)

    if min_order_amount < 0:
        flash("Minimum order amount must be non-negative.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))
    if delivery_fee < 0:
        flash("Delivery fee must be non-negative.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))
    if distance_band_min < 0 or distance_band_max < 0:
        flash("Distance bands must be non-negative.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))
    if distance_band_max > 0 and distance_band_min > distance_band_max:
        flash("Minimum distance band cannot exceed maximum.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    zip_codes = [z.strip() for z in zip_codes_raw.split(",") if z.strip()]
    neighborhoods_raw = request.form.get("neighborhoods", "").strip()
    neighborhoods = [n.strip() for n in neighborhoods_raw.split(",") if n.strip()]

    # Check name uniqueness (excluding self)
    existing = CoverageZone.query.filter(
        CoverageZone.name == name, CoverageZone.id != zone_id
    ).first()
    if existing:
        flash("A zone with this name already exists.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    # Check ZIP uniqueness across other active zones
    if zip_codes:
        active_zones = CoverageZone.query.filter(
            CoverageZone.is_active == True, CoverageZone.id != zone_id
        ).all()
        for az in active_zones:
            existing_zips = set(az.zip_codes_json or [])
            overlap = existing_zips & set(zip_codes)
            if overlap:
                flash(f"ZIP code(s) {', '.join(sorted(overlap))} already assigned to active zone '{az.name}'.", "danger")
                return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    zone.name = name
    zone.description = description
    zone.zip_codes_json = zip_codes
    zone.neighborhoods_json = neighborhoods
    zone.distance_band_min = distance_band_min
    zone.distance_band_max = distance_band_max
    zone.min_order_amount = min_order_amount
    zone.delivery_fee = delivery_fee
    db.session.commit()

    log_action("update_zone", "coverage_zone", zone.id, {"name": name})
    flash(f"Zone '{name}' updated.", "success")
    return redirect(url_for("coverage.zone_detail", zone_id=zone_id))


@coverage_bp.route("/zones/<int:zone_id>/deactivate", methods=["POST"])
@role_required("administrator")
@antireplay
def deactivate_zone(zone_id):
    """Soft-deactivate a coverage zone."""
    zone = db.session.get(CoverageZone, zone_id)
    if not zone:
        flash("Zone not found.", "danger")
        return redirect(url_for("coverage.zones"))

    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("A reason is required to deactivate a zone.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    zone.is_active = False
    db.session.commit()

    log_action("deactivate_zone", "coverage_zone", zone.id, {"name": zone.name, "reason": reason})
    flash(f"Zone '{zone.name}' deactivated.", "info")
    return redirect(url_for("coverage.zones"))


@coverage_bp.route("/zones/<int:zone_id>/assign", methods=["POST"])
@role_required("administrator")
@antireplay
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


@coverage_bp.route("/zones/<int:zone_id>/windows", methods=["POST"])
@role_required("administrator")
@antireplay
def create_window(zone_id):
    """Create a delivery window for a coverage zone."""
    zone = db.session.get(CoverageZone, zone_id)
    if not zone:
        flash("Zone not found.", "danger")
        return redirect(url_for("coverage.zones"))

    day = request.form.get("day_of_week", "").strip().lower()
    start_str = request.form.get("start_time", "").strip()
    end_str = request.form.get("end_time", "").strip()

    start_time, end_time, errors = _validate_window_fields(day, start_str, end_str)

    if not errors and _has_overlap(zone_id, day, start_time, end_time):
        errors.append(
            "This window overlaps an existing delivery window for the same day."
        )

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    window = ZoneDeliveryWindow(
        zone_id=zone_id,
        day_of_week=day,
        start_time=start_time,
        end_time=end_time,
    )
    db.session.add(window)
    db.session.commit()
    log_action("create_delivery_window", "coverage_zone", zone_id, {
        "day_of_week": day, "start_time": start_str, "end_time": end_str,
    })
    flash("Delivery window added.", "success")
    return redirect(url_for("coverage.zone_detail", zone_id=zone_id))


@coverage_bp.route("/zones/<int:zone_id>/windows/<int:window_id>/delete", methods=["POST"])
@role_required("administrator")
@antireplay
def delete_window(zone_id, window_id):
    """Delete a delivery window from a coverage zone."""
    window = db.session.get(ZoneDeliveryWindow, window_id)
    if not window or window.zone_id != zone_id:
        flash("Delivery window not found.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    db.session.delete(window)
    db.session.commit()
    log_action("delete_delivery_window", "coverage_zone", zone_id, {"window_id": window_id})
    flash("Delivery window removed.", "info")
    return redirect(url_for("coverage.zone_detail", zone_id=zone_id))


@coverage_bp.route("/zones/<int:zone_id>/windows/<int:window_id>/update", methods=["POST"])
@role_required("administrator")
@antireplay
def update_window(zone_id, window_id):
    """Update an existing delivery window for a coverage zone."""
    window = db.session.get(ZoneDeliveryWindow, window_id)
    if not window or window.zone_id != zone_id:
        flash("Delivery window not found.", "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    day = request.form.get("day_of_week", "").strip().lower()
    start_str = request.form.get("start_time", "").strip()
    end_str = request.form.get("end_time", "").strip()

    start_time, end_time, errors = _validate_window_fields(day, start_str, end_str)

    if not errors and _has_overlap(zone_id, day, start_time, end_time, exclude_id=window_id):
        errors.append(
            "This window overlaps an existing delivery window for the same day."
        )

    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("coverage.zone_detail", zone_id=zone_id))

    window.day_of_week = day
    window.start_time = start_time
    window.end_time = end_time
    db.session.commit()
    log_action("update_delivery_window", "coverage_zone", zone_id, {
        "window_id": window_id, "day_of_week": day,
        "start_time": start_str, "end_time": end_str,
    })
    flash("Delivery window updated.", "success")
    return redirect(url_for("coverage.zone_detail", zone_id=zone_id))


@coverage_bp.route("/check")
@role_required("patient", "front_desk")
def check_coverage():
    """Check coverage for a given ZIP code, optional neighborhood, and optional distance.

    Query parameters:
      zip          – ZIP code string (required unless neighborhood is supplied)
      neighborhood – neighborhood name string (optional, alternative/additional to zip)
      distance     – non-negative float in miles from clinic (optional)

    Distance band logic:
      A zone whose distance_band_max > 0 will only be returned when the caller
      provides a `distance` value that falls within [distance_band_min, distance_band_max].
      Zones with distance_band_max == 0 (or null) have no distance constraint.

    Returns HTTP 400 for missing location identifiers or a non-numeric distance value.
    """
    zip_code = request.args.get("zip", "").strip()
    neighborhood = request.args.get("neighborhood", "").strip()
    distance_str = request.args.get("distance", "").strip()

    # Require at least one location identifier.
    if not zip_code and not neighborhood:
        return jsonify({"covered": False, "error": "zip or neighborhood is required"}), 400

    # Validate and parse distance if provided.
    distance = None
    if distance_str:
        try:
            distance = float(distance_str)
        except ValueError:
            return jsonify({"covered": False, "error": "distance must be a number"}), 400
        if distance < 0:
            return jsonify({"covered": False, "error": "distance must be non-negative"}), 400

    zones = CoverageZone.query.filter_by(is_active=True).all()
    matching = []
    for zone in zones:
        zips = zone.zip_codes_json or []
        neighborhoods = zone.neighborhoods_json or []

        # Location check: ZIP or neighborhood must match at least one configured value.
        zip_match = bool(zip_code) and zip_code in zips
        nbhd_match = bool(neighborhood) and neighborhood in neighborhoods

        if not zip_match and not nbhd_match:
            continue

        # Distance band check: only applied when the zone has a configured max band.
        band_max = zone.distance_band_max or 0
        if band_max > 0:
            if distance is None:
                # Zone requires a distance but caller did not provide one — skip.
                continue
            band_min = zone.distance_band_min or 0
            if not (band_min <= distance <= band_max):
                continue

        windows = []
        for w in zone.delivery_windows.all():
            windows.append({
                "day_of_week": w.day_of_week,
                "start_time": w.start_time.strftime("%H:%M") if w.start_time else None,
                "end_time": w.end_time.strftime("%H:%M") if w.end_time else None,
            })

        matching.append({
            "id": zone.id,
            "name": zone.name,
            "delivery_fee": zone.delivery_fee,
            "min_order_amount": zone.min_order_amount,
            "distance_band_min": zone.distance_band_min,
            "distance_band_max": zone.distance_band_max,
            "delivery_windows": windows,
        })

    if matching:
        return jsonify({"covered": True, "zones": matching})
    return jsonify({"covered": False, "zones": []})
