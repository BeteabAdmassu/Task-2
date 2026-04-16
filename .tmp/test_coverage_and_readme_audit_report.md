# Test Coverage Audit

## Backend Endpoint Inventory

Project type from static inspection: **fullstack** Flask backend with server-rendered HTMX frontend.

Blueprint prefixes:
- `/auth` -> `repo/app/routes/auth.py`
- `/admin` -> `repo/app/routes/admin.py`, `repo/app/routes/observability.py`, `repo/app/routes/audit.py`
- `/assessments` -> `repo/app/routes/assessments.py`
- `/schedule` -> `repo/app/routes/schedule.py`
- `/coverage` -> `repo/app/routes/coverage.py`
- `/visits` -> `repo/app/routes/visits.py`
- `/patient` -> `repo/app/routes/patient.py`
- `/staff` -> `repo/app/routes/staff.py`
- `/notes` -> `repo/app/routes/notes.py`
- `/reminders` -> `repo/app/routes/reminders.py`
- no prefix -> `repo/app/routes/main.py`, `repo/app/routes/health.py`

Total extracted endpoints (strict `METHOD + PATH`): **86**.

## API Test Mapping Table

Test type legend:
- `true no-mock HTTP`: real transport/network request (Playwright/urllib), no execution-path mocks
- `HTTP with mocking`: route is requested but core execution path has patched/mocked dependency
- `unit-only / indirect`: in-process Flask `test_client` route test

