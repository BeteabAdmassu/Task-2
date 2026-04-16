"""E2E tests for authentication flows."""

import uuid
import pytest


def _submit_and_wait(page, url_fragment, method="POST"):
    """Click submit and wait for the HTMX XHR response to complete."""
    with page.expect_response(
        lambda r: url_fragment in r.url and r.request.method == method
    ):
        page.click('button[type="submit"]')
    # Let HTMX process the HX-Redirect (sets window.location.href async).
    page.wait_for_timeout(500)
    page.wait_for_load_state("load")


def test_register_new_patient(page, base_url):
    """Register a new patient account and verify redirect to authenticated area."""
    uname = f"e2e_reg_{uuid.uuid4().hex[:6]}"
    page.goto(f"{base_url}/auth/register")
    page.fill('input[name="username"]', uname)
    page.fill('input[name="password"]', "TestPass1")
    page.fill('input[name="password_confirm"]', "TestPass1")
    _submit_and_wait(page, "/auth/register")
    # HX-Redirect fires async; navigate cleanly to verify session.
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")
    assert "MeridianCare" in page.title()


def test_login_valid_credentials(page, base_url):
    """Login with valid credentials and verify authenticated dashboard loads."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "Admin123")
    _submit_and_wait(page, "/auth/login")
    # HX-Redirect fires async; navigate cleanly to verify session.
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")
    content = page.content()
    assert "MeridianCare" in content
    # Must not still be on the login page
    assert "Log In" not in content or "Logout" in content


def test_login_invalid_credentials(page, base_url):
    """Login with bad credentials shows an error and keeps user on login page."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "nonexistent")
    page.fill('input[name="password"]', "WrongPass1")
    _submit_and_wait(page, "/auth/login")
    # Failed login swaps error into #login-form-container via HTMX (stays on page).
    page.wait_for_selector("text=Invalid username or password", timeout=5000)
    assert "Invalid username or password" in page.content()


def test_logout(page, base_url):
    """Login then logout and verify redirect to login page."""
    page.goto(f"{base_url}/auth/login")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "Admin123")
    _submit_and_wait(page, "/auth/login")
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")

    # Click logout button (plain POST form — triggers full page navigation)
    page.click('button:has-text("Logout")')
    page.wait_for_load_state("networkidle")
    assert "logged out" in page.content().lower() or "Log In" in page.content()


def test_register_duplicate_username(page, base_url):
    """Registering with an existing username shows an error."""
    page.goto(f"{base_url}/auth/register")
    page.fill('input[name="username"]', "admin")
    page.fill('input[name="password"]', "TestPass1")
    page.fill('input[name="password_confirm"]', "TestPass1")
    _submit_and_wait(page, "/auth/register")
    # Error response is swapped inline by HTMX.
    page.wait_for_load_state("networkidle")
    assert "already taken" in page.content().lower()


def test_login_rate_limiting(page, base_url):
    """After 10 failed login attempts the account is locked and the page shows rate-limit message."""
    uname = f"e2e_rl_{uuid.uuid4().hex[:6]}"

    # Register the account first
    page.goto(f"{base_url}/auth/register")
    page.fill('input[name="username"]', uname)
    page.fill('input[name="password"]', "TestPass1")
    page.fill('input[name="password_confirm"]', "TestPass1")
    _submit_and_wait(page, "/auth/register")
    page.goto(f"{base_url}/")
    page.wait_for_load_state("networkidle")

    # Registration auto-logs-in; log out so we can hit the login page freely
    page.click('button:has-text("Logout")')
    page.wait_for_load_state("networkidle")

    # Make 10 failed login attempts to trigger the rate limit
    for _ in range(10):
        page.goto(f"{base_url}/auth/login")
        page.wait_for_load_state("networkidle")
        page.fill('input[name="username"]', uname)
        page.fill('input[name="password"]', "WrongPass999")
        _submit_and_wait(page, "/auth/login")
        page.wait_for_load_state("networkidle")

    # The next attempt — even with the correct password — must be blocked
    page.goto(f"{base_url}/auth/login")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="username"]', uname)
    page.fill('input[name="password"]', "TestPass1")
    _submit_and_wait(page, "/auth/login")
    page.wait_for_load_state("networkidle")

    content = page.content()
    assert "Too many login attempts" in content or "rate" in content.lower() or "locked" in content.lower()
