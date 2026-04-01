from datetime import datetime, timezone, timedelta, date, time
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.scheduling import (
    Clinician, ScheduleTemplate, Room, Slot, Reservation, Holiday, expire_stale_holds,
)
from app.utils.auth import role_required
from app.utils.antireplay import antireplay

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

HOLD_DURATION = timedelta(minutes=10)
MAX_SIMULTANEOUS_HOLDS = 2


@schedule_bp.before_request
def cleanup_expired():
    """Lazy expiry of stale holds on every schedule request."""
    try:
        expire_stale_holds()
    except Exception:
        pass


@schedule_bp.route("/available")
@login_required
def available():
    date_from = request.args.get("date_from", date.today().isoformat())
    date_to = request.args.get("date_to", (date.today() + timedelta(days=7)).isoformat())
    clinician_id = request.args.get("clinician_id", type=int)

    try:
        d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
    except ValueError:
        d_from = date.today()
        d_to = date.today() + timedelta(days=7)

    query = Slot.query.filter(
        Slot.date >= d_from,
        Slot.date <= d_to,
        Slot.status == "available",
    )
    if clinician_id:
        query = query.filter(Slot.clinician_id == clinician_id)

    slots = query.order_by(Slot.date, Slot.start_time).all()

    # Filter to only actually available slots
    available_slots = [s for s in slots if s.is_available]

    clinicians = Clinician.query.all()
    return render_template(
        "schedule/available.html",
        slots=available_slots,
        clinicians=clinicians,
        date_from=date_from,
        date_to=date_to,
        selected_clinician=clinician_id,
    )


@schedule_bp.route("/hold/<int:slot_id>", methods=["POST"])
@login_required
@antireplay
def hold(slot_id):
    slot = db.session.get(Slot, slot_id)
    if not slot:
        flash("Slot not found.", "danger")
        return redirect(url_for("schedule.available"))

    if slot.date < date.today():
        flash("Cannot book a slot in the past.", "danger")
        return redirect(url_for("schedule.available"))

    if not slot.is_available:
        flash("This slot is no longer available.", "warning")
        return redirect(url_for("schedule.available"))

    # Check max holds
    active_holds = Reservation.query.filter_by(
        patient_id=current_user.id, status="held"
    ).count()
    if active_holds >= MAX_SIMULTANEOUS_HOLDS:
        flash(f"You can only hold up to {MAX_SIMULTANEOUS_HOLDS} slots at a time.", "warning")
        return redirect(url_for("schedule.available"))

    reservation = Reservation(
        slot_id=slot.id,
        patient_id=current_user.id,
        status="held",
        held_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + HOLD_DURATION,
        request_token=request.form.get("request_token"),
    )
    db.session.add(reservation)
    db.session.commit()

    return redirect(url_for("schedule.confirm_page", reservation_id=reservation.id))