| Endpoint | Covered | Test Type | Test Files | Evidence |
|---|---|---|---|---|
| GET `/` | yes | true no-mock HTTP | `tests/test_foundation.py`, `tests/e2e/test_zz_auth.py` | `test_index_page`, `test_login_valid_credentials` |
| GET `/health` | yes | true no-mock HTTP | `tests/test_foundation.py`, `tests/e2e/test_e2e_foundation.py` | `test_health_endpoint`, `test_health_endpoint` |
| GET `/health/detailed` | yes | unit-only / indirect | `tests/test_observability.py` | `test_health_detailed_returns_json` |
| GET `/admin/audit` | yes | unit-only / indirect | `tests/test_audit.py` | `test_audit_log_page_accessible_by_admin` |
| GET `/auth/register` | yes | true no-mock HTTP | `tests/test_auth.py`, `tests/e2e/test_zz_auth.py` | `test_register_page_loads`, `test_register_new_patient` |
| POST `/auth/register` | yes | true no-mock HTTP | `tests/test_auth.py`, `tests/e2e/test_zz_auth.py` | `test_register_success`, `test_register_new_patient` |
| GET `/auth/login` | yes | true no-mock HTTP | `tests/test_auth.py`, `tests/e2e/test_zz_auth.py` | `test_login_page_loads`, `test_login_valid_credentials` |
| POST `/auth/login` | yes | true no-mock HTTP | `tests/test_auth.py`, `tests/e2e/test_zz_auth.py` | `test_login_success`, `test_login_valid_credentials` |
| POST `/auth/logout` | yes | true no-mock HTTP | `tests/test_auth.py`, `tests/e2e/test_zz_auth.py` | `test_logout`, `test_logout` |
| GET `/auth/change-password` | yes | unit-only / indirect | `tests/test_security.py` | `test_change_password_page` |
| POST `/auth/change-password` | yes | unit-only / indirect | `tests/test_security.py` | `test_change_password_success` |
| GET `/auth/check-username` | yes | unit-only / indirect | `tests/test_auth.py` | `test_check_username_available` |
| GET `/admin/users` | yes | unit-only / indirect | `tests/test_rbac.py` | `test_admin_users_page_accessible_by_admin` |
| PUT `/admin/users/:id/role` | yes | unit-only / indirect | `tests/test_audit_coverage.py` | `test_put_change_role_success` |
| POST `/admin/users/:id/role` | yes | unit-only / indirect | `tests/test_rbac.py`, `tests/test_coverage_gaps.py` | `test_change_user_role`, `test_change_role_success_htmx_returns_row` |
| PUT `/admin/users/:id/status` | yes | unit-only / indirect | `tests/test_audit_coverage.py` | `test_put_deactivate_user_success` |
| POST `/admin/users/:id/status` | yes | unit-only / indirect | `tests/test_rbac.py`, `tests/test_coverage_gaps.py` | `test_deactivate_user`, `test_change_status_missing_reason_htmx` |
| GET `/admin/clinicians` | yes | unit-only / indirect | `tests/test_admin_schedule.py` | `test_clinicians_page_accessible_to_admin` |
| POST `/admin/clinicians` | yes | unit-only / indirect | `tests/test_admin_schedule.py` | `test_create_clinician_profile` |
| GET `/admin/clinicians/:id/templates` | yes | unit-only / indirect | `tests/test_admin_schedule.py` | `test_templates_page_loads_for_admin` |
| POST `/admin/clinicians/:id/templates` | yes | unit-only / indirect | `tests/test_admin_schedule.py` | `test_create_schedule_template` |
| POST `/admin/clinicians/:id/templates/:id/delete` | yes | unit-only / indirect | `tests/test_admin_schedule.py` | `test_delete_schedule_template` |
| GET `/admin/observability` | yes | unit-only / indirect | `tests/test_observability.py` | `test_observability_accessible_by_admin` |
| GET `/admin/operations` | yes | unit-only / indirect | `tests/test_audit_coverage.py` | `test_admin_operations_redirect` |
| GET `/admin/operations/alerts` | yes | unit-only / indirect | `tests/test_new_features.py` | `test_operations_alerts_accessible_by_admin` |
| GET `/admin/operations/slow-queries` | yes | unit-only / indirect | `tests/test_new_features.py` | `test_operations_slow_queries_accessible_by_admin` |
| GET `/admin/operations/sessions` | yes | unit-only / indirect | `tests/test_observability.py` | `test_operations_sessions_accessible_by_admin` |
| POST `/admin/operations/alerts/:id/acknowledge` | yes | unit-only / indirect | `tests/test_audit_security.py` | `test_acknowledge_alert_succeeds_with_antireplay` |
| GET `/assessments/start` | yes | true no-mock HTTP | `tests/test_assessments.py`, `tests/e2e/test_assessments.py` | `test_assessment_start_page`, `test_assessment_start_page` |
| GET `/assessments/start/:visit_id` | yes | unit-only / indirect | `tests/test_audit_coverage.py` | `test_start_with_valid_visit` |
| POST `/assessments/step/:step` | yes | unit-only / indirect | `tests/test_assessments.py` | `test_step_persists_in_draft` |
| POST `/assessments/submit` | yes | unit-only / indirect | `tests/test_assessments.py` | `test_full_assessment_submission` |
| GET `/assessments/result/:id` | yes | unit-only / indirect | `tests/test_assessments.py` | `test_result_page` |
| GET `/assessments/history` | yes | true no-mock HTTP | `tests/test_assessments.py`, `tests/e2e/test_assessments.py` | `test_history_page`, `test_assessment_history_shows_result` |
| POST `/assessments/save-draft` | yes | unit-only / indirect | `tests/test_assessments.py` | `test_save_draft_endpoint` |
| GET `/assessments/behalf/:patient_id/start` | yes | unit-only / indirect | `tests/test_on_behalf.py` | `test_front_desk_can_submit_behalf_assessment` |
| POST `/assessments/behalf/:patient_id/step/:step` | yes | unit-only / indirect | `tests/test_on_behalf.py` | `test_behalf_assessment_idempotency` |
| POST `/assessments/behalf/:patient_id/submit` | yes | unit-only / indirect | `tests/test_on_behalf.py` | `test_admin_can_submit_behalf_assessment` |
| GET `/assessments/patient/:patient_id` | yes | unit-only / indirect | `tests/test_assessments.py` | `test_staff_can_view_patient_assessments` |
| GET `/schedule/available` | yes | true no-mock HTTP | `tests/test_scheduling.py`, `tests/e2e/test_scheduling.py` | `test_available_slots_page`, `test_search_available_slots` |
| POST `/schedule/hold/:slot_id` | yes | unit-only / indirect | `tests/test_scheduling.py`, `tests/test_acceptance_audit.py` | `test_hold_slot`, `test_reservation_request_token_hash_at_rest` |
| GET `/schedule/confirm/:reservation_id` | yes | unit-only / indirect | `tests/test_user_isolation.py` | `test_user_b_cannot_access_user_a_confirm_page` |
| POST `/schedule/confirm/:reservation_id` | yes | unit-only / indirect | `tests/test_scheduling.py` | `test_confirm_reservation` |
| POST `/schedule/cancel/:reservation_id` | yes | unit-only / indirect | `tests/test_scheduling.py` | `test_cancel_reservation` |
| POST `/schedule/behalf/:patient_id/hold/:slot_id` | yes | unit-only / indirect | `tests/test_on_behalf.py` | `test_front_desk_can_hold_slot_for_patient` |
| GET `/schedule/behalf/:patient_id/confirm/:reservation_id` | yes | unit-only / indirect | `tests/test_on_behalf.py` | `test_behalf_confirm_page_reservation_not_found` |
| POST `/schedule/behalf/:patient_id/confirm/:reservation_id` | yes | unit-only / indirect | `tests/test_on_behalf.py` | `test_behalf_confirm_completes_booking` |
| GET `/schedule/my-appointments` | yes | true no-mock HTTP | `tests/test_scheduling.py`, `tests/e2e/test_scheduling.py` | `test_my_appointments`, `test_my_appointments_page` |
| GET `/schedule/staff/calendar` | yes | true no-mock HTTP | `tests/test_scheduling.py`, `tests/e2e/test_scheduling.py` | `test_staff_calendar`, `test_staff_calendar` |
| GET `/schedule/admin/holidays` | yes | unit-only / indirect | `tests/test_audit_coverage.py` | `test_holidays_page_loads` |
| POST `/schedule/admin/holidays` | yes | unit-only / indirect | `tests/test_scheduling.py`, `tests/test_audit_security.py` | `test_mark_holiday`, `test_add_holiday_succeeds_with_antireplay` |
| POST `/schedule/admin/holidays/:holiday_id/delete` | yes | unit-only / indirect | `tests/test_audit_security.py` | `test_delete_holiday_succeeds_with_antireplay` |
| GET `/schedule/admin/bulk-generate` | yes | true no-mock HTTP | `tests/e2e/conftest.py` | `ensure_schedule_slots` |
| POST `/schedule/admin/bulk-generate` | yes | unit-only / indirect | `tests/test_scheduling.py`, `tests/test_admin_schedule.py` | `test_bulk_generate`, `test_full_bootstrap_flow` |
| GET `/coverage/zones` | yes | true no-mock HTTP | `tests/test_coverage.py`, `tests/e2e/test_zones.py` | `test_zones_page_accessible_by_admin`, `test_zones_page_loads` |
| POST `/coverage/zones` | yes | unit-only / indirect | `tests/test_coverage.py` | `test_create_zone` |
| GET `/coverage/zones/:zone_id` | yes | unit-only / indirect | `tests/test_coverage.py` | `test_zone_detail` |
| POST `/coverage/zones/:zone_id` | yes | unit-only / indirect | `tests/test_coverage.py`, `tests/test_coverage_gaps.py` | `test_update_zone_ui_all_fields_persisted`, `test_update_zone_success` |
| POST `/coverage/zones/:zone_id/deactivate` | yes | unit-only / indirect | `tests/test_new_features.py` | `test_deactivate_zone_marks_inactive` |
| POST `/coverage/zones/:zone_id/assign` | yes | unit-only / indirect | `tests/test_coverage.py` | `test_assign_clinician_to_zone` |
| POST `/coverage/zones/:zone_id/windows` | yes | unit-only / indirect | `tests/test_coverage.py` | `test_create_delivery_window` |
| POST `/coverage/zones/:zone_id/windows/:window_id/delete` | yes | unit-only / indirect | `tests/test_coverage.py` | `test_delete_delivery_window` |
| POST `/coverage/zones/:zone_id/windows/:window_id/update` | yes | unit-only / indirect | `tests/test_coverage.py` | `test_update_delivery_window_success` |
| GET `/coverage/check` | yes | true no-mock HTTP | `tests/test_coverage.py`, `tests/e2e/test_zones.py` | `test_check_coverage_covered`, `test_coverage_check_endpoint` |
| GET `/visits/dashboard` | yes | true no-mock HTTP | `tests/test_visits.py`, `tests/e2e/test_visits.py` | `test_dashboard_accessible_by_admin`, `test_dashboard_loads_for_admin` |
| GET `/visits/dashboard/poll` | yes | true no-mock HTTP | `tests/test_visits.py`, `tests/e2e/test_visits.py` | `test_dashboard_poll_endpoint`, `test_dashboard_poll_endpoint` |
| POST `/visits/:visit_id/transition` | yes | unit-only / indirect | `tests/test_visits.py` | `test_transition_endpoint` |
| GET `/visits/:visit_id/timeline` | yes | unit-only / indirect | `tests/test_visits.py` | `test_timeline_endpoint` |
| GET `/staff/patients` | yes | unit-only / indirect | `tests/test_demographics.py` | `test_patient_list_page` |
| GET `/staff/patients/:patient_id/demographics` | yes | unit-only / indirect | `tests/test_demographics.py` | `test_staff_can_view_patient_demographics` |
| POST `/staff/patients/:patient_id/demographics` | yes | unit-only / indirect | `tests/test_demographics.py` | `test_staff_front_desk_can_edit_patient_demographics` |
| POST `/staff/patients/:patient_id/demographics/reveal` | yes | unit-only / indirect | `tests/test_coverage_gaps.py` | `test_reveal_insurance_id` |
| GET `/patient/demographics` | yes | true no-mock HTTP | `tests/test_demographics.py`, `tests/e2e/test_demographics.py` | `test_patient_can_view_demographics_page`, `test_demographics_page_loads` |
| POST `/patient/demographics` | yes | unit-only / indirect | `tests/test_demographics.py` | `test_patient_can_create_demographics` |
| POST `/patient/demographics/reveal` | yes | unit-only / indirect | `tests/test_demographics.py`, `tests/test_security.py` | `test_reveal_field`, `test_reveal_succeeds_with_valid_antireplay` |
| GET `/patient/export` | yes | unit-only / indirect | `tests/test_security.py` | `test_export_data_returns_json_download` |
| POST `/patient/delete-account` | yes | unit-only / indirect | `tests/test_delete_account.py` | `test_deleted_user_is_deactivated` |
| GET `/notes/patient/:patient_id` | yes | unit-only / indirect | `tests/test_notes.py` | `test_staff_can_read_patient_notes` |
| POST `/notes/patient/:patient_id` | yes | unit-only / indirect | `tests/test_notes.py` | `test_clinician_can_create_note` |
| GET `/notes/my` | yes | unit-only / indirect | `tests/test_notes.py` | `test_patient_can_read_own_notes` |
| GET `/reminders` | yes | unit-only / indirect | `tests/test_reminders.py` | `test_reminders_page_shows_pending` |
| POST `/reminders/:reminder_id/dismiss` | yes | unit-only / indirect | `tests/test_reminders.py` | `test_dismiss_reminder` |
| GET `/reminders/admin` | yes | unit-only / indirect | `tests/test_reminders.py` | `test_admin_reminders_page` |
| GET `/reminders/patient/count` | yes | unit-only / indirect | `tests/test_reminders.py` | `test_reminder_count_endpoint` |
| GET `/reminders/admin/config` | yes | unit-only / indirect | `tests/test_reminders.py` | `test_admin_config_page` |
| POST `/reminders/admin/config/:template_id` | yes | unit-only / indirect | `tests/test_reminders.py` | `test_admin_update_config` |

