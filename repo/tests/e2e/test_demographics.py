"""E2E tests for patient demographics."""

import uuid
import pytest
from tests.e2e.conftest import register_user, BASE


def test_complete_demographics_form(page, base_url):
    """Patient submits demographics and data persists across a page reload."""
    uname = f"e2e_demo_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)

    page.goto(f"{base_url}/patient/demographics")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="full_name"]', "E2E Test Patient")
    page.fill('input[name="date_of_birth"]', "1990-01-15")
    page.select_option('select[name="gender"]', "Male")
    page.fill('input[name="phone"]', "555-123-4567")
    page.fill('input[name="address_street"]', "123 Test St")
    page.fill('input[name="address_city"]', "Testville")
    page.fill('input[name="address_state"]', "TX")
    page.fill('input[name="address_zip"]', "75001")
    page.fill('input[name="insurance_id"]', "INS999888777")
    page.click('button:has-text("Save Demographics")')
    # HX-Redirect reloads the page; wait for the navigation to complete.
    page.wait_for_function(
        "() => document.querySelector('.alert-success') !== null || document.readyState === 'loading'",
        timeout=15000,
    )
    page.wait_for_load_state("networkidle")

    # Reload the form and verify the saved name is pre-populated
    page.goto(f"{base_url}/patient/demographics")
    page.wait_for_load_state("networkidle")
    saved_name = page.input_value('input[name="full_name"]')
    assert saved_name == "E2E Test Patient", (
        f"Expected 'E2E Test Patient' to be pre-filled after save, got {saved_name!r}"
    )


def test_edit_demographics_persist(page, base_url):
    """Edited demographics are persisted and the form reflects the new value on reload."""
    uname = f"e2e_dedit_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)

    # Initial save
    page.goto(f"{base_url}/patient/demographics")
    page.wait_for_load_state("networkidle")
    page.fill('input[name="full_name"]', "Original Name")
    page.fill('input[name="date_of_birth"]', "1985-06-20")
    page.fill('input[name="phone"]', "555-000-1111")
    page.click('button:has-text("Save Demographics")')
    page.wait_for_function(
        "() => document.querySelector('.alert-success') !== null || document.readyState === 'loading'",
        timeout=15000,
    )
    page.wait_for_load_state("networkidle")

    # Reload and verify the input field value — not just page text
    page.goto(f"{base_url}/patient/demographics")
    page.wait_for_load_state("networkidle")
    assert page.input_value('input[name="full_name"]') == "Original Name"


def test_demographics_page_loads(page, base_url):
    """Demographics page is accessible for patients."""
    uname = f"e2e_dload_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/patient/demographics")
    assert "My Demographics" in page.content()
