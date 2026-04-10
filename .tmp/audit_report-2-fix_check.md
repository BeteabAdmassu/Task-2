# audit_report-2 Fix Check (Static-Only)

1. Verdict
- Pass (for issues raised in `audit_report-2.md`)

2. Scope and Verification Boundary
- Reviewed statically: scheduling hold idempotency implementation, related templates, updated tests, and documentation updates.
- Files reviewed include: `repo/app/routes/schedule.py`, `repo/app/templates/schedule/available.html`, `repo/tests/test_scheduling.py`, `docs/design.md`, `docs/api-spec.md`, plus spot-checks for prior high findings (`auth`, `patient/staff reveal`, `observability sessions`).
- Not executed: app runtime, tests, Docker, browser/HTMX flows.
- Runtime behavior remains Manual Verification Required.

3. Prior Findings Status (from `audit_report-2.md`)

## H-01 (High): request-token idempotency not enforced on scheduling holds
- Status: Fixed
- Evidence:
  - Token required in patient hold route: `repo/app/routes/schedule.py:108`
  - Missing token rejected with explicit handling: `repo/app/routes/schedule.py:109`
  - Replay handling returns deterministic prior outcome: `repo/app/routes/schedule.py:120`
  - Same enforcement on staff on-behalf hold: `repo/app/routes/schedule.py:310`, `repo/app/routes/schedule.py:322`
  - Hold form now includes token: `repo/app/templates/schedule/available.html:43`
  - Token-at-rest remains hashed (SHA-256): `repo/app/routes/schedule.py:116`, `repo/app/routes/schedule.py:159`
  - Coverage added for missing token + replay (patient and behalf): `repo/tests/test_scheduling.py:791`, `repo/tests/test_scheduling.py:828`, `repo/tests/test_scheduling.py:863`, `repo/tests/test_scheduling.py:884`

## M-01 (Medium): architecture documentation drift
- Status: Fixed
- Evidence:
  - Session model now documented as Flask-Login cookie-based (no sessions table): `docs/design.md:70`, `docs/design.md:167`
  - Schema naming aligned to implemented models (`audit_logs`, `signed_requests`, reservation request token notes): `docs/design.md:147`, `docs/design.md:262`, `docs/design.md:384`, `docs/design.md:412`

## M-02 (Medium): audit details typing inconsistency
- Status: Fixed
- Evidence:
  - `log_action` call sites pass structured dicts (no pre-serialized JSON strings): `repo/app/routes/admin.py:69`, `repo/app/routes/schedule.py:382`, `repo/app/routes/assessments.py:440`

## M-03 / L-01 (Docs clarity on response modes)
- Status: Fixed / Improved
- Evidence:
  - API spec now explicitly documents mixed response modes and HTMX-conditional behavior: `docs/api-spec.md:3`, `docs/api-spec.md:12`
  - Scheduling hold token requirement and replay semantics documented: `docs/api-spec.md:109`, `docs/api-spec.md:113`

4. Regression Spot-Checks for Earlier Audit Findings
- Login anti-replay wiring present and tested:
  - Route guard: `repo/app/routes/auth.py:158`
  - Login form anti-replay regression test: `repo/tests/test_auth.py:286`
- Stored-XSS reveal risk path remains escaped:
  - Patient reveal escape: `repo/app/routes/patient.py:201`
  - Staff reveal escape: `repo/app/routes/staff.py:89`
- Admin operations sessions endpoint now aligned with model field:
  - Uses `User.last_login_at`: `repo/app/routes/observability.py:74`
  - Field exists in model: `repo/app/models/user.py:17`
  - Endpoint test present: `repo/tests/test_observability.py:94`

5. Final Conclusion
- All issues identified in `audit_report-2.md` are resolved by static evidence.
- No new Blocker/High issue was identified in this targeted fix-check scope.
- Manual verification still recommended for runtime UX details (HTMX error rendering, redirect behavior, and concurrency under real deployment conditions).
