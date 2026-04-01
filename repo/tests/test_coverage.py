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


# ---------------------------------------------------------------------------
# Fix 2: delivery window CRUD + validation
# ---------------------------------------------------------------------------

def _make_zone(app, name="WindowZone", zips=None):
    with app.app_context():
        zone = CoverageZone(name=name, zip_codes_json=zips or ["80001"])
        db.session.add(zone)
        db.session.commit()
        return zone.id


def test_create_delivery_window(client, app, db):
    """Admin can add a delivery window to a zone."""
    _create_user(app, "admin_win1", role="administrator")
    _login(client, "admin_win1")
    zid = _make_zone(app, "WinZone1")
    path = f"/coverage/zones/{zid}/windows"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "monday",
            "start_time": "09:00",
            "end_time": "17:00",
        }),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        from datetime import time as dt_time
        w = ZoneDeliveryWindow.query.filter_by(zone_id=zid, day_of_week="monday").first()
        assert w is not None
        assert w.start_time == dt_time(9, 0)
        assert w.end_time == dt_time(17, 0)


def test_create_duplicate_delivery_window_rejected(client, app, db):
    """Creating an identical window twice shows an overlap error and keeps only one."""
    from datetime import time as dt_time
    _create_user(app, "admin_win2", role="administrator")
    _login(client, "admin_win2")
    zid = _make_zone(app, "WinZone2")
    with app.app_context():
        w = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="tuesday",
            start_time=dt_time(10, 0), end_time=dt_time(14, 0),
        )
        db.session.add(w)
        db.session.commit()
    path = f"/coverage/zones/{zid}/windows"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "tuesday",
            "start_time": "10:00",
            "end_time": "14:00",
        }),
        follow_redirects=True,
    )
    # Exact duplicates are caught by the overlap check (identical range overlaps itself).
    assert b"overlap" in resp.data.lower()
    with app.app_context():
        count = ZoneDeliveryWindow.query.filter_by(zone_id=zid, day_of_week="tuesday").count()
        assert count == 1


def test_create_window_invalid_time_range(client, app, db):
    """start_time >= end_time is rejected."""
    _create_user(app, "admin_win3", role="administrator")
    _login(client, "admin_win3")
    zid = _make_zone(app, "WinZone3")
    path = f"/coverage/zones/{zid}/windows"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "friday",
            "start_time": "17:00",
            "end_time": "09:00",
        }),
        follow_redirects=True,
    )
    assert b"before end time" in resp.data or b"Start time" in resp.data
    with app.app_context():
        count = ZoneDeliveryWindow.query.filter_by(zone_id=zid).count()
        assert count == 0


def test_create_window_invalid_day(client, app, db):
    """An unrecognised day_of_week value is rejected."""
    _create_user(app, "admin_win4", role="administrator")
    _login(client, "admin_win4")
    zid = _make_zone(app, "WinZone4")
    path = f"/coverage/zones/{zid}/windows"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "funday",
            "start_time": "09:00",
            "end_time": "17:00",
        }),
        follow_redirects=True,
    )
    assert b"Invalid day" in resp.data
    with app.app_context():
        count = ZoneDeliveryWindow.query.filter_by(zone_id=zid).count()
        assert count == 0


def test_delete_delivery_window(client, app, db):
    """Admin can delete an existing delivery window."""
    from datetime import time as dt_time
    _create_user(app, "admin_win5", role="administrator")
    _login(client, "admin_win5")
    zid = _make_zone(app, "WinZone5")
    with app.app_context():
        w = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="all",
            start_time=dt_time(8, 0), end_time=dt_time(20, 0),
        )
        db.session.add(w)
        db.session.commit()
        wid = w.id
    path = f"/coverage/zones/{zid}/windows/{wid}/delete"
    resp = client.post(
        path,
        data=signed_data("POST", path),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        assert ZoneDeliveryWindow.query.get(wid) is None


def test_coverage_check_shows_configured_windows(client, app, db):
    """Delivery windows added via CRUD are returned by /coverage/check."""
    from datetime import time as dt_time
    with app.app_context():
        zone = CoverageZone(
            name="CRUDCheckZone", zip_codes_json=["90001"], is_active=True,
            delivery_fee=2.50, min_order_amount=10.0,
        )
        db.session.add(zone)
        db.session.commit()
        w = ZoneDeliveryWindow(
            zone_id=zone.id, day_of_week="wednesday",
            start_time=dt_time(10, 0), end_time=dt_time(18, 0),
        )
        db.session.add(w)
        db.session.commit()
    resp = client.get("/coverage/check?zip=90001")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["covered"] is True
    z = data["zones"][0]
    assert len(z["delivery_windows"]) == 1
    assert z["delivery_windows"][0]["day_of_week"] == "wednesday"
    assert z["delivery_windows"][0]["start_time"] == "10:00"
    assert z["delivery_windows"][0]["end_time"] == "18:00"


# ---------------------------------------------------------------------------
# Update delivery window (CRUD – U)
# ---------------------------------------------------------------------------

def test_update_delivery_window_success(client, app, db):
    """Admin can update an existing delivery window's day/times."""
    from datetime import time as dt_time
    _create_user(app, "admin_upd1", role="administrator")
    _login(client, "admin_upd1")
    zid = _make_zone(app, "UpdZone1")
    with app.app_context():
        w = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="monday",
            start_time=dt_time(9, 0), end_time=dt_time(17, 0),
        )
        db.session.add(w)
        db.session.commit()
        wid = w.id
    path = f"/coverage/zones/{zid}/windows/{wid}/update"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "tuesday",
            "start_time": "10:00",
            "end_time": "18:00",
        }),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    with app.app_context():
        updated = db.session.get(ZoneDeliveryWindow, wid)
        assert updated.day_of_week == "tuesday"
        assert updated.start_time == dt_time(10, 0)
        assert updated.end_time == dt_time(18, 0)