## API Test Classification

1. **True No-Mock HTTP**
   - Present under `repo/tests/e2e/` using Playwright browser requests and urllib helpers.
   - Evidence: `tests/e2e/test_zz_auth.py:test_login_valid_credentials`, `tests/e2e/test_scheduling.py:test_hold_and_confirm_slot`, `tests/e2e/test_zones.py:test_coverage_check_endpoint`.

2. **HTTP with Mocking**
   - Present in targeted tests.
   - Evidence:
     - `tests/test_scheduling.py:test_recount_guard_is_authoritative_even_when_precheck_bypassed` (patches `Slot.is_available`).
     - `tests/test_audit_security.py:test_slow_query_persisted_to_db` (patches middleware time).

3. **Non-HTTP (in-process route tests)**
   - Dominant test style across `repo/tests/test_*.py` using Flask `test_client`.

## Mock Detection

- `tests/test_scheduling.py:test_recount_guard_is_authoritative_even_when_precheck_bypassed`
  - What mocked: `Slot.is_available`.
  - Classification impact: that test is `HTTP with mocking`.

- `tests/test_audit_security.py:test_slow_query_persisted_to_db`
  - What mocked: `app.utils.middleware.time`.
  - Classification impact: that test is `HTTP with mocking`.

## Coverage Summary

