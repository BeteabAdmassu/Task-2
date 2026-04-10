import threading
import uuid
from datetime import datetime, timezone, timedelta, date, time
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.extensions import db
from app.models.scheduling import (
    Clinician, ScheduleTemplate, Room, Slot, Reservation, Holiday, expire_stale_holds,
)
from app.models.visit import Visit
from app.utils.auth import role_required
from app.utils.antireplay import antireplay
from app.utils.idempotency import hash_token as _hash_token

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

HOLD_DURATION = timedelta(minutes=10)
MAX_SIMULTANEOUS_HOLDS = 2

# Serialise the capacity-check + flush + recount window so that concurrent
# threads in a single-process deployment (Werkzeug, SQLite) cannot both read
# "slot available" before either commits.  For multi-process deployments the
# database's own serialisation (row locks / SERIALIZABLE isolation) takes over.
_HOLD_CAPACITY_LOCK = threading.Lock()


def _has_room_conflict(room_id, slot_date, start_time, end_time, exclude_slot_id=None):
    """Return True if a slot already occupies room_id during [start_time, end_time) on slot_date."""
    if room_id is None:
        return False
    query = Slot.query.filter(
        Slot.room_id == room_id,
        Slot.date == slot_date,
        Slot.start_time < end_time,
        Slot.end_time > start_time,
    )
    if exclude_slot_id is not None:
        query = query.filter(Slot.id != exclude_slot_id)
    return query.first() is not None


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
    # Generate a fresh UUID per slot so every hold form has a unique request_token.
    slot_tokens = {s.id: str(uuid.uuid4()) for s in available_slots}
    return render_template(
        "schedule/available.html",
        slots=available_slots,
        clinicians=clinicians,
        date_from=date_from,
        date_to=date_to,
        selected_clinician=clinician_id,
        slot_tokens=slot_tokens,
    )


@schedule_bp.route("/hold/<int:slot_id>", methods=["POST"])
@role_required("patient")
@antireplay
def hold(slot_id):
    slot = db.session.get(Slot, slot_id)
    if not slot:
        flash("Slot not found.", "danger")
        return redirect(url_for("schedule.available"))

    if slot.date < date.today():
        flash("Cannot book a slot in the past.", "danger")
        return redirect(url_for("schedule.available"))

    # request_token is mandatory — check early so replays are handled before
    # availability checks (a replayed token must return a deterministic result
    # even if the slot is now full).
    raw_token = request.form.get("request_token", "").strip()
    if not raw_token:
        msg = "A request token is required to hold a slot."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 422
        flash(msg, "danger")
        return redirect(url_for("schedule.available"))

    token_hash = _hash_token(raw_token)

    # Idempotency: if this token was already used by this patient, return the
    # previous result rather than creating a duplicate reservation.
    existing = Reservation.query.filter_by(
        patient_id=current_user.id,
        request_token=token_hash,
    ).first()
    if existing:
        if existing.status == "held" and not existing.is_expired():
            return redirect(url_for("schedule.confirm_page", reservation_id=existing.id))
        if existing.status == "confirmed":
            flash("This appointment has already been confirmed.", "info")
            return redirect(url_for("schedule.my_appointments"))
        # Token consumed by an expired or cancelled hold — reject replay.
        flash("This request token has already been used. Please refresh to book again.", "warning")
        return redirect(url_for("schedule.available"))

    with _HOLD_CAPACITY_LOCK:
        # Roll back any open read-only transaction so the availability query
        # gets a fresh WAL snapshot that includes reservations committed by
        # concurrent threads while we waited for the lock.
        db.session.rollback()

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
            # Store SHA-256 hash — raw token never persisted.
            request_token=token_hash,
        )
        db.session.add(reservation)
        db.session.flush()

        active_count = Reservation.query.filter(
            Reservation.slot_id == slot.id,
            Reservation.status.in_(["held", "confirmed"]),
        ).count()
        if active_count > slot.capacity:
            db.session.rollback()
            flash("This slot is no longer available.", "warning")
            return redirect(url_for("schedule.available"))

        db.session.commit()
    return redirect(url_for("schedule.confirm_page", reservation_id=reservation.id))


@schedule_bp.route("/confirm/<int:reservation_id>", methods=["GET"])
@role_required("patient")
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
@role_required("patient")
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

    # Idempotently create a Visit record for this booking.
    # Using slot_id + patient_id as the uniqueness key prevents duplicates
    # even if confirm is somehow called twice on separate requests.
    existing_visit = Visit.query.filter_by(
        patient_id=reservation.patient_id,
        slot_id=reservation.slot_id,
    ).first()
    if not existing_visit:
        visit = Visit(
            patient_id=reservation.patient_id,
            clinician_id=reservation.slot.clinician_id,
            slot_id=reservation.slot_id,
            status="booked",
        )
        db.session.add(visit)

    db.session.commit()

    flash("Appointment confirmed!", "success")
    return redirect(url_for("schedule.my_appointments"))


