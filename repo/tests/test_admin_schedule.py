"""Integration tests for admin clinician profile and schedule template management.

Covers F-01 finding: verifies that an admin can create clinician profiles and
schedule templates through the in-product UI, and that bulk slot generation
succeeds from a clean install using only in-product admin flows (no manual DB
seeding required).
"""

import pytest
from datetime import date, time, timedelta
from app.models.user import User
from app.models.scheduling import Clinician, ScheduleTemplate, Slot
from app.extensions import db
from tests.signing_helpers import signed_data, login_data


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
        data=login_data(username, password),
        follow_redirects=True,
    )


# ---------------------------------------------------------------------------
# Clinician profile management
# ---------------------------------------------------------------------------

class TestClinicianProfileAdmin:
    def test_clinicians_page_requires_admin(self, client, app, db):
        _create_user(app, "pat_adm1")
        _login(client, "pat_adm1")
        resp = client.get("/admin/clinicians")
        assert resp.status_code == 403

    def test_clinicians_page_accessible_to_admin(self, client, app, db):
        _create_user(app, "adm_clin1", role="administrator")
        _login(client, "adm_clin1")
        resp = client.get("/admin/clinicians")
        assert resp.status_code == 200
        assert b"Clinician" in resp.data

    def test_create_clinician_profile(self, client, app, db):
        """Admin can create a clinician profile for a clinician-role user."""
        _create_user(app, "adm_clin2", role="administrator")
        clin_user_id = _create_user(app, "doc_new1", role="clinician")
        _login(client, "adm_clin2")

        path = "/admin/clinicians"
        resp = client.post(
            path,
            data=signed_data("POST", path, {
                "user_id": str(clin_user_id),
                "specialty": "General",
                "default_slot_duration_minutes": "15",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            clinician = Clinician.query.filter_by(user_id=clin_user_id).first()
            assert clinician is not None
            assert clinician.specialty == "General"
            assert clinician.default_slot_duration_minutes == 15

    def test_create_clinician_profile_with_specialty(self, client, app, db):
        """Admin can set specialty and slot duration when creating a profile."""
        _create_user(app, "adm_clin3", role="administrator")
        clin_user_id = _create_user(app, "doc_new2", role="clinician")
        _login(client, "adm_clin3")

        path = "/admin/clinicians"
        resp = client.post(
            path,
            data=signed_data("POST", path, {
                "user_id": str(clin_user_id),
                "specialty": "Cardiology",
                "default_slot_duration_minutes": "30",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            clinician = Clinician.query.filter_by(user_id=clin_user_id).first()
            assert clinician.specialty == "Cardiology"
            assert clinician.default_slot_duration_minutes == 30

    def test_create_duplicate_clinician_profile_rejected(self, client, app, db):
        """Creating a duplicate clinician profile is rejected."""
        _create_user(app, "adm_clin4", role="administrator")
        clin_user_id = _create_user(app, "doc_dup1", role="clinician")
        _login(client, "adm_clin4")

        path = "/admin/clinicians"
        data = signed_data("POST", path, {
            "user_id": str(clin_user_id),
            "specialty": "",
            "default_slot_duration_minutes": "15",
        })
        client.post(path, data=data, follow_redirects=True)

        # Second attempt should fail
        data2 = signed_data("POST", path, {
            "user_id": str(clin_user_id),
            "specialty": "",
            "default_slot_duration_minutes": "15",
        })
        resp = client.post(path, data=data2, follow_redirects=True)
        assert resp.status_code == 200
        assert b"already exists" in resp.data

    def test_cannot_create_profile_for_non_clinician_role(self, client, app, db):
        """Creating a clinician profile for a patient-role user is rejected."""
        _create_user(app, "adm_clin5", role="administrator")
        pat_id = _create_user(app, "pat_not_clin", role="patient")
        _login(client, "adm_clin5")

        path = "/admin/clinicians"
        resp = client.post(
            path,
            data=signed_data("POST", path, {
                "user_id": str(pat_id),
                "specialty": "",
                "default_slot_duration_minutes": "15",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"clinician role" in resp.data

        with app.app_context():
            clinician = Clinician.query.filter_by(user_id=pat_id).first()
            assert clinician is None


# ---------------------------------------------------------------------------
# Schedule template management
# ---------------------------------------------------------------------------

def _create_clinician_profile(app, username="tmpl_doc"):
    """Helper to create a clinician user and profile, return (user_id, clinician_id)."""
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id, specialty="General")
        db.session.add(clinician)
        db.session.commit()
        return user.id, clinician.id


class TestScheduleTemplateAdmin:
    def test_templates_page_requires_admin(self, client, app, db):
        _, cid = _create_clinician_profile(app, "tmpl_doc0")
        _create_user(app, "pat_tmpl0")
        _login(client, "pat_tmpl0")
        resp = client.get(f"/admin/clinicians/{cid}/templates")
        assert resp.status_code == 403

    def test_templates_page_loads_for_admin(self, client, app, db):
        _, cid = _create_clinician_profile(app, "tmpl_doc1")
        _create_user(app, "adm_tmpl1", role="administrator")
        _login(client, "adm_tmpl1")
        resp = client.get(f"/admin/clinicians/{cid}/templates")
        assert resp.status_code == 200
        assert b"Schedule Templates" in resp.data

    def test_create_schedule_template(self, client, app, db):
        """Admin can create a schedule template for a clinician."""
        _, cid = _create_clinician_profile(app, "tmpl_doc2")
        _create_user(app, "adm_tmpl2", role="administrator")
        _login(client, "adm_tmpl2")

        path = f"/admin/clinicians/{cid}/templates"
        resp = client.post(
            path,
            data=signed_data("POST", path, {
                "day_of_week": "0",  # Monday
                "start_time": "09:00",
                "end_time": "12:00",
                "slot_duration": "15",
                "capacity": "1",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            tmpl = ScheduleTemplate.query.filter_by(clinician_id=cid).first()
            assert tmpl is not None
            assert tmpl.day_of_week == 0
            assert tmpl.start_time == time(9, 0)
            assert tmpl.end_time == time(12, 0)
            assert tmpl.slot_duration == 15
            assert tmpl.capacity == 1

    def test_invalid_time_range_rejected(self, client, app, db):
        """Template with start >= end is rejected."""
        _, cid = _create_clinician_profile(app, "tmpl_doc3")
        _create_user(app, "adm_tmpl3", role="administrator")
        _login(client, "adm_tmpl3")

        path = f"/admin/clinicians/{cid}/templates"
        resp = client.post(
            path,
            data=signed_data("POST", path, {
                "day_of_week": "1",
                "start_time": "12:00",
                "end_time": "09:00",
                "slot_duration": "15",
                "capacity": "1",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"before end time" in resp.data

        with app.app_context():
            count = ScheduleTemplate.query.filter_by(clinician_id=cid).count()
            assert count == 0

    def test_delete_schedule_template(self, client, app, db):
        """Admin can delete a schedule template."""
        _, cid = _create_clinician_profile(app, "tmpl_doc4")
        _create_user(app, "adm_tmpl4", role="administrator")

        with app.app_context():
            tmpl = ScheduleTemplate(
                clinician_id=cid,
                day_of_week=2,
                start_time=time(14, 0),
                end_time=time(17, 0),
                slot_duration=15,
            )
            db.session.add(tmpl)
            db.session.commit()
            tmpl_id = tmpl.id

        _login(client, "adm_tmpl4")
        path = f"/admin/clinicians/{cid}/templates/{tmpl_id}/delete"
        resp = client.post(
            path,
            data=signed_data("POST", path),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            assert db.session.get(ScheduleTemplate, tmpl_id) is None


# ---------------------------------------------------------------------------
# Clean-install scheduling bootstrap (F-01 core scenario)
# ---------------------------------------------------------------------------

class TestCleanInstallSchedulingBootstrap:
    def test_full_bootstrap_flow(self, client, app, db):
        """
        Prove that an admin can complete the full scheduling bootstrap
        (create clinician profile -> create template -> bulk generate slots)
        entirely through in-product admin UI routes, with no manual DB seeding.
        """
        # Step 1: Create admin and clinician user accounts
        _create_user(app, "bootstrap_admin", role="administrator")
        clin_uid = _create_user(app, "bootstrap_clinician", role="clinician")
        _login(client, "bootstrap_admin")

        # Step 2: Create clinician profile via admin UI
        clin_path = "/admin/clinicians"
        resp = client.post(
            clin_path,
            data=signed_data("POST", clin_path, {
                "user_id": str(clin_uid),
                "specialty": "General",
                "default_slot_duration_minutes": "15",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            clinician = Clinician.query.filter_by(user_id=clin_uid).first()
            assert clinician is not None
            cid = clinician.id

        # Step 3: Create schedule template via admin UI
        tmpl_path = f"/admin/clinicians/{cid}/templates"
        resp = client.post(
            tmpl_path,
            data=signed_data("POST", tmpl_path, {
                "day_of_week": "0",  # Monday
                "start_time": "09:00",
                "end_time": "10:00",
                "slot_duration": "15",
                "capacity": "1",
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            templates = ScheduleTemplate.query.filter_by(clinician_id=cid).all()
            assert len(templates) == 1

        # Step 4: Bulk generate slots via admin UI
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7 or 7
        next_monday = today + timedelta(days=days_until_monday)

        gen_path = "/schedule/admin/bulk-generate"
        resp = client.post(
            gen_path,
            data=signed_data("POST", gen_path, {
                "clinician_id": str(cid),
                "date_from": next_monday.isoformat(),
                "date_to": next_monday.isoformat(),
            }),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Generated" in resp.data

        with app.app_context():
            slots = Slot.query.filter_by(clinician_id=cid, date=next_monday).all()
            # 9:00-10:00 with 15-min slots = 4 slots
            assert len(slots) == 4