- Total endpoints: **86**
- Endpoints with endpoint-level route tests: **86**
- Endpoints with strict true no-mock real HTTP evidence: **18**

- HTTP coverage %: **100.0%** (86/86)
- True API coverage %: **20.9%** (18/86)

## Unit Test Summary

Covered modules (representative):
- Controllers/routes: `tests/test_auth.py`, `tests/test_assessments.py`, `tests/test_scheduling.py`, `tests/test_coverage.py`, `tests/test_audit_coverage.py`
- Services/utils: anti-replay/idempotency/audit logic in `tests/test_audit_security.py`, `tests/test_idempotency.py`, `tests/test_audit.py`
- Models/repository behavior: `tests/test_delete_account.py`, `tests/test_notes.py`, `tests/test_reminders.py`
- Auth/guards/middleware: `tests/test_rbac.py`, `tests/test_security.py`, `tests/test_observability.py`

Important modules weakly tested directly:
- None critical are untested at endpoint level; remaining weakness is depth style in some negative-path assertions.

## API Observability Check

Assessment: **mostly strong**.

- Endpoint method/path usage is clear in route tests and E2E.
- Request inputs are usually explicit (`signed_data(...)`, form payloads, params).
- Response content + state checks are frequent (HTML/JSON assertions + DB assertions).

