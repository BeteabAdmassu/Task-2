"""Seed test data for E2E testing."""

import os
import sys

# Only seed when explicitly requested
if os.environ.get("SEED_TEST_DATA") != "1":
    sys.exit(0)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.scheduling import Clinician, ScheduleTemplate, Slot, Room
from app.models.coverage import CoverageZone
from datetime import date, time, timedelta

app = create_app(os.environ.get("FLASK_ENV", "production"))

with app.app_context():
    # Create admin user
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", role="administrator")
        admin.set_password("Admin123")
        db.session.add(admin)

    # Create patient user
    if not User.query.filter_by(username="patient").first():
        patient = User(username="patient", role="patient")
        patient.set_password("Patient1")
        db.session.add(patient)

    # Create front desk user
    if not User.query.filter_by(username="frontdesk").first():
        fd = User(username="frontdesk", role="front_desk")
        fd.set_password("FrontDesk1")
        db.session.add(fd)

    # Create clinician user
    if not User.query.filter_by(username="drclinician").first():
        clin_user = User(username="drclinician", role="clinician")
        clin_user.set_password("Clinician1")
        db.session.add(clin_user)
        db.session.commit()

        clinician = Clinician(user_id=clin_user.id, specialty="General Medicine")
        db.session.add(clinician)
        db.session.commit()

        # Create schedule template (Mon-Fri 9-17)
        for dow in range(5):
            tmpl = ScheduleTemplate(
                clinician_id=clinician.id,
                day_of_week=dow,
                start_time=time(9, 0),
                end_time=time(17, 0),
                slot_duration=15,
                capacity=1,
            )
            db.session.add(tmpl)

        # Generate slots for next 7 days
        for d in range(1, 8):
            slot_date = date.today() + timedelta(days=d)
            if slot_date.weekday() >= 5:  # skip weekends
                continue
            t = time(9, 0)
            for s in range(32):  # 32 x 15min = 8 hours
                from datetime import datetime
                start = datetime.combine(slot_date, t)
                end_t = (start + timedelta(minutes=15)).time()
                slot = Slot(
                    clinician_id=clinician.id,
                    date=slot_date,
                    start_time=t,
                    end_time=end_t,
                    capacity=1,
                )
                db.session.add(slot)
                t = end_t
    else:
        db.session.commit()

    # Create a room
    if not Room.query.filter_by(name="Room 1").first():
        room = Room(name="Room 1", description="Main consultation room")
        db.session.add(room)

    # Create a coverage zone
    if not CoverageZone.query.filter_by(name="Downtown").first():
        zone = CoverageZone(
            name="Downtown",
            description="Downtown service area",
            zip_codes_json='["10001", "10002", "10003"]',
        )
        db.session.add(zone)

    db.session.commit()
    print("Test data seeded successfully.")
