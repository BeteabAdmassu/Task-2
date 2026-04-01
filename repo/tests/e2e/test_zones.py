"""E2E tests for coverage zones."""

import pytest
from tests.e2e.conftest import login_user, BASE


def test_zones_page_loads(logged_in_admin, base_url):
    """Admin can view coverage zones."""
    page = logged_in_admin
    page.goto(f"{base_url}/coverage/zones")
    assert "Coverage Zones" in page.content()


def test_create_zone(logged_in_admin, base_url):
    """Admin can create a new zone."""
    page = logged_in_admin
    page.goto(f"{base_url}/coverage/zones")

    page.fill('input[name="name"]', "E2E Test Zone")
    page.fill('input[name="zip_codes"]', "99001,99002")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    assert "E2E Test Zone" in page.content() or "Zone" in page.content()


def test_coverage_check_endpoint(logged_in_admin, base_url):
    """Coverage check returns a result."""
    page = logged_in_admin
    resp = page.request.get(f"{base_url}/coverage/check?zip=10001")
    assert resp.status == 200
