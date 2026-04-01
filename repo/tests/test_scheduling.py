"""Tests for prompt 06 — scheduling."""

import uuid
import pytest
from datetime import date, time, timedelta, datetime, timezone
from app.models.user import User
from app.models.scheduling import Clinician, ScheduleTemplate, Slot, Reservation, Holiday, Room, expire_stale_holds
from app.extensions import db


def _nonce_data():
    """Return fresh nonce+timestamp form fields for antireplay-protected endpoints."""
    return {
        "_nonce": str(uuid.uuid4()),
        "_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _create_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, username, password="Password1"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


def _create_clinician_with_slot(app, username="doc1", slot_date=None):
    """Create a clinician user with one available slot."""
    with app.app_context():
        uid = _create_user.__wrapped__(app, username, role="clinician") if hasattr(_create_user, '__wrapped__') else None
        if uid is None:
            user = User(username=username, role="clinician")
            user.set_password("Password1")
            db.session.add(user)
            db.session.commit()
            uid = user.id

        clinician = Clinician(user_id=uid, specialty="General")
        db.session.add(clinician)
        db.session.commit()

        if slot_date is None:
            slot_date = date.today() + timedelta(days=1)

        slot = Slot(
            clinician_id=clinician.id,
            date=slot_date,
            start_time=time(9, 0),
            end_time=time(9, 15),
            capacity=1,
        )
        db.session.add(slot)
        db.session.commit()
        return uid, clinician.id, slot.id


def test_available_slots_page(client, app):
    _create_user(app, "pat_s1")
    _login(client, "pat_s1")
    resp = client.get("/schedule/available")
    assert resp.status_code == 200
    assert b"Available Appointments" in resp.data


def test_hold_slot(client, app):
    uid, cid, sid = _create_clinician_with_slot(app)
    pid = _create_user(app, "pat_s2")
    _login(client, "pat_s2")

    resp = client.post(f"/schedule/hold/{sid}", data=_nonce_data(), follow_redirects=True)
    assert resp.status_code == 200
    assert b"Confirm" in resp.data

    with app.app_context():
        r = Reservation.query.filter_by(slot_id=sid, patient_id=pid).first()
        assert r is not None
        assert r.status == "held"


def test_confirm_reservation(client, app):
    uid, cid, sid = _create_clinician_with_slot(app, "doc2")
    pid = _create_user(app, "pat_s3")
    _login(client, "pat_s3")

    client.post(f"/schedule/hold/{sid}", data=_nonce_data())

    with app.app_context():
        r = Reservation.query.filter_by(slot_id=sid).first()
        resp = client.post(f"/schedule/confirm/{r.id}", data=_nonce_data(), follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        r = Reservation.query.filter_by(slot_id=sid).first()
        assert r.status == "confirmed"


def test_cancel_reservation(client, app):
    uid, cid, sid = _create_clinician_with_slot(app, "doc3")
    pid = _create_user(app, "pat_s4")
    _login(client, "pat_s4")

    client.post(f"/schedule/hold/{sid}", data=_nonce_data())

    with app.app_context():
        r = Reservation.query.filter_by(slot_id=sid).first()
        resp = client.post(f"/schedule/cancel/{r.id}", data=_nonce_data(), follow_redirects=True)
        assert resp.status_code == 200

    with app.app_context():
        r = Reservation.query.filter_by(slot_id=sid).first()
        assert r.status == "canceled"


def test_cannot_book_past_slot(client, app):
    with app.app_context():
        user = User(username="doc_past", role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id)
        db.session.add(clinician)
        db.session.commit()
        slot = Slot(
            clinician_id=clinician.id,
            date=date.today() - timedelta(days=1),
            start_time=time(9, 0),
            end_time=time(9, 15),
        )
        db.session.add(slot)
        db.session.commit()
        sid = slot.id

    _create_user(app, "pat_s5")
    _login(client, "pat_s5")
    resp = client.post(f"/schedule/hold/{sid}", data=_nonce_data(), follow_redirects=True)
    assert b"past" in resp.data.lower()


def test_max_simultaneous_holds(client, app):
    with app.app_context():
        user = User(username="doc_holds", role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id)
        db.session.add(clinician)
        db.session.commit()

        slots = []
        for i in range(3):
            s = Slot(
                clinician_id=clinician.id,
                date=date.today() + timedelta(days=1),
                start_time=time(9 + i, 0),
                end_time=time(9 + i, 15),
            )
            db.session.add(s)
            slots.append(s)
        db.session.commit()
        slot_ids = [s.id for s in slots]

    _create_user(app, "pat_s6")
    _login(client, "pat_s6")

    client.post(f"/schedule/hold/{slot_ids[0]}", data=_nonce_data())
    client.post(f"/schedule/hold/{slot_ids[1]}", data=_nonce_data())
    resp = client.post(f"/schedule/hold/{slot_ids[2]}", data=_nonce_data(), follow_redirects=True)
    assert b"only hold" in resp.data.lower()


def test_hold_expiry(app):
    with app.app_context():
        user = User(username="doc_exp", role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id)
        db.session.add(clinician)
        db.session.commit()
        slot = Slot(clinician_id=clinician.id, date=date.today() + timedelta(days=1),
                    start_time=time(10, 0), end_time=time(10, 15))
        db.session.add(slot)
        db.session.commit()

        pat = User(username="pat_exp", role="patient")
        pat.set_password("Password1")
        db.session.add(pat)
        db.session.commit()

        r = Reservation(
            slot_id=slot.id, patient_id=pat.id, status="held",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.session.add(r)
        db.session.commit()

        expired = expire_stale_holds()
        assert expired == 1
        assert Reservation.query.first().status == "expired"


def test_holiday_blocks_slots(client, app):
    admin_id = _create_user(app, "admin_h1", role="administrator")
    _login(client, "admin_h1")

    with app.app_context():
        user = User(username="doc_h", role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id)
        db.session.add(clinician)
        db.session.commit()
        slot = Slot(clinician_id=clinician.id, date=date(2026, 12, 25),
                    start_time=time(9, 0), end_time=time(9, 15))
        db.session.add(slot)
        db.session.commit()

    resp = client.post("/schedule/admin/holidays", data={
        "date": "2026-12-25", "name": "Christmas",
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        slot = Slot.query.filter_by(date=date(2026, 12, 25)).first()
        assert slot.status == "holiday"


def test_bulk_generate(client, app):
    admin_id = _create_user(app, "admin_bg", role="administrator")
    _login(client, "admin_bg")

    with app.app_context():
        user = User(username="doc_bg", role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id)
        db.session.add(clinician)
        db.session.commit()
        # Monday template
        tmpl = ScheduleTemplate(
            clinician_id=clinician.id, day_of_week=0,
            start_time=time(9, 0), end_time=time(10, 0),
            slot_duration=15,
        )
        db.session.add(tmpl)
        db.session.commit()
        cid = clinician.id

    # Find next Monday
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)

    resp = client.post("/schedule/admin/bulk-generate", data={
        "clinician_id": str(cid),
        "date_from": next_monday.isoformat(),
        "date_to": next_monday.isoformat(),
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Generated" in resp.data

    with app.app_context():
        slots = Slot.query.filter_by(clinician_id=cid, date=next_monday).all()
        assert len(slots) == 4  # 9:00-10:00 = 4 x 15min slots


def test_staff_calendar(client, app):
    _create_user(app, "fd_cal", role="front_desk")
    _login(client, "fd_cal")
    resp = client.get("/schedule/staff/calendar")
    assert resp.status_code == 200
    assert b"Schedule" in resp.data


def test_my_appointments(client, app):
    _create_user(app, "pat_s7")
    _login(client, "pat_s7")
    resp = client.get("/schedule/my-appointments")
    assert resp.status_code == 200
    assert b"My Appointments" in resp.data
