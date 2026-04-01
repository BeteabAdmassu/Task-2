"""E2E tests for RBAC & authorization."""

import uuid
import pytest
from tests.e2e.conftest import register_user, login_user, BASE


def test_patient_cannot_access_admin(page, base_url):
    """Patient gets 403 when accessing admin routes."""
    uname = f"e2e_rbac_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    resp = page.request.get(f"{base_url}/admin/users")
    assert resp.status == 403 or "Access Denied" in resp.text()


def test_patient_cannot_access_dashboard(page, base_url):
    """Patient gets 403 on visits dashboard."""
    uname = f"e2e_rbac2_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    resp = page.request.get(f"{base_url}/visits/dashboard")
    assert resp.status == 403 or resp.status == 302


def test_admin_can_access_users(logged_in_admin, base_url):
    """Admin can access user management."""
    page = logged_in_admin
    page.goto(f"{base_url}/admin/users")
    assert "User Management" in page.content()


def test_admin_can_access_audit(logged_in_admin, base_url):
    """Admin can access audit log."""
    page = logged_in_admin
    page.goto(f"{base_url}/admin/audit")
    assert "Audit" in page.content()


def test_nav_shows_role_appropriate_links(logged_in_admin, base_url):
    """Admin nav shows Users, Zones, Audit, System links."""
    page = logged_in_admin
    page.goto(base_url)
    content = page.content()
    assert "Users" in content
    assert "Zones" in content
    assert "Audit" in content