@schedule_bp.route("/cancel/<int:reservation_id>", methods=["POST"])
@role_required("patient")
@antireplay
def cancel(reservation_id):
    reservation = db.session.get(Reservation, reservation_id)
    if not reservation:
        flash("Reservation not found.", "danger")
        return redirect(url_for("schedule.my_appointments"))

    if reservation.patient_id != current_user.id:
        flash("Access denied.", "danger")
        return redirect(url_for("schedule.my_appointments"))

    if reservation.status == "confirmed":
        reservation.slot.booked_count = max(0, reservation.slot.booked_count - 1)
    reservation.status = "canceled"
    db.session.commit()

    flash("Reservation canceled.", "info")
    return redirect(url_for("schedule.my_appointments"))


# ── On-behalf scheduling routes (administrator / front_desk only) ──

def _get_behalf_schedule_patient(patient_id):
    """Return (User, None) if patient_id is a patient-role user,
    otherwise return (None, redirect_response)."""
    from app.models.user import User
    patient = db.session.get(User, patient_id)
    if not patient:
        flash("Patient not found.", "danger")
        return None, redirect(url_for("schedule.available"))
    if patient.role != "patient":
        flash("Selected user is not a patient.", "danger")
        return None, redirect(url_for("schedule.available"))
    return patient, None


@schedule_bp.route("/behalf/<int:patient_id>/hold/<int:slot_id>", methods=["POST"])
@role_required("administrator", "front_desk")
@antireplay
def behalf_hold(patient_id, slot_id):
    """Staff places a hold on a slot on behalf of a patient."""
    from app.utils.audit import log_action

    patient, err = _get_behalf_schedule_patient(patient_id)
    if err:
        return err

    slot = db.session.get(Slot, slot_id)
    if not slot:
        flash("Slot not found.", "danger")
        return redirect(url_for("schedule.available"))

    if slot.date < date.today():
        flash("Cannot book a slot in the past.", "danger")
        return redirect(url_for("schedule.available"))

    # request_token is mandatory — check early so replays are handled before
    # availability checks (a replayed token must return a deterministic result
    # even if the slot is now full).
    raw_token = request.form.get("request_token", "").strip()
    if not raw_token:
        msg = "A request token is required to hold a slot."
        if request.headers.get("HX-Request"):
            return f'<span class="field-error">{msg}</span>', 422
        flash(msg, "danger")
        return redirect(url_for("schedule.available"))

    token_hash = _hash_token(raw_token)

    # Idempotency: if this token was already used for this patient, return the
    # previous result rather than creating a duplicate reservation.
    existing = Reservation.query.filter_by(
        patient_id=patient_id,
        request_token=token_hash,
    ).first()
    if existing:
        if existing.status == "held" and not existing.is_expired():
            return redirect(url_for(
                "schedule.behalf_confirm_page",
                patient_id=patient_id,
                reservation_id=existing.id,
            ))
        if existing.status == "confirmed":
            flash("This appointment has already been confirmed.", "info")
            return redirect(url_for("schedule.available"))
        # Token consumed by an expired or cancelled hold — reject replay.
        flash("This request token has already been used. Please try again with a new token.", "warning")
        return redirect(url_for("schedule.available"))

    with _HOLD_CAPACITY_LOCK:
        # Roll back any open read-only transaction so the availability query
        # gets a fresh WAL snapshot (see hold() for full explanation).
        db.session.rollback()

        if not slot.is_available:
            flash("This slot is no longer available.", "warning")
            return redirect(url_for("schedule.available"))

        active_holds = Reservation.query.filter_by(
            patient_id=patient_id, status="held"
        ).count()
        if active_holds >= MAX_SIMULTANEOUS_HOLDS:
            flash(f"Patient already has {MAX_SIMULTANEOUS_HOLDS} active holds.", "warning")
            return redirect(url_for("schedule.available"))

        reservation = Reservation(
            slot_id=slot.id,
            patient_id=patient_id,
            status="held",
            held_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + HOLD_DURATION,
            request_token=token_hash,
        )
        db.session.add(reservation)
        db.session.flush()

        active_count = Reservation.query.filter(
            Reservation.slot_id == slot.id,
            Reservation.status.in_(["held", "confirmed"]),
        ).count()
        if active_count > slot.capacity:
            db.session.rollback()
            flash("This slot is no longer available.", "warning")
            return redirect(url_for("schedule.available"))

        db.session.commit()

    log_action(
        action="on_behalf_hold",
        resource_type="reservation",
        resource_id=reservation.id,
        details={
            "actor_id": current_user.id,
            "actor_role": current_user.role,
            "patient_id": patient_id,
            "slot_id": slot_id,
            "context": "staff held slot on behalf of patient",
        },
    )

    return redirect(url_for("schedule.behalf_confirm_page", patient_id=patient_id, reservation_id=reservation.id))


