# API Specification

All endpoints are REST-style, consumed by HTMX partial updates. Responses return HTML fragments for HTMX requests (`HX-Request` header present) and JSON for direct API calls. All state-changing endpoints require CSRF tokens and, for sensitive actions, signed request timestamps with anti-replay nonces.

---

## Health & System

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/health` | Basic health check | None | — | `{"status": "ok", "timestamp": "ISO8601"}` |
| GET | `/health/detailed` | Extended health (DB status and table row counts) | Admin | — | `{"status": "ok", "database": "ok", "tables": {"users": 5, ...}}` |

---

## Authentication (`/auth`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/auth/register` | Registration page | None | — | HTML form |
| POST | `/auth/register` | Create account | None | `username`, `password`, `password_confirm` | Redirect to login (success) or HTML partial with errors |
| GET | `/auth/login` | Login page | None | — | HTML form |
| POST | `/auth/login` | Authenticate | None | `username`, `password`, signed timestamp + nonce + signature (anti-replay) | Session cookie + redirect to role dashboard |
| POST | `/auth/logout` | End session | Authenticated | CSRF token | Redirect to login |
| GET | `/auth/check-username` | HTMX username availability | None | `?username=<value>` | HTML partial: "Available" / "Taken" |

### Rate Limiting
- 10 login attempts per 10 minutes per account AND per IP address
- Exceeding returns 429 with lockout remaining time

---

## User Management (`/admin/users`) — Admin Only

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/admin/users` | List all users | Admin | — | HTML table |
| PUT | `/admin/users/<id>/role` | Change user role | Admin | `role`, `reason` (required), anti-replay fields | HTML partial (updated row) |
| PUT | `/admin/users/<id>/status` | Activate/deactivate user | Admin | `is_active` (true/1/yes/on), `reason` (required), anti-replay fields | HTML partial (updated row) |

### Constraints
- Cannot demote the last Administrator
- Cannot change own role

---

## Patient Demographics (`/patient`, `/staff/patients`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/patient/demographics` | View own demographics | Patient | — | HTML form (pre-filled or empty) |
| POST | `/patient/demographics` | Create/update own demographics | Patient | `full_name`, `date_of_birth`, `gender`, `phone`, `address_*`, `emergency_contact_*`, `insurance_id`, `government_id` | HTML partial (success banner) |
| POST | `/patient/demographics/reveal` | Reveal masked sensitive field | Patient | `field` (insurance_id/government_id), anti-replay fields | Plain text unmasked value |
| GET | `/staff/patients/<id>/demographics` | View patient demographics | Front Desk, Clinician | — | HTML form (editable for Front Desk, read-only for Clinician) |
| POST | `/staff/patients/<id>/demographics` | Edit patient demographics | Front Desk | Same fields as patient update, anti-replay fields | Redirect to patient demographics |
| POST | `/staff/patients/<id>/demographics/reveal` | Reveal masked field for a patient | Admin, Front Desk | `field` (insurance_id/government_id), anti-replay fields | Plain text unmasked value |

### Field Validation
- `full_name`: required, 1-200 chars
- `date_of_birth`: required, ISO date, not in the future
- `phone`: required, US format
- `address_zip`: 5 or 9 digit US ZIP
- `insurance_id`, `government_id`: encrypted at rest, masked in display (last 4 only)

---

## Health Assessments (`/assessments`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/assessments/start` | Begin assessment wizard (no linked visit) | Patient | — | HTML wizard (step 1: PHQ-9) |
| GET | `/assessments/start/<visit_id>` | Begin assessment wizard linked to a visit | Patient | — | HTML wizard (step 1: PHQ-9) |
| POST | `/assessments/step/<step>` | Submit a wizard step and advance | Patient | `visit_id` (optional), `request_token`, answer fields by question key | HTML partial (next step or review) |
| POST | `/assessments/save-draft` | Save partial progress without advancing | Patient | `visit_id` (optional), answer fields by question key | HTML partial (confirmation) |
| POST | `/assessments/submit` | Finalize assessment | Patient | `visit_id` (optional), `request_token`, anti-replay fields | Redirect to result page |
| GET | `/assessments/result/<assessment_id>` | View result with explanation | Patient, Clinician, Admin | — | HTML page (scores, risk level, rules) |
| GET | `/assessments/history` | Patient's assessment history | Patient | — | HTML timeline/list |

### Assessment Templates
- **PHQ-9**: 9 questions, 0-3 scale, total 0-27 → Minimal/Mild/Moderate/Moderately Severe/Severe
- **GAD-7**: 7 questions, 0-3 scale, total 0-21 → Minimal/Mild/Moderate/Severe
- **Blood Pressure**: Self-reported category (Normal/Elevated/Stage 1/Stage 2/Crisis)
- **Fall Risk**: Yes/No flags (history of falls, mobility aids, dizziness, balance medications)
- **Medication Adherence**: 4 questions, 0-3 scale (total 0-12) → never_miss (≤2) / rarely_miss (3-5) / sometimes_miss (6-8) / often_miss (9+)

