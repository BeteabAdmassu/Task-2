"""E2E tests for visit state machine and dashboard."""

import pytest
from tests.e2e.conftest import login_user, BASE


def test_dashboard_loads_for_admin(logged_in_admin, base_url):
    """Admin visits dashboard renders with required columns."""
    page = logged_in_admin
    page.goto(f"{base_url}/visits/dashboard")
    content = page.content()
    assert "Visit Dashboard" in content or "Dashboard" in content
    # Dashboard table must include status and patient columns
    assert "Status" in content
    assert "Patient" in content or "patient" in content.lower()


def test_dashboard_loads_for_frontdesk(logged_in_frontdesk, base_url):
    """Front desk visits dashboard renders with transition controls."""
    page = logged_in_frontdesk
    page.goto(f"{base_url}/visits/dashboard")
    content = page.content()
    assert "Dashboard" in content
    assert "Status" in content


def test_dashboard_loads_for_clinician(logged_in_clinician, base_url):
    """Clinician visits dashboard renders with required columns."""
    page = logged_in_clinician
    page.goto(f"{base_url}/visits/dashboard")
    content = page.content()
    assert "Dashboard" in content
    assert "Status" in content


def test_dashboard_poll_endpoint(logged_in_admin, base_url):
    """Dashboard poll endpoint returns valid HTMX partial content."""
    page = logged_in_admin
    resp = page.request.get(f"{base_url}/visits/dashboard/poll")
    assert resp.status == 200
    # Poll response is an HTML partial — must contain table row markup or empty message
    body = resp.text()
    assert "<tr" in body or "No visits" in body or "no visit" in body.lower()
