"""E2E tests for scheduling."""

import uuid
import pytest
from tests.e2e.conftest import register_user, login_user, BASE


def test_search_available_slots(page, base_url):
    """Search for available appointment slots — page loads with slot table."""
    uname = f"e2e_sched_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/schedule/available")
    content = page.content()
    assert "Available Appointments" in content
    # At least one of: a Hold button or "No available slots" message must be present
    assert (
        page.query_selector('button:has-text("Hold")') is not None
        or "No available" in content
        or "no slots" in content.lower()
    )


def test_hold_and_confirm_slot(page, base_url, ensure_schedule_slots):
    """Hold a slot and confirm — reservation must appear as Confirmed in My Appointments."""
    uname = f"e2e_book_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/schedule/available")

    # wait_for_selector raises TimeoutError if no slots exist — fail loudly,
    # not silently via an `if` guard that would hide the missing seed data.
    hold_btn = page.wait_for_selector('button:has-text("Hold")', timeout=10000)
    hold_btn.click()
    # HX-Redirect navigates to the confirm page
    page.wait_for_function(
        "() => window.location.href.includes('/schedule/confirm')",
        timeout=15000,
    )
    page.wait_for_load_state("networkidle")
    assert "Confirm Appointment" in page.content()

    # Confirm the booking (HX-Redirect navigates to my-appointments)
    page.click('button:has-text("Confirm Booking")')
    page.wait_for_function(
        "() => window.location.href.includes('/schedule/my-appointments')",
        timeout=15000,
    )
    page.wait_for_load_state("networkidle")

    # Verify the booking is listed as Confirmed in My Appointments
    page.goto(f"{base_url}/schedule/my-appointments")
    page.wait_for_load_state("networkidle")
    content = page.content()
    assert "My Appointments" in content
    assert "Confirmed" in content


def test_my_appointments_page(page, base_url):
    """My appointments page loads for a patient with no bookings."""
    uname = f"e2e_myappt_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/schedule/my-appointments")
    content = page.content()
    assert "My Appointments" in content
    # Either a table of appointments or the empty-state message
    assert "No appointments" in content or "Date" in content


def test_staff_calendar(logged_in_frontdesk, base_url):
    """Front desk can view staff calendar with schedule headings."""
    page = logged_in_frontdesk
    page.goto(f"{base_url}/schedule/staff/calendar")
    content = page.content()
    assert "Schedule" in content
    # Calendar must show at least one navigational element or date heading
    assert page.query_selector("table") is not None or "week" in content.lower() or "calendar" in content.lower()
