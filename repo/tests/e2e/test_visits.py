"""E2E tests for visit state machine and dashboard."""

import pytest
from tests.e2e.conftest import login_user, BASE


def test_dashboard_loads_for_admin(logged_in_admin, base_url):
    """Admin can access the visits dashboard."""
    page = logged_in_admin
    page.goto(f"{base_url}/visits/dashboard")
    assert "Visit Dashboard" in page.content() or "Dashboard" in page.content()


def test_dashboard_loads_for_frontdesk(logged_in_frontdesk, base_url):
    """Front desk can access the visits dashboard."""
    page = logged_in_frontdesk
    page.goto(f"{base_url}/visits/dashboard")
    assert "Dashboard" in page.content()


def test_dashboard_loads_for_clinician(logged_in_clinician, base_url):
    """Clinician can access the visits dashboard."""
    page = logged_in_clinician
    page.goto(f"{base_url}/visits/dashboard")
    assert "Dashboard" in page.content()


def test_dashboard_poll_endpoint(logged_in_admin, base_url):
    """Dashboard poll endpoint returns content."""
    page = logged_in_admin
    resp = page.request.get(f"{base_url}/visits/dashboard/poll")
    assert resp.status == 200