Weak spots:
- Some tests use permissive assertions (`status_code in (...)`, broad text exclusion) instead of exact forbidden/redirect behavior.

## Tests Check

- Relevant categories for this repo are present: `unit`, `integration/API-surface`, `end-to-end`.
- Suite is substantial and confidence-building for core product behavior.
- `repo/run_tests.sh` exists and is Docker-based for the main flow (`docker compose --profile test run --rm test-runner ... pytest`).
- `repo/run_tests.sh` includes coverage gate (`--cov-fail-under=90`) and runs E2E by default (`RUN_E2E=1`).
- Main test suite is Python-based; Bash is orchestration only.

## Test Coverage Score (0-100)

**91/100**

## Score Rationale

- Full endpoint breadth coverage with strong domain depth in security, RBAC, scheduling, assessments, and audit behavior.
- Score reduced for strict-mode reasons: true no-mock real transport coverage proportion is still limited compared to total endpoint surface, and a subset of negative-path assertions remains permissive.

## Key Gaps

- Increase real transport no-mock API tests for additional high-risk mutation endpoints.
- Tighten permissive assertions to exact outcomes for denied/redirect paths.

## Confidence & Assumptions

- Confidence: **high** for endpoint extraction and endpoint-test mapping.
- Confidence: **medium-high** for qualitative sufficiency scoring.
- No runtime execution was performed.

---

# README Audit

## High Priority Issues

- None.

## Medium Priority Issues

- None material.

## Low Priority Issues

- None material.

## Hard Gate Failures

- None.

## README Verdict

**PASS**

README hard-gate checks:
- Project type declared at top: `repo/README.md:3`
- Required location exists: `repo/README.md`
- Compose startup present: `repo/README.md:13`
- Access method documented: `repo/README.md:74-80`
- Verification method documented: `repo/README.md:34-47`
- Demo credentials for auth roles present: `repo/README.md:25-31`
- Seed consistency present in code: `repo/seed_test_data.py:21-42`
- Environment guidance is Docker-contained and avoids local runtime install requirements in the main flow: `repo/README.md:109-113`
