"""E2E tests for health assessments."""

import uuid
import pytest
from tests.e2e.conftest import register_user, BASE


def _fill_scale_questions(page, prefix, count, value="0"):
    """Click radio buttons for scale_0_3 questions."""
    for i in range(1, count + 1):
        page.click(f'input[name="{prefix}_q{i}"][value="{value}"]')


def _complete_full_assessment(page, base_url):
    """Walk through all wizard steps with all-zero responses (Low-risk result)."""
    page.goto(f"{base_url}/assessments/start")
    page.wait_for_load_state("networkidle")

    # Step 1: PHQ-9 (9 questions, scale_0_3)
    _fill_scale_questions(page, "phq9", 9, "0")
    page.click('button:has-text("Next")')
    page.wait_for_load_state("networkidle")

    # Step 2: GAD-7 (7 questions, scale_0_3)
    _fill_scale_questions(page, "gad7", 7, "0")
    page.click('button:has-text("Next")')
    page.wait_for_load_state("networkidle")

    # Step 3: Blood Pressure category (select)
    page.select_option('select[name="bp_category"]', "Normal")
    page.click('button:has-text("Next")')
    page.wait_for_load_state("networkidle")

    # Step 4: Fall Risk (yes/no radio buttons)
    page.click('input[name="fall_history"][value="no"]')
    page.click('input[name="mobility_aids"][value="no"]')
    page.click('input[name="dizziness"][value="no"]')
    page.click('input[name="balance_meds"][value="no"]')
    page.click('button:has-text("Next")')
    page.wait_for_load_state("networkidle")

    # Step 5: Medication Adherence — 4 scale_0_3 questions (med_adherence_q1..q4)
    _fill_scale_questions(page, "med_adherence", 4, "0")
    page.click('button:has-text("Review")')
    page.wait_for_load_state("networkidle")

    # Review page — submit final (HX-Redirect navigates to the result page)
    page.click('button:has-text("Submit Assessment")')
    page.wait_for_function(
        "() => window.location.href.includes('/assessments/result')",
        timeout=15000,
    )
    page.wait_for_load_state("networkidle")


def test_complete_assessment_wizard(page, base_url):
    """Walk through the full assessment wizard and verify a Low risk result."""
    uname = f"e2e_assess_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    _complete_full_assessment(page, base_url)

    content = page.content()
    # All-zero responses must produce a Low risk classification
    assert "Low" in content


def test_assessment_history_shows_result(page, base_url):
    """Completed assessment appears in history with a risk level."""
    uname = f"e2e_ahist_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    _complete_full_assessment(page, base_url)

    page.goto(f"{base_url}/assessments/history")
    page.wait_for_load_state("networkidle")
    content = page.content()
    assert "Assessment History" in content
    # At least one completed assessment must appear in the history
    assert "Low" in content or "Moderate" in content or "High" in content


def test_assessment_start_page(page, base_url):
    """Assessment start page is accessible for patients."""
    uname = f"e2e_astart_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/assessments/start")
    assert "Health Assessment" in page.content()
