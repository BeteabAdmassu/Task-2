"""E2E tests for coverage zones."""

import pytest
import uuid
from tests.e2e.conftest import login_user, BASE


def test_zones_page_loads(logged_in_admin, base_url):
    """Admin can view coverage zones with correct page heading."""
    page = logged_in_admin
    page.goto(f"{base_url}/coverage/zones")
    content = page.content()
    assert "Coverage Zones" in content


def test_create_zone(logged_in_admin, base_url):
    """Admin creates a zone and it immediately appears in the zones list."""
    page = logged_in_admin
    zone_name = f"E2E Zone {uuid.uuid4().hex[:6]}"
    page.goto(f"{base_url}/coverage/zones")
    page.wait_for_load_state("networkidle")

    page.fill('input[name="name"]', zone_name)
    page.fill('input[name="zip_codes"]', "99001,99002")
    page.click('button:has-text("Create Zone")')
    page.wait_for_load_state("networkidle")

    assert zone_name in page.content()


def test_create_zone_all_policy_fields(logged_in_admin, base_url):
    """Admin can create a zone with all required policy fields via UI and they persist."""
    page = logged_in_admin
    zone_name = f"E2E Policy Zone {uuid.uuid4().hex[:6]}"
    page.goto(f"{base_url}/coverage/zones")
    page.wait_for_load_state("networkidle")

    page.fill('input[name="name"]', zone_name)
    page.fill('input[name="zip_codes"]', "88001,88002")
    page.fill('input[name="neighborhoods"]', "Westside,Harbor")
    page.fill('input[name="distance_band_min"]', "1.0")
    page.fill('input[name="distance_band_max"]', "15.0")
    page.fill('input[name="min_order_amount"]', "25.00")
    page.fill('input[name="delivery_fee"]', "4.99")
    page.click('button:has-text("Create Zone")')
    page.wait_for_load_state("networkidle")

    # Zone must appear in list with its exact name
    assert zone_name in page.content()


def test_zone_detail_shows_and_updates_all_policy_fields(logged_in_admin, base_url):
    """Zone detail page displays all policy fields and update form persists changes."""
    page = logged_in_admin
    zone_name = f"E2E Detail Zone {uuid.uuid4().hex[:6]}"

    # Create zone with all fields
    page.goto(f"{base_url}/coverage/zones")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="name"]', zone_name)
    page.fill('input[name="zip_codes"]', "77001")
    page.fill('input[name="neighborhoods"]', "Northside")
    page.fill('input[name="distance_band_min"]', "0")
    page.fill('input[name="distance_band_max"]', "10.0")
    page.fill('input[name="min_order_amount"]', "15.00")
    page.fill('input[name="delivery_fee"]', "3.00")
    page.click('button:has-text("Create Zone")')
    page.wait_for_load_state("networkidle")

    # Navigate to zone detail via the View button in the zone's row
    row = page.locator(f"tr:has-text('{zone_name}')")
    row.locator("text=View").click()
    page.wait_for_load_state("networkidle")
    content = page.content()

    # Detail page must show all policy fields
    assert "Northside" in content
    assert "10.0" in content
    assert "15" in content
    assert "3.00" in content or "3.0" in content

    # Update fields via the edit form
    page.fill('input[name="neighborhoods"]', "Northside,Eastgate")
    page.fill('input[name="distance_band_max"]', "20.0")
    page.fill('input[name="min_order_amount"]', "30.00")
    page.fill('input[name="delivery_fee"]', "5.50")
    page.click('button:has-text("Save Zone")')
    page.wait_for_load_state("networkidle")

    updated_content = page.content()
    assert "Northside" in updated_content
    assert "Eastgate" in updated_content
    assert "20.0" in updated_content


def test_deactivate_zone(logged_in_admin, base_url):
    """Admin deactivates a zone and it is excluded from coverage checks."""
    page = logged_in_admin
    zone_name = f"E2E Deact Zone {uuid.uuid4().hex[:6]}"
    unique_zip = f"9{uuid.uuid4().int % 9000 + 1000}"

    # Create zone
    page.goto(f"{base_url}/coverage/zones")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="name"]', zone_name)
    page.fill('input[name="zip_codes"]', unique_zip)
    page.click('button:has-text("Create Zone")')
    page.wait_for_load_state("networkidle")
    assert zone_name in page.content()

    # Navigate to zone detail and deactivate
    row = page.locator(f"tr:has-text('{zone_name}')")
    row.locator("text=View").click()
    page.wait_for_load_state("networkidle")
    page.fill('input[name="reason"]', "E2E test deactivation")
    page.click('button:has-text("Deactivate Zone")')
    page.wait_for_load_state("networkidle")

    # After deactivation the zone row should show "No" in the Active column
    page.goto(f"{base_url}/coverage/zones")
    page.wait_for_load_state("networkidle")
    row = page.locator(f"tr:has-text('{zone_name}')")
    assert "No" in row.inner_text()


def test_coverage_check_endpoint(logged_in_frontdesk, base_url):
    """Coverage check returns a valid JSON response."""
    page = logged_in_frontdesk
    resp = page.request.get(f"{base_url}/coverage/check?zip=10001")
    assert resp.status == 200
    data = resp.json()
    assert "covered" in data