@schedule_bp.route("/behalf/<int:patient_id>/confirm/<int:reservation_id>", methods=["GET"])
@role_required("administrator", "front_desk")
def behalf_confirm_page(patient_id, reservation_id):
    """Staff reviews the held reservation before confirming."""
    patient, err = _get_behalf_schedule_patient(patient_id)
    if err:
        return err

    reservation = db.session.get(Reservation, reservation_id)
    if not reservation or reservation.patient_id != patient_id:
        flash("Reservation not found.", "danger")
        return redirect(url_for("schedule.available"))

    if reservation.is_expired():
        reservation.status = "expired"
        db.session.commit()
        flash("The reservation hold has expired.", "warning")
        return redirect(url_for("schedule.available"))

    remaining = 0
    if reservation.expires_at:
        exp = reservation.expires_at.replace(tzinfo=timezone.utc) if reservation.expires_at.tzinfo is None else reservation.expires_at
        remaining = max(0, int((exp - datetime.now(timezone.utc)).total_seconds()))

    return render_template(
        "schedule/behalf_confirm.html",
        reservation=reservation,
        slot=reservation.slot,
        remaining_seconds=remaining,
        patient=patient,
    )


@schedule_bp.route("/behalf/<int:patient_id>/confirm/<int:reservation_id>", methods=["POST"])
@role_required("administrator", "front_desk")
@antireplay
def behalf_confirm(patient_id, reservation_id):
    """Staff confirms (books) the held reservation on behalf of a patient."""
    from app.utils.audit import log_action

    patient, err = _get_behalf_schedule_patient(patient_id)
    if err:
        return err

    reservation = db.session.get(Reservation, reservation_id)
    if not reservation or reservation.patient_id != patient_id:
        flash("Reservation not found.", "danger")
        return redirect(url_for("schedule.available"))

    if reservation.is_expired():
        reservation.status = "expired"
        db.session.commit()
        flash("The reservation hold has expired.", "warning")
        return redirect(url_for("schedule.available"))

    if reservation.status == "confirmed":
        flash("This reservation is already confirmed.", "info")
        return redirect(url_for("schedule.staff_calendar"))

    reservation.status = "confirmed"
    reservation.confirmed_at = datetime.now(timezone.utc)
    reservation.slot.booked_count += 1

    existing_visit = Visit.query.filter_by(
        patient_id=patient_id,
        slot_id=reservation.slot_id,
    ).first()
    if not existing_visit:
        visit = Visit(
            patient_id=patient_id,
            clinician_id=reservation.slot.clinician_id,
            slot_id=reservation.slot_id,
            status="booked",
        )
        db.session.add(visit)

    db.session.commit()

    log_action(
        action="on_behalf_confirm",
        resource_type="reservation",
        resource_id=reservation.id,
        details={
            "actor_id": current_user.id,
            "actor_role": current_user.role,
            "patient_id": patient_id,
            "slot_id": reservation.slot_id,
            "context": "staff confirmed booking on behalf of patient",
        },
    )

    flash("Appointment confirmed!", "success")
    return redirect(url_for("schedule.staff_calendar"))


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
@antireplay
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
@antireplay
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
@antireplay
def bulk_generate():
    clinicians = Clinician.query.all()

    rooms = Room.query.filter_by(is_active=True).order_by(Room.name).all()

    if request.method == "POST":
        clinician_id = request.form.get("clinician_id", type=int)
        date_from = request.form.get("date_from", "").strip()
        date_to = request.form.get("date_to", "").strip()
        room_id = request.form.get("room_id", type=int) or None

        if not clinician_id or not date_from or not date_to:
            flash("All fields are required.", "danger")
            return render_template("schedule/bulk_generate.html", clinicians=clinicians, rooms=rooms)

        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid dates.", "danger")
            return render_template("schedule/bulk_generate.html", clinicians=clinicians, rooms=rooms)

        templates = ScheduleTemplate.query.filter_by(clinician_id=clinician_id).all()
        if not templates:
            flash("No schedule template found for this clinician.", "warning")
            return render_template("schedule/bulk_generate.html", clinicians=clinicians, rooms=rooms)

        holiday_dates = {h.date for h in Holiday.query.filter(Holiday.date >= d_from, Holiday.date <= d_to).all()}

        created = 0
        skipped_conflicts = 0
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
                        if _has_room_conflict(room_id, current, t.time(), slot_end_time):
                            skipped_conflicts += 1
                        else:
                            slot = Slot(
                                clinician_id=clinician_id,
                                room_id=room_id,
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
        msg = f"Generated {created} slots."
        if skipped_conflicts:
            msg += f" Skipped {skipped_conflicts} slot(s) due to room conflicts."
        flash(msg, "success")
        return redirect(url_for("schedule.bulk_generate"))

    return render_template("schedule/bulk_generate.html", clinicians=clinicians, rooms=rooms)
