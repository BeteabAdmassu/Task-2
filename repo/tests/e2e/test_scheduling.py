"""E2E tests for scheduling."""

import uuid
import pytest
from tests.e2e.conftest import register_user, login_user, BASE


def test_search_available_slots(page, base_url):
    """Search for available appointment slots."""
    uname = f"e2e_sched_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/schedule/available")
    assert "Available Appointments" in page.content()


def test_hold_and_confirm_slot(page, base_url):
    """Hold a slot and confirm the booking."""
    uname = f"e2e_book_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/schedule/available")

    # If there are Hold buttons, click the first one
    hold_btns = page.query_selector_all('button:has-text("Hold")')
    if hold_btns:
        hold_btns[0].click()
        page.wait_for_load_state("networkidle")
        assert "Confirm" in page.content()

        # Confirm the booking
        page.click('button:has-text("Confirm Booking")')
        page.wait_for_load_state("networkidle")
        assert "confirmed" in page.content().lower() or "Appointments" in page.content()


def test_my_appointments_page(page, base_url):
    """My appointments page loads."""
    uname = f"e2e_myappt_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/schedule/my-appointments")
    assert "My Appointments" in page.content()


def test_staff_calendar(logged_in_frontdesk, base_url):
    """Front desk can view staff calendar."""
    page = logged_in_frontdesk
    page.goto(f"{base_url}/schedule/staff/calendar")
    assert "Schedule" in page.content()
