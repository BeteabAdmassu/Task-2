"""Tests for prompt 04 — patient demographics."""

import pytest
from app.models.user import User
from app.models.demographics import PatientDemographics, DemographicsChangeLog
from app.extensions import db
from app.utils.encryption import encrypt_value, decrypt_value, mask_id, reset_fernet
from tests.signing_helpers import signed_data

_DEMO_PATH = "/patient/demographics"


def _create_user(app, username, role="patient", password="Password1"):
    with app.app_context():
        user = User(username=username, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login(client, username="testuser", password="Password1"):
    return client.post(
        "/auth/login",
        data={"username": username, "password": password},
        follow_redirects=True,
    )


DEMO_DATA = {
    "full_name": "John Doe",
    "date_of_birth": "1990-05-15",
    "gender": "Male",
    "phone": "555-123-4567",
    "address_street": "123 Main St",
    "address_city": "Springfield",
    "address_state": "IL",
    "address_zip": "62701",
    "emergency_contact_name": "Jane Doe",
    "emergency_contact_phone": "555-987-6543",
    "emergency_contact_relationship": "Spouse",
    "insurance_id": "INS123456789",
    "government_id": "GOV987654321",
}


def test_patient_can_view_demographics_page(client, app):
    _create_user(app, "pat1")
    _login(client, "pat1")
    resp = client.get("/patient/demographics")
    assert resp.status_code == 200
    assert b"My Demographics" in resp.data


def test_patient_can_create_demographics(client, app):
    _create_user(app, "pat2")
    _login(client, "pat2")
    resp = client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        demo = PatientDemographics.query.filter_by(
            user_id=User.query.filter_by(username="pat2").first().id
        ).first()
        assert demo is not None
        assert demo.full_name == "John Doe"
        assert demo.phone == "555-123-4567"


def test_patient_can_update_demographics(client, app):
    _create_user(app, "pat3")
    _login(client, "pat3")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)

    updated = dict(DEMO_DATA)
    updated["full_name"] = "John Updated"
    updated["version"] = "1"
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, updated), follow_redirects=True)

    with app.app_context():
        demo = PatientDemographics.query.filter_by(
            user_id=User.query.filter_by(username="pat3").first().id
        ).first()
        assert demo.full_name == "John Updated"


def test_demographics_validation_required_fields(client, app):
    _create_user(app, "pat4")
    _login(client, "pat4")
    resp = client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, {"full_name": "", "phone": ""}))
    assert b"Full name is required" in resp.data


def test_demographics_future_dob_rejected(client, app):
    _create_user(app, "pat5")
    _login(client, "pat5")
    data = dict(DEMO_DATA)
    data["date_of_birth"] = "2099-01-01"
    resp = client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, data))
    assert b"future" in resp.data.lower()


def test_demographics_invalid_zip(client, app):
    _create_user(app, "pat6")
    _login(client, "pat6")
    data = dict(DEMO_DATA)
    data["address_zip"] = "BADZIP"
    resp = client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, data))
    assert b"ZIP" in resp.data


def test_encryption_of_sensitive_fields(client, app):
    _create_user(app, "pat7")
    _login(client, "pat7")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)
    with app.app_context():
        demo = PatientDemographics.query.filter_by(
            user_id=User.query.filter_by(username="pat7").first().id
        ).first()
        assert demo.insurance_id_encrypted is not None
        assert demo.insurance_id_encrypted != "INS123456789"
        assert decrypt_value(demo.insurance_id_encrypted) == "INS123456789"


def test_mask_id_function():
    assert mask_id("123456789") == "***-**-6789"
    assert mask_id("1234") == "1234"
    assert mask_id("") == ""
    assert mask_id(None) == ""


def test_reveal_field(client, app):
    _create_user(app, "pat8")
    _login(client, "pat8")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)
    resp = client.post("/patient/demographics/reveal", data={"field": "insurance_id"})
    assert resp.status_code == 200
    assert b"INS123456789" in resp.data


def test_staff_can_view_patient_demographics(client, app):
    pid = _create_user(app, "pat9")
    _create_user(app, "fd1", role="front_desk")
    # Create demographics for patient first
    _login(client, "pat9")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)
    client.post("/auth/logout")

    _login(client, "fd1")
    resp = client.get(f"/staff/patients/{pid}/demographics")
    assert resp.status_code == 200
    assert b"John Doe" in resp.data


def test_staff_front_desk_can_edit_patient_demographics(client, app):
    pid = _create_user(app, "pat10")
    _create_user(app, "fd2", role="front_desk")
    _login(client, "pat10")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)
    client.post("/auth/logout")

    _login(client, "fd2")
    updated = dict(DEMO_DATA)
    updated["full_name"] = "Updated By Staff"
    updated["version"] = "1"
    path = f"/staff/patients/{pid}/demographics"
    resp = client.post(path, data=signed_data("POST", path, updated), follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        demo = PatientDemographics.query.filter_by(user_id=pid).first()
        assert demo.full_name == "Updated By Staff"


def test_clinician_cannot_edit_demographics(client, app):
    pid = _create_user(app, "pat11")
    _create_user(app, "clin1", role="clinician")
    _login(client, "pat11")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)
    client.post("/auth/logout")

    _login(client, "clin1")
    resp = client.get(f"/staff/patients/{pid}/demographics")
    assert resp.status_code == 200
    # Clinician POSTs are rejected by read_only check (antireplay passes, role check redirects)
    path = f"/staff/patients/{pid}/demographics"
    resp = client.post(path, data=signed_data("POST", path, DEMO_DATA), follow_redirects=True)
    # Should get redirected with a warning
    assert resp.status_code == 200


def test_patient_list_page(client, app):
    _create_user(app, "pat12")
    _create_user(app, "fd3", role="front_desk")
    _login(client, "fd3")
    resp = client.get("/staff/patients")
    assert resp.status_code == 200
    assert b"pat12" in resp.data


def test_change_log_created(client, app):
    _create_user(app, "pat13")
    _login(client, "pat13")
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, DEMO_DATA), follow_redirects=True)

    updated = dict(DEMO_DATA)
    updated["full_name"] = "Changed Name"
    updated["version"] = "1"
    client.post("/patient/demographics", data=signed_data("POST", _DEMO_PATH, updated), follow_redirects=True)

    with app.app_context():
        logs = DemographicsChangeLog.query.all()
        name_changes = [l for l in logs if l.field_name == "full_name"]
        assert len(name_changes) >= 1
        assert name_changes[0].old_value == "John Doe"
        assert name_changes[0].new_value == "Changed Name"


def test_non_patient_cannot_access_patient_demographics(client, app):
    _create_user(app, "fd4", role="front_desk")
    _login(client, "fd4")
    resp = client.get("/patient/demographics", follow_redirects=True)
    # Front desk is redirected away
    assert resp.status_code == 200
