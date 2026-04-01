"""Tests for prompt 08 — Service Coverage Zones."""

import pytest
from app.models.user import User
from app.models.scheduling import Clinician
from app.models.coverage import CoverageZone, ZoneAssignment, ZoneDeliveryWindow
from app.extensions import db
from tests.signing_helpers import signed_data

_ZONES_PATH = "/coverage/zones"


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


def _create_clinician(app, username="doc_cov"):
    with app.app_context():
        user = User(username=username, role="clinician")
        user.set_password("Password1")
        db.session.add(user)
        db.session.commit()
        clinician = Clinician(user_id=user.id, specialty="General")
        db.session.add(clinician)
        db.session.commit()
        return user.id, clinician.id


def test_zones_page_requires_admin(client, app, db):
    _create_user(app, "pat_cov1")
    _login(client, "pat_cov1")
    resp = client.get("/coverage/zones")
    assert resp.status_code == 403


def test_zones_page_accessible_by_admin(client, app, db):
    _create_user(app, "admin_cov1", role="administrator")
    _login(client, "admin_cov1")
    resp = client.get("/coverage/zones")
    assert resp.status_code == 200
    assert b"Coverage Zones" in resp.data


def test_create_zone(client, app, db):
    _create_user(app, "admin_cov2", role="administrator")
    _login(client, "admin_cov2")
    resp = client.post(
        _ZONES_PATH,
        data=signed_data("POST", _ZONES_PATH, {"name": "Downtown", "description": "Downtown area", "zip_codes": "10001, 10002"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        zone = CoverageZone.query.filter_by(name="Downtown").first()
        assert zone is not None
        assert "10001" in zone.zip_codes_json


def test_create_duplicate_zone(client, app, db):
    _create_user(app, "admin_cov3", role="administrator")
    _login(client, "admin_cov3")
    client.post(_ZONES_PATH, data=signed_data("POST", _ZONES_PATH, {"name": "Uptown", "zip_codes": "20001"}), follow_redirects=True)
    resp = client.post(_ZONES_PATH, data=signed_data("POST", _ZONES_PATH, {"name": "Uptown", "zip_codes": "20002"}), follow_redirects=True)
    assert b"already exists" in resp.data


def test_zone_detail(client, app, db):
    _create_user(app, "admin_cov4", role="administrator")
    _login(client, "admin_cov4")
    with app.app_context():
        zone = CoverageZone(name="TestZone", zip_codes_json=["30001"])
        db.session.add(zone)
        db.session.commit()
        zid = zone.id
    resp = client.get(f"/coverage/zones/{zid}")
    assert resp.status_code == 200


def test_assign_clinician_to_zone(client, app, db):
    _create_user(app, "admin_cov5", role="administrator")
    uid, cid = _create_clinician(app, "doc_cov5")
    _login(client, "admin_cov5")
    with app.app_context():
        zone = CoverageZone(name="AssignZone", zip_codes_json=["40001"])
        db.session.add(zone)
        db.session.commit()
        zid = zone.id
    resp = client.post(
        f"/coverage/zones/{zid}/assign",
        data=signed_data("POST", f"/coverage/zones/{zid}/assign", {"clinician_id": cid, "assignment_type": "primary"}),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        a = ZoneAssignment.query.filter_by(zone_id=zid, clinician_id=cid).first()
        assert a is not None
        assert a.assignment_type == "primary"


def test_check_coverage_covered(client, app, db):
    with app.app_context():
        zone = CoverageZone(name="CheckZone", zip_codes_json=["50001"], is_active=True)
        db.session.add(zone)
        db.session.commit()
    resp = client.get("/coverage/check?zip=50001")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["covered"] is True


def test_check_coverage_not_covered(client, app, db):
    resp = client.get("/coverage/check?zip=99999")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["covered"] is False


def test_check_coverage_no_zip(client, app, db):
    resp = client.get("/coverage/check?zip=")
    assert resp.status_code == 400


def test_create_zone_with_new_fields(client, app, db):
    _create_user(app, "admin_cov_nf", role="administrator")
    _login(client, "admin_cov_nf")
    resp = client.post(
        "/coverage/zones",
        data=signed_data("POST", "/coverage/zones", {
            "name": "NewFieldZone",
            "description": "Zone with new fields",
            "zip_codes": "60001, 60002",
            "distance_band_min": "0",
            "distance_band_max": "10.5",
            "min_order_amount": "25.0",
            "delivery_fee": "5.99",
        }),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        zone = CoverageZone.query.filter_by(name="NewFieldZone").first()
        assert zone is not None
        assert zone.distance_band_min == 0
        assert zone.distance_band_max == 10.5
        assert zone.min_order_amount == 25.0
        assert zone.delivery_fee == 5.99


def test_check_coverage_returns_fee_and_minimum(client, app, db):
    from datetime import time as dt_time
    with app.app_context():
        zone = CoverageZone(
            name="FeeZone",
            zip_codes_json=["70001"],
            is_active=True,
            delivery_fee=4.99,
            min_order_amount=15.0,
        )
        db.session.add(zone)
        db.session.commit()
        window = ZoneDeliveryWindow(
            zone_id=zone.id,
            day_of_week="all",
            start_time=dt_time(9, 0),
            end_time=dt_time(17, 0),
        )
        db.session.add(window)
        db.session.commit()
    resp = client.get("/coverage/check?zip=70001")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["covered"] is True
    assert len(data["zones"]) == 1
    z = data["zones"][0]
    assert z["delivery_fee"] == 4.99
    assert z["min_order_amount"] == 15.0
    assert len(z["delivery_windows"]) == 1
    assert z["delivery_windows"][0]["day_of_week"] == "all"
    assert z["delivery_windows"][0]["start_time"] == "09:00"
    assert z["delivery_windows"][0]["end_time"] == "17:00"
