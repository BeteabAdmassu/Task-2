"""E2E tests for authentication flows."""

import uuid
import pytest


def test_register_new_patient(page, base_url):
    """Register a new patient account and verify redirect."""
    uname = f"e2e_reg_{uuid.uuid4().hex[:6]}"
    page.goto(f"{base_url}/auth/register")
    page.fill('input[name="username"]', uname)
    page.fill('input[name="password"]', "TestPass1")
    page.fill('input[name="password_confirm"]', "TestPass1")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "MeridianCare" in page.title()


def test_login_valid_credentials(page, base_url):
    """Login with valid credentials and verify dashboard loads."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "Admin123")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "MeridianCare" in page.content()


def test_login_invalid_credentials(page, base_url):
    """Login with bad credentials and verify error message."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "nonexistent")
    page.fill('input[name="password"]', "WrongPass1")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "Invalid username or password" in page.content()


def test_logout(page, base_url):
    """Login then logout and verify redirect to login page."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "Admin123")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    # Click logout button
    page.click('button:has-text("Logout")')
    page.wait_for_load_state("networkidle")
    assert "logged out" in page.content().lower() or "Log In" in page.content()


def test_register_duplicate_username(page, base_url):
    """Registering with an existing username shows an error."""
    page.goto(f"{base_url}/auth/register")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "TestPass1")
    page.fill('input[name="password_confirm"]', "TestPass1")
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    assert "already taken" in page.content().lower()