@schedule_bp.route("/confirm/<int:reservation_id>", methods=["GET"])
@login_required
def confirm_page(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if not reservation or reservation.patient_id != current_user.id:
        flash("Reservation not found.", "danger")
        return redirect(url_for("schedule.available"))

    if reservation.is_expired():
        reservation.status = "expired"
        db.session.commit()
        flash("Your reservation hold has expired.", "warning")
        return redirect(url_for("schedule.available"))

    remaining = 0
    if reservation.expires_at:
        exp = reservation.expires_at.replace(tzinfo=timezone.utc) if reservation.expires_at.tzinfo is None else reservation.expires_at
        remaining = max(0, int((exp - datetime.now(timezone.utc)).total_seconds()))

    return render_template(
        "schedule/confirm.html",
        reservation=reservation,
        slot=reservation.slot,
        remaining_seconds=remaining,
    )


@schedule_bp.route("/confirm/<int:reservation_id>", methods=["POST"])
@login_required
@antireplay
def confirm(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if not reservation or reservation.patient_id != current_user.id:
        flash("Reservation not found.", "danger")
        return redirect(url_for("schedule.available"))

    if reservation.is_expired():
        reservation.status = "expired"
        db.session.commit()
        flash("Your reservation hold has expired.", "warning")
        return redirect(url_for("schedule.available"))

    if reservation.status == "confirmed":
        flash("This reservation is already confirmed.", "info")
        return redirect(url_for("schedule.my_appointments"))

    reservation.status = "confirmed"
    reservation.confirmed_at = datetime.now(timezone.utc)
    reservation.slot.booked_count += 1
    db.session.commit()

    flash("Appointment confirmed!", "success")
    return redirect(url_for("schedule.my_appointments"))


@schedule_bp.route("/cancel/<int:reservation_id>", methods=["POST"])
@login_required
@antireplay
def cancel(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if not reservation:
        flash("Reservation not found.", "danger")
        return redirect(url_for("schedule.my_appointments"))

    # Allow patient to cancel own, or staff to cancel any
    if reservation.patient_id != current_user.id and current_user.role not in ("administrator", "front_desk"):
        flash("Access denied.", "danger")
        return redirect(url_for("schedule.my_appointments"))

    if reservation.status == "confirmed":
        reservation.slot.booked_count = max(0, reservation.slot.booked_count - 1)
    reservation.status = "canceled"
    db.session.commit()

    flash("Reservation canceled.", "info")
    return redirect(url_for("schedule.my_appointments"))


@schedule_bp.route("/my-appointments")
@login_required
def my_appointments():
    reservations = Reservation.query.filter_by(
        patient_id=current_user.id
    ).filter(
        Reservation.status.in_(["held", "confirmed"])
    ).order_by(Reservation.held_at.desc()).all()
    return render_template("schedule/my_appointments.html", reservations=reservations)


# ── Staff calendar view ──
@schedule_bp.route("/staff/calendar")
@role_required("administrator", "clinician", "front_desk")
def staff_calendar():
    week_str = request.args.get("week")
    clinician_id = request.args.get("clinician_id", type=int)

    if week_str:
        try:
            week_start = datetime.strptime(week_str, "%Y-%m-%d").date()
        except ValueError:
            week_start = date.today() - timedelta(days=date.today().weekday())
    else:
        week_start = date.today() - timedelta(days=date.today().weekday())

    week_end = week_start + timedelta(days=6)

    query = Slot.query.filter(Slot.date >= week_start, Slot.date <= week_end)
    if clinician_id:
        query = query.filter(Slot.clinician_id == clinician_id)
    slots = query.order_by(Slot.date, Slot.start_time).all()

    clinicians = Clinician.query.all()
    holidays = Holiday.query.filter(Holiday.date >= week_start, Holiday.date <= week_end).all()
    holiday_dates = {h.date for h in holidays}

    prev_week = (week_start - timedelta(days=7)).isoformat()
    next_week = (week_start + timedelta(days=7)).isoformat()

    return render_template(
        "schedule/staff_calendar.html",
        slots=slots, clinicians=clinicians,
        week_start=week_start, week_end=week_end,
        prev_week=prev_week, next_week=next_week,
        selected_clinician=clinician_id,
        holiday_dates=holiday_dates,
    )


# ── Admin: holidays ──
@schedule_bp.route("/admin/holidays", methods=["GET", "POST"])
@role_required("administrator")
def holidays():
    if request.method == "POST":
        holiday_date = request.form.get("date", "").strip()
        holiday_name = request.form.get("name", "").strip()
        if holiday_date and holiday_name:
            try:
                d = datetime.strptime(holiday_date, "%Y-%m-%d").date()
                existing = Holiday.query.filter_by(date=d).first()
                if not existing:
                    h = Holiday(date=d, name=holiday_name, created_by=current_user.id)
                    db.session.add(h)
                    # Block all slots on this date
                    Slot.query.filter_by(date=d).update({"status": "holiday"})
                    db.session.commit()
                    flash("Holiday added.", "success")
                else:
                    flash("Holiday already exists for this date.", "warning")
            except ValueError:
                flash("Invalid date.", "danger")
        return redirect(url_for("schedule.holidays"))

    all_holidays = Holiday.query.order_by(Holiday.date).all()
    return render_template("schedule/holidays.html", holidays=all_holidays)


@schedule_bp.route("/admin/holidays/<int:holiday_id>/delete", methods=["POST"])
@role_required("administrator")
def delete_holiday(holiday_id):
    h = db.session.get(Holiday, holiday_id)
    if h:
        Slot.query.filter_by(date=h.date, status="holiday").update({"status": "available"})
        db.session.delete(h)
        db.session.commit()
        flash("Holiday removed.", "info")
    return redirect(url_for("schedule.holidays"))


# ── Admin: bulk generate ──
@schedule_bp.route("/admin/bulk-generate", methods=["GET", "POST"])
@role_required("administrator")
def bulk_generate():
    clinicians = Clinician.query.all()

    if request.method == "POST":
        clinician_id = request.form.get("clinician_id", type=int)
        date_from = request.form.get("date_from", "").strip()
        date_to = request.form.get("date_to", "").strip()

        if not clinician_id or not date_from or not date_to:
            flash("All fields are required.", "danger")
            return render_template("schedule/bulk_generate.html", clinicians=clinicians)

        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid dates.", "danger")
            return render_template("schedule/bulk_generate.html", clinicians=clinicians)

        templates = ScheduleTemplate.query.filter_by(clinician_id=clinician_id).all()
        if not templates:
            flash("No schedule template found for this clinician.", "warning")
            return render_template("schedule/bulk_generate.html", clinicians=clinicians)

        holiday_dates = {h.date for h in Holiday.query.filter(Holiday.date >= d_from, Holiday.date <= d_to).all()}

        created = 0
        current = d_from
        while current <= d_to:
            if current in holiday_dates:
                current += timedelta(days=1)
                continue

            dow = current.weekday()
            for tmpl in templates:
                if tmpl.day_of_week != dow:
                    continue

                # Generate slots
                t = datetime.combine(current, tmpl.start_time)
                end = datetime.combine(current, tmpl.end_time)
                while t < end:
                    slot_end_time = (t + timedelta(minutes=tmpl.slot_duration)).time()
                    existing = Slot.query.filter_by(
                        clinician_id=clinician_id, date=current, start_time=t.time()
                    ).first()
                    if not existing:
                        slot = Slot(
                            clinician_id=clinician_id,
                            date=current,
                            start_time=t.time(),
                            end_time=slot_end_time,
                            capacity=tmpl.capacity,
                        )
                        db.session.add(slot)
                        created += 1
                    t += timedelta(minutes=tmpl.slot_duration)

            current += timedelta(days=1)

        db.session.commit()
        flash(f"Generated {created} slots.", "success")
        return redirect(url_for("schedule.bulk_generate"))

    return render_template("schedule/bulk_generate.html", clinicians=clinicians)