def test_update_delivery_window_invalid_time_rejected(client, app, db):
    """Update with start >= end is rejected and window is unchanged."""
    from datetime import time as dt_time
    _create_user(app, "admin_upd2", role="administrator")
    _login(client, "admin_upd2")
    zid = _make_zone(app, "UpdZone2")
    with app.app_context():
        w = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="friday",
            start_time=dt_time(9, 0), end_time=dt_time(17, 0),
        )
        db.session.add(w)
        db.session.commit()
        wid = w.id
    path = f"/coverage/zones/{zid}/windows/{wid}/update"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "friday",
            "start_time": "17:00",
            "end_time": "09:00",
        }),
        follow_redirects=True,
    )
    assert b"before end time" in resp.data or b"Start time" in resp.data
    with app.app_context():
        unchanged = db.session.get(ZoneDeliveryWindow, wid)
        assert unchanged.start_time == dt_time(9, 0)
        assert unchanged.end_time == dt_time(17, 0)


def test_update_delivery_window_duplicate_rejected(client, app, db):
    """Update that would create an exact duplicate of another window is rejected."""
    from datetime import time as dt_time
    _create_user(app, "admin_upd3", role="administrator")
    _login(client, "admin_upd3")
    zid = _make_zone(app, "UpdZone3")
    with app.app_context():
        # Existing window that we'd collide with.
        w_existing = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="wednesday",
            start_time=dt_time(10, 0), end_time=dt_time(14, 0),
        )
        # The window we'll try to update.
        w_target = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="thursday",
            start_time=dt_time(8, 0), end_time=dt_time(12, 0),
        )
        db.session.add_all([w_existing, w_target])
        db.session.commit()
        wid = w_target.id
    path = f"/coverage/zones/{zid}/windows/{wid}/update"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "wednesday",
            "start_time": "10:00",
            "end_time": "14:00",
        }),
        follow_redirects=True,
    )
    assert b"overlap" in resp.data.lower()
    with app.app_context():
        unchanged = db.session.get(ZoneDeliveryWindow, wid)
        assert unchanged.day_of_week == "thursday"  # not changed


def test_create_delivery_window_overlap_rejected(client, app, db):
    """Creating a window that overlaps an existing same-day window is rejected."""
    from datetime import time as dt_time
    _create_user(app, "admin_ovl1", role="administrator")
    _login(client, "admin_ovl1")
    zid = _make_zone(app, "OvlZone1")
    with app.app_context():
        w = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="monday",
            start_time=dt_time(9, 0), end_time=dt_time(17, 0),
        )
        db.session.add(w)
        db.session.commit()
    # 12:00-20:00 overlaps 09:00-17:00
    path = f"/coverage/zones/{zid}/windows"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "monday",
            "start_time": "12:00",
            "end_time": "20:00",
        }),
        follow_redirects=True,
    )
    assert b"overlap" in resp.data.lower()
    with app.app_context():
        count = ZoneDeliveryWindow.query.filter_by(zone_id=zid, day_of_week="monday").count()
        assert count == 1  # only the original


def test_update_delivery_window_overlap_rejected(client, app, db):
    """Updating a window to overlap another same-day window is rejected."""
    from datetime import time as dt_time
    _create_user(app, "admin_ovl2", role="administrator")
    _login(client, "admin_ovl2")
    zid = _make_zone(app, "OvlZone2")
    with app.app_context():
        # Two non-overlapping windows on tuesday.
        w1 = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="tuesday",
            start_time=dt_time(8, 0), end_time=dt_time(12, 0),
        )
        w2 = ZoneDeliveryWindow(
            zone_id=zid, day_of_week="tuesday",
            start_time=dt_time(13, 0), end_time=dt_time(17, 0),
        )
        db.session.add_all([w1, w2])
        db.session.commit()
        w2id = w2.id
    # Try to extend w2 to 11:00-17:00, which would overlap w1 (08:00-12:00).
    path = f"/coverage/zones/{zid}/windows/{w2id}/update"
    resp = client.post(
        path,
        data=signed_data("POST", path, {
            "day_of_week": "tuesday",
            "start_time": "11:00",
            "end_time": "17:00",
        }),
        follow_redirects=True,
    )
    assert b"overlap" in resp.data.lower()
    with app.app_context():
        unchanged = db.session.get(ZoneDeliveryWindow, w2id)
        assert unchanged.start_time == dt_time(13, 0)  # unchanged
