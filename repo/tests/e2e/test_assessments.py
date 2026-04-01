"""E2E tests for health assessments."""

import uuid
import pytest
from tests.e2e.conftest import register_user, BASE


def _fill_scale_questions(page, prefix, count, value="0"):
    """Fill radio buttons for scale questions."""
    for i in range(1, count + 1):
        page.click(f'input[name="{prefix}_q{i}"][value="{value}"]')


def test_complete_assessment_wizard(page, base_url):
    """Walk through the full assessment wizard."""
    uname = f"e2e_assess_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)

    page.goto(f"{base_url}/assessments/start")
    assert "Health Assessment" in page.content()

    # Step 1: PHQ-9 — fill all 9 questions with 0
    _fill_scale_questions(page, "phq9", 9, "0")
    page.click('button[type="submit"]')
    page.wait_for_timeout(500)

    # Step 2: GAD-7
    _fill_scale_questions(page, "gad7", 7, "0")
    page.click('button[type="submit"]')
    page.wait_for_timeout(500)

    # Step 3: BP
    page.select_option('select[name="bp_category"]', "Normal")
    page.click('button[type="submit"]')
    page.wait_for_timeout(500)

    # Step 4: Fall Risk
    page.click('input[name="fall_history"][value="no"]')
    page.click('input[name="mobility_aids"][value="no"]')
    page.click('input[name="dizziness"][value="no"]')
    page.click('input[name="balance_meds"][value="no"]')
    page.click('button[type="submit"]')
    page.wait_for_timeout(500)

    # Step 5: Med Adherence
    page.select_option('select[name="med_adherence"]', "never_miss")
    page.click('button[type="submit"]')
    page.wait_for_timeout(500)

    # Review page — submit
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")

    assert "Low" in page.content() or "Result" in page.content()


def test_assessment_history_page(page, base_url):
    """Assessment history page loads."""
    uname = f"e2e_ahist_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/assessments/history")
    assert "Assessment History" in page.content()


def test_assessment_start_page(page, base_url):
    """Assessment start page loads."""
    uname = f"e2e_astart_{uuid.uuid4().hex[:6]}"
    register_user(page, uname)
    page.goto(f"{base_url}/assessments/start")
    assert "Health Assessment" in page.content()
