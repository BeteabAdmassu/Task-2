"""E2E test configuration and fixtures for Playwright."""

import pytest
import urllib.request
import ssl
import json
import uuid
from datetime import date, timedelta


BASE = "https://localhost:5000"


@pytest.fixture(scope="session")
def base_url():
    return BASE


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "ignore_https_errors": True}


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _api_get(path):
    resp = urllib.request.urlopen(f"{BASE}{path}", context=_ssl_ctx(), timeout=10)
    return resp.status, resp.read().decode()


def _api_post(path, data):
    encoded = "&".join(f"{k}={v}" for k, v in data.items()).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    resp = urllib.request.urlopen(req, context=_ssl_ctx(), timeout=10)
    return resp.status, resp.read().decode()


def register_user(page, username, password="TestPass1"):
    """Register a new user via the UI and return the logged-in page."""
    page.goto(f"{BASE}/auth/register")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.fill('input[name="password_confirm"]', password)
    with page.expect_response(lambda r: "/auth/register" in r.url and r.request.method == "POST"):
        page.click('button[type="submit"]')
    page.wait_for_timeout(500)
    page.wait_for_load_state("load")
    page.goto(f"{BASE}/")
    page.wait_for_load_state("networkidle")
    return page


def login_user(page, username, password):
    """Login a user via the UI.

    The login form uses hx-post; on success the server returns an HX-Redirect
    header which HTMX handles by setting window.location.href asynchronously.
    We wait for the XHR response (which sets the session cookie), then navigate
    to '/' ourselves so tests get a clean, fully-loaded page.
    """
    page.goto(f"{BASE}/auth/login")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    # expect_response waits for the XHR to /auth/login to complete (session
    # cookie is set server-side in that response).
    with page.expect_response(lambda r: "/auth/login" in r.url and r.request.method == "POST"):
        page.click('button[type="submit"]')
    # Let HTMX process the HX-Redirect (sets window.location.href async).
    page.wait_for_timeout(500)
    page.wait_for_load_state("load")
    # Force a clean navigation — the session cookie is already set.
    page.goto(f"{BASE}/")
    page.wait_for_load_state("networkidle")
    return page


@pytest.fixture
def registered_patient(page):
    """Register a fresh patient and return logged-in page."""
    uname = f"patient_{uuid.uuid4().hex[:8]}"
    return register_user(page, uname)


@pytest.fixture
def logged_in_admin(page):
    """Login as seeded admin."""
    return login_user(page, "admin", "Admin123")


@pytest.fixture
def logged_in_frontdesk(page):
    """Login as seeded front desk."""
    return login_user(page, "frontdesk", "FrontDesk1")


@pytest.fixture
def logged_in_clinician(page):
    """Login as seeded clinician."""
    return login_user(page, "drclinician", "Clinician1")


@pytest.fixture(scope="session", autouse=True)
def ensure_schedule_slots(browser):
    """Ensure available slots exist for the next 14 days.

    Uses the admin bulk-generate UI so E2E scheduling tests always find Hold
    buttons regardless of weekday, time of day, or how long since the seed
    script last ran.  Runs once per test session; any slots already present
    are skipped (the route de-dupes on clinician+date+start_time).
    """
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    try:
        page.goto(f"{BASE}/auth/login")
        page.fill('input[name="username"]', "admin")
        page.fill('input[name="password"]', "Admin123")
        with page.expect_response(lambda r: "/auth/login" in r.url and r.request.method == "POST"):
            page.click('button[type="submit"]')
        page.wait_for_timeout(500)
        page.wait_for_load_state("load")
        page.goto(f"{BASE}/schedule/admin/bulk-generate")
        page.wait_for_load_state("networkidle")

        # Select the first real clinician (index 1 skips the placeholder option)
        page.select_option('select[name="clinician_id"]', index=1)
        today = date.today()
        page.fill('input[name="date_from"]', today.isoformat())
        page.fill('input[name="date_to"]', (today + timedelta(days=14)).isoformat())
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
    except Exception:
        # Never block the test session: slots may already exist or the server
        # may still be starting.  The scheduling tests will fail with a clear
        # TimeoutError if no Hold buttons appear.
        pass
    finally:
        context.close()