### Risk Stratification Rules
- **High**: PHQ-9 ≥ 15 OR GAD-7 ≥ 15 OR BP = Crisis OR fall-risk ≥ 2 flags
- **Moderate**: PHQ-9 10-14 OR GAD-7 10-14 OR BP = Stage 1/2 OR fall-risk = 1 flag
- **Low**: All scores below moderate thresholds

---

## Scheduling (`/schedule`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/schedule/available` | Search available slots | Authenticated | `?date_from=`, `?date_to=`, `?clinician_id=` | HTML slot list |
| POST | `/schedule/hold/<slot_id>` | Create 10-min reservation hold | Patient | `request_token`, anti-replay fields | Redirect to confirm page |
| GET | `/schedule/confirm/<reservation_id>` | Confirm page with countdown | Patient | — | HTML confirm page |
| POST | `/schedule/confirm/<reservation_id>` | Confirm booking | Patient | anti-replay fields | Redirect to my appointments |
| POST | `/schedule/cancel/<reservation_id>` | Cancel hold or booking | Patient | anti-replay fields | Redirect to my appointments |
| POST | `/schedule/behalf/<patient_id>/hold/<slot_id>` | Staff hold on behalf | Admin, Front Desk | `request_token` | Redirect to behalf confirm page |
| GET | `/schedule/behalf/<patient_id>/confirm/<reservation_id>` | Staff confirm page | Admin, Front Desk | — | HTML confirm page |
| POST | `/schedule/behalf/<patient_id>/confirm/<reservation_id>` | Staff confirm booking | Admin, Front Desk | — | Redirect to staff calendar |
| GET | `/schedule/my-appointments` | Patient's appointments | Authenticated | — | HTML appointment list |
| GET | `/schedule/staff/calendar` | Staff calendar view | Admin, Clinician, Front Desk | `?week=`, `?clinician_id=` | HTML calendar (week view) |
| GET/POST | `/schedule/admin/holidays` | List/add holidays | Admin | `date`, `name` (POST) | HTML list |
| POST | `/schedule/admin/holidays/<id>/delete` | Remove holiday | Admin | — | Redirect to holidays |
| GET/POST | `/schedule/admin/bulk-generate` | Bulk slot generation | Admin | `clinician_id`, `date_from`, `date_to`, `room_id` (POST) | HTML form / redirect |

### Slot Defaults
- 15-minute duration, 1 patient capacity per clinician slot
- Reservation hold expires after 10 minutes
- Maximum 2 simultaneous holds per patient

---

## Visits & Dashboard (`/visits`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/visits/dashboard` | Shared visit dashboard (today's visits) | Front Desk, Clinician, Admin | — | HTML dashboard table |
| GET | `/visits/dashboard/poll` | HTMX polling for dashboard updates | Front Desk, Clinician, Admin | — | HTML partial (updated rows) |
| POST | `/visits/<id>/transition` | Advance visit state | Front Desk, Clinician, Admin | `target_state`, `reason` (required for canceled/no_show), `request_token`, anti-replay fields | HTML partial (updated row) |
| GET | `/visits/<id>/timeline` | Milestone timeline for a visit | Authenticated (staff or own) | — | HTML partial (transition history) |

### State Machine Transitions
```
Booked → Pending Payment → Checked In → Seen
Booked → Checked In → Seen
Booked → Canceled
Pending Payment → Canceled
Checked In → No-Show
Any active → Canceled (reason required)
Any checked_in → No-Show (reason required)
```

### Idempotency
- `_request_token` (UUID) generated per form load, consumed on use
- Duplicate token → 409 Conflict with "This action has already been processed"
- Optimistic concurrency: `UPDATE ... WHERE status = <expected>` prevents race conditions

---

## Service Coverage Zones (`/coverage`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/coverage/zones` | List all coverage zones | Admin | — | HTML table |
| POST | `/coverage/zones` | Create zone | Admin | `name`, `description`, `zip_codes`, `neighborhoods`, `distance_band_min`, `distance_band_max`, `min_order_amount`, `delivery_fee` | Redirect to zone list |
| GET | `/coverage/zones/<id>` | Zone detail | Admin | — | HTML detail page |
| POST | `/coverage/zones/<id>` | Update zone | Admin | Same fields as create | Redirect to zone detail |
| POST | `/coverage/zones/<id>/deactivate` | Soft-deactivate zone | Admin | `reason` (required), anti-replay fields | Redirect to zone list |
| POST | `/coverage/zones/<id>/assign` | Assign clinician to zone | Admin | `clinician_id`, `assignment_type` | Redirect to zone detail |
| POST | `/coverage/zones/<id>/windows` | Add delivery window | Admin | `day_of_week`, `start_time`, `end_time` | Redirect to zone detail |
| POST | `/coverage/zones/<id>/windows/<wid>/update` | Update delivery window | Admin | `day_of_week`, `start_time`, `end_time` | Redirect to zone detail |
| POST | `/coverage/zones/<id>/windows/<wid>/delete` | Delete delivery window | Admin | — | Redirect to zone detail |
| GET | `/coverage/check` | Check delivery eligibility | Patient, Front Desk | `?zip=<zip_code>&neighborhood=<name>&distance=<miles>` | JSON: `{"covered": bool, "zones": [...]}` |

