"""E2E test configuration and fixtures for Playwright."""

import pytest
import urllib.request
import ssl
import json
import uuid


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
    page.click('button[type="submit"]')
    # Wait for HTMX to process the HX-Redirect response and navigate away from the register page.
    page.wait_for_url(lambda url: "/auth/register" not in url, timeout=10000)
    page.wait_for_load_state("networkidle")
    return page


def login_user(page, username, password):
    """Login a user via the UI."""
    page.goto(f"{BASE}/auth/login")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    # Wait for HTMX to process the HX-Redirect response and navigate away from the login page.
    page.wait_for_url(lambda url: "/auth/login" not in url, timeout=10000)
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