### Zone Constraints
- ZIP codes unique across active zones
- Delivery windows within a zone cannot overlap
- Min order and delivery fee must be ≥ $0.00

---

## Reminders (`/reminders`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/reminders` | List active reminders | Patient | — | HTML reminder list |
| POST | `/reminders/<id>/dismiss` | Dismiss a reminder | Patient | anti-replay fields | Redirect to reminder list |
| GET | `/reminders/patient/count` | Badge count for nav | Patient | — | HTML partial (count badge) |
| GET | `/reminders/admin` | All pending patient reminders | Admin | — | HTML table |
| GET | `/reminders/admin/config` | Reassessment interval config | Admin | — | HTML form |
| POST | `/reminders/admin/config/<template_id>` | Update interval | Admin | `interval_days`, anti-replay fields | Redirect to config page |

### Defaults
- Chronic-care reassessment: every 90 days
- Pre-visit reminder: 24 hours before appointment

---

## Audit Log (`/admin/audit`) — Admin Only

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/admin/audit` | Audit log viewer with pagination | Admin | `?page=` | HTML table with pagination |

---

## Data Export & Deletion (`/patient`)

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/patient/export` | Download personal data | Patient | — | JSON file download |
| POST | `/patient/delete-account` | Request account anonymization | Patient | `password` (re-authentication), signed timestamp | Session terminated, redirect to login |

### Anonymization
- Name → `ANON-<hash>`, email/phone/IDs → null
- Visit dates, assessment scores preserved (de-identified)
- Audit events retain structure with anonymized actor

---

## Admin Operations & Observability (`/admin`) — Admin Only

| Method | Path | Description | Auth | Request | Response |
|--------|------|-------------|------|---------|----------|
| GET | `/admin/observability` | Observability dashboard (stats, alerts, slow queries) | Admin | — | HTML dashboard |
| GET | `/admin/operations` | Redirect to observability dashboard | Admin | — | 302 → `/admin/observability` |
| GET | `/admin/operations/alerts` | HTMX partial for alerts | Admin | — | HTML partial (alert list) |
| POST | `/admin/operations/alerts/<id>/acknowledge` | Acknowledge alert | Admin | anti-replay fields | Redirect to observability dashboard |
| GET | `/admin/operations/slow-queries` | HTMX partial for slow queries | Admin | — | HTML partial (query table) |
| GET | `/admin/operations/sessions` | Active sessions | Admin | — | HTML partial (session table) |

---

## Common Headers & Conventions

### Request Headers
| Header | Purpose | Required |
|--------|---------|----------|
| `X-CSRFToken` | CSRF protection (HTMX requests) | All POST/PUT/DELETE |
| `X-Request-Token` | Idempotency token | State-changing operations |
| `X-Timestamp` | Anti-replay ISO-8601 UTC timestamp | Sensitive actions (login, transitions, deletion) |
| `X-Nonce` | Anti-replay UUID nonce | Sensitive actions |
| `X-Signature` | HMAC-SHA256 over `METHOD\|path\|nonce\|timestamp` | Sensitive actions |
| `HX-Request` | HTMX request indicator (auto-set by HTMX) | HTMX calls |

> **Note**: Anti-replay fields can also be submitted as hidden form fields `_timestamp`, `_nonce`, and `_signature` (used by server-rendered HTMX forms via the `antireplay_inputs()` helper).

### Response Headers
| Header | Purpose |
|--------|---------|
| `X-Correlation-ID` | Request correlation UUID for tracing |
| `Strict-Transport-Security` | HSTS enforcement |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Content-Security-Policy` | CSP rules |

### Error Responses
| Status | Meaning | Body |
|--------|---------|------|
| 400 | Validation error | HTML partial with field errors / JSON `{"error": "...", "fields": {...}}` |
| 403 | Forbidden (CSRF fail, auth fail, role denied) | HTML 403 page / JSON `{"error": "Access denied"}` |
| 404 | Not found | HTML 404 page / JSON `{"error": "Not found"}` |
| 409 | Conflict (duplicate token, stale state) | HTML message / JSON `{"error": "Already processed"}` |
| 429 | Rate limited | HTML message with retry-after / JSON `{"error": "Too many attempts", "retry_after_seconds": N}` |
