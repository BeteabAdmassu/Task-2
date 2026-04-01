# Design Document

## Architecture

### Overview
MeridianCare is a self-contained clinic operations platform that runs entirely on an internal workstation or clinic LAN. It follows a monolithic server-rendered architecture with HTMX for dynamic UI updates — no SPA framework, no external service dependencies.

### Architecture Diagram
```
┌─────────────────────────────────────────────────────────┐
│                      Browser (HTMX)                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │ Login/   │ │ Patient  │ │ Sched/   │ │ Admin     │  │
│  │ Register │ │ Portal   │ │ Dashboard│ │ Console   │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
└───────┼─────────────┼───────────┼──────────────┼────────┘
        │  HTTPS (self-signed)    │              │
┌───────┼─────────────┼───────────┼──────────────┼────────┐
│       ▼             ▼           ▼              ▼        │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Flask Application                    │   │
│  │  ┌─────────┐ ┌──────────┐ ┌────────────────────┐ │   │
│  │  │ Auth    │ │ CSRF /   │ │ Correlation ID     │ │   │
│  │  │ + RBAC  │ │ Anti-    │ │ Middleware          │ │   │
│  │  │ Middle- │ │ Replay   │ │                    │ │   │
│  │  │ ware    │ │ Guard    │ │                    │ │   │
│  │  └────┬────┘ └────┬─────┘ └────────┬───────────┘ │   │
│  │       ▼           ▼                ▼             │   │
│  │  ┌──────────────────────────────────────────────┐ │   │
│  │  │              Route Blueprints                │ │   │
│  │  │  auth │ patient │ schedule │ visits │ admin  │ │   │
│  │  │  assessments │ zones │ reminders │ audit    │ │   │
│  │  └──────────────────┬───────────────────────────┘ │   │
│  │                     ▼                             │   │
│  │  ┌──────────────────────────────────────────────┐ │   │
│  │  │           Business Logic Layer               │ │   │
│  │  │  State Machine │ Risk Engine │ Scheduler     │ │   │
│  │  │  Zone Lookup │ Audit Logger │ Encryption     │ │   │
│  │  └──────────────────┬───────────────────────────┘ │   │
│  │                     ▼                             │   │
│  │  ┌──────────────────────────────────────────────┐ │   │
│  │  │              Data Access Layer               │ │   │
│  │  │         (Parameterized SQL / ORM)            │ │   │
│  │  └──────────────────┬───────────────────────────┘ │   │
│  └─────────────────────┼────────────────────────────┘   │
│                        ▼                                │
│  ┌──────────────────────────────────────────────────┐   │
│  │              SQLite Database                      │   │
│  │  (single file, encryption at rest for PII fields) │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │         APScheduler (in-process)                  │   │
│  │  • Reservation hold expiry (every 1 min)          │   │
│  │  • Reassessment reminders (daily)                 │   │
│  │  • Pre-visit reminders (hourly)                   │   │
│  │  • Anomaly detection (every 5 min)                │   │
│  │  • Token cleanup (daily)                          │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│                Flask Server Process                     │
└─────────────────────────────────────────────────────────┘
```

### Key Architecture Decisions

1. **Monolithic + HTMX over SPA**: Clinic LAN deployment eliminates the need for a CDN-served frontend. HTMX partial updates provide interactivity without the complexity of React/Vue, keeping the stack simple and fully self-contained.

2. **SQLite over PostgreSQL/MySQL**: Single-file database requires zero setup, no separate server process, and works offline. Adequate for single-clinic workloads (< 100 concurrent users).

3. **In-process scheduler over external cron**: APScheduler runs within the Flask process, eliminating the need for OS-level cron configuration and ensuring scheduler state is co-located with application state.

4. **Server-side sessions over JWT**: Sessions stored in SQLite enable server-side session invalidation, which is critical for role changes and account deactivation taking effect immediately.

5. **Field-level encryption over full-disk encryption**: Fernet encryption on specific PII/clinical fields provides defense-in-depth even if the SQLite file is copied from the workstation.

### Request Flow
```
Browser → HTTPS → Flask Middleware Pipeline:
  1. Correlation ID assignment (UUID per request)
  2. Structured logging (start)
  3. CSRF validation (POST/PUT/DELETE)
  4. Session/authentication check
  5. Role-based authorization
  6. Anti-replay validation (sensitive endpoints)
  7. Idempotency token validation (state-changing endpoints)
  8. → Route handler → Business logic → Database
  9. Audit log recording
  10. Structured logging (end, with duration)
  11. ← Response (HTML partial for HTMX / JSON for API)
```

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | Python 3.10+ | Server-side logic |
| **Web Framework** | Flask | HTTP routing, templating, middleware |
| **Template Engine** | Jinja2 | Server-rendered HTML with autoescaping |
| **Frontend Interactivity** | HTMX | Partial page updates, form handling, polling |
| **Styling** | CSS (custom) | Clinic-appropriate responsive design |
| **Database** | SQLite3 | Offline-capable relational persistence |
| **ORM / DB Access** | SQLAlchemy or raw parameterized SQL | Data access with injection protection |
| **Password Hashing** | bcrypt or argon2-cffi | Secure credential storage |
| **Encryption** | cryptography (Fernet) | AES field-level encryption at rest |
| **CSRF Protection** | Flask-WTF (CSRFProtect) | Cross-site request forgery prevention |
| **Scheduling** | APScheduler | In-process periodic tasks |
| **Logging** | Python logging (JSON formatter) | Structured, rotated log files |
| **TLS** | pyOpenSSL / ssl module | Self-signed HTTPS certificates |
| **Testing (Unit/Integration)** | pytest | Unit and integration tests |
| **Testing (E2E)** | Playwright (pytest-playwright) | Browser-based end-to-end tests |
| **Containerization** | Docker + Docker Compose | E2E test environment |

### Dependencies (requirements.txt)
```
flask
flask-wtf
cryptography
bcrypt  # or argon2-cffi
apscheduler
pyopenssl
```

### Test Dependencies (requirements-test.txt)
```
pytest
pytest-playwright
playwright
```

---

## Database Schema

### Entity Relationship Overview
```
users ──────┬──── patient_demographics
            │
            ├──── sessions
            │
            ├──── login_attempts
            │
            ├──── visits ──────┬──── visit_transitions
            │     │            └──── assessment_results
            │     │
            │     └──── reservations ──── slots
            │                              │
            ├──── reminders                └──── rooms
            │
            └──── audit_log

clinicians ──── schedule_templates ──── slots

assessment_templates ──── assessment_results
                     └──── assessment_drafts
                     └──── reassessment_config

coverage_zones ──── zone_zip_codes
               └──── zone_delivery_windows

holidays (standalone)
request_tokens (standalone)
signed_nonces (standalone)
anomaly_alerts (standalone)
slow_queries (standalone)
```

### Table Definitions

#### `users`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| username | TEXT | UNIQUE, NOT NULL | 3-50 chars, alphanumeric + underscore |
| password_hash | TEXT | NOT NULL | bcrypt/argon2 hash |
| role | TEXT | NOT NULL, DEFAULT 'Patient' | Administrator, Clinician, Front Desk, Patient |
| is_active | BOOLEAN | NOT NULL, DEFAULT 1 | Deactivated users cannot log in |
| created_at | TIMESTAMP | NOT NULL, DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TIMESTAMP | NOT NULL | |

#### `sessions`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | TEXT | PRIMARY KEY | Session ID (UUID) |
| user_id | INTEGER | FK → users.id | |
| ip_address | TEXT | NOT NULL | |
| user_agent | TEXT | | |
| created_at | TIMESTAMP | NOT NULL | |
| last_activity | TIMESTAMP | NOT NULL | |
| expires_at | TIMESTAMP | NOT NULL | Default: 30 min inactivity |

#### `login_attempts`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| username | TEXT | NOT NULL | |
| ip_address | TEXT | NOT NULL | |
| success | BOOLEAN | NOT NULL | |
| attempted_at | TIMESTAMP | NOT NULL | |

#### `patient_demographics`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| user_id | INTEGER | FK → users.id, UNIQUE | |
| full_name | TEXT | NOT NULL | |
| date_of_birth | DATE | NOT NULL | Cannot be in the future |
| gender | TEXT | | |
| phone | TEXT | NOT NULL | US format validated |
| address_street | TEXT | | |
| address_city | TEXT | | |
| address_state | TEXT | | |
| address_zip | TEXT | | 5 or 9 digit |
| emergency_contact_name | TEXT | | |
| emergency_contact_phone | TEXT | | |
| emergency_contact_relationship | TEXT | | |
| insurance_id_encrypted | BLOB | | Fernet-encrypted, displayed masked (last 4) |
| government_id_encrypted | BLOB | | Fernet-encrypted, displayed masked (last 4) |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |

#### `clinicians`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| user_id | INTEGER | FK → users.id, UNIQUE | |
| specialty | TEXT | | |
| default_slot_duration_minutes | INTEGER | DEFAULT 15 | |

#### `schedule_templates`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| clinician_id | INTEGER | FK → clinicians.id | |
| day_of_week | INTEGER | NOT NULL | 0=Monday, 6=Sunday |
| start_time | TIME | NOT NULL | |
| end_time | TIME | NOT NULL | |
| slot_duration | INTEGER | DEFAULT 15 | Minutes |
| capacity | INTEGER | DEFAULT 1 | Patients per slot |

#### `rooms`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| name | TEXT | NOT NULL, UNIQUE | |
| description | TEXT | | |
| is_active | BOOLEAN | DEFAULT 1 | |

#### `slots`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| clinician_id | INTEGER | FK → clinicians.id | |
| room_id | INTEGER | FK → rooms.id, NULLABLE | |
| date | DATE | NOT NULL | |
| start_time | TIME | NOT NULL | |
| end_time | TIME | NOT NULL | |
| capacity | INTEGER | DEFAULT 1 | |
| booked_count | INTEGER | DEFAULT 0 | |
| status | TEXT | DEFAULT 'available' | available, full, blocked |

#### `reservations`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| slot_id | INTEGER | FK → slots.id | |
| patient_id | INTEGER | FK → users.id | |
| status | TEXT | NOT NULL | held, confirmed, expired, canceled |
| held_at | TIMESTAMP | | |
| confirmed_at | TIMESTAMP | | |
| expires_at | TIMESTAMP | | held_at + 10 minutes |

#### `holidays`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| date | DATE | NOT NULL, UNIQUE | |
| name | TEXT | NOT NULL | |
| created_by | INTEGER | FK → users.id | |

#### `visits`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| patient_id | INTEGER | FK → users.id | |
| clinician_id | INTEGER | FK → clinicians.id | |
| slot_id | INTEGER | FK → slots.id | |
| status | TEXT | NOT NULL, DEFAULT 'Booked' | Booked, Pending Payment, Checked In, Seen, Canceled, No-Show |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |

#### `visit_transitions`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| visit_id | INTEGER | FK → visits.id | |
| from_status | TEXT | NOT NULL | |
| to_status | TEXT | NOT NULL | |
| changed_by | INTEGER | FK → users.id | |
| reason | TEXT | | Required for cancellations and admin overrides |
| request_token | TEXT | UNIQUE | Idempotency enforcement |
| timestamp | TIMESTAMP | NOT NULL | |

#### `assessment_templates`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| name | TEXT | NOT NULL | PHQ-9, GAD-7, etc. |
| version | INTEGER | NOT NULL | Incremented on definition change |
| questions_json | TEXT | NOT NULL | JSON array of question definitions |
| scoring_rules_json | TEXT | NOT NULL | JSON rules for scoring and risk stratification |
| created_at | TIMESTAMP | NOT NULL | |

#### `assessment_results`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| patient_id | INTEGER | FK → users.id | |
| visit_id | INTEGER | FK → visits.id | |
| template_id | INTEGER | FK → assessment_templates.id | |
| template_version | INTEGER | NOT NULL | Snapshot of version at submission |
| answers_json | TEXT | NOT NULL | All answers preserved |
| scores_json | TEXT | NOT NULL | Computed scores |
| risk_level | TEXT | NOT NULL | Low, Moderate, High |
| explanation_snapshot_json | TEXT | NOT NULL | Rules + contributing answers |
| submitted_at | TIMESTAMP | NOT NULL | |

#### `assessment_drafts`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| patient_id | INTEGER | FK → users.id | |
| visit_id | INTEGER | FK → visits.id | |
| template_id | INTEGER | FK → assessment_templates.id | |
| partial_answers_json | TEXT | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |

#### `reassessment_config`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| template_id | INTEGER | FK → assessment_templates.id | |
| interval_days | INTEGER | DEFAULT 90 | |
| is_active | BOOLEAN | DEFAULT 1 | |

#### `reminders`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| patient_id | INTEGER | FK → users.id | |
| type | TEXT | NOT NULL | reassessment, pre_visit |
| related_entity_type | TEXT | | assessment_template, visit |
| related_entity_id | INTEGER | | |
| message | TEXT | NOT NULL | |
| status | TEXT | DEFAULT 'pending' | pending, seen, acted_on, dismissed, expired |
| created_at | TIMESTAMP | NOT NULL | |
| seen_at | TIMESTAMP | | |
| acted_at | TIMESTAMP | | |
| dismissed_at | TIMESTAMP | | |
| expires_at | TIMESTAMP | | |

#### `coverage_zones`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| name | TEXT | NOT NULL | |
| description | TEXT | | |
| distance_band_min | REAL | | Miles from clinic |
| distance_band_max | REAL | | Miles from clinic |
| min_order_amount | REAL | DEFAULT 0.00 | e.g., $25.00 |
| delivery_fee | REAL | DEFAULT 0.00 | e.g., $5.00 |
| is_active | BOOLEAN | DEFAULT 1 | Soft delete |
| created_at | TIMESTAMP | NOT NULL | |
| updated_at | TIMESTAMP | NOT NULL | |
| created_by | INTEGER | FK → users.id | |

#### `zone_zip_codes`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| zone_id | INTEGER | FK → coverage_zones.id | |
| zip_code | TEXT | NOT NULL | Unique across active zones |

#### `zone_delivery_windows`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| zone_id | INTEGER | FK → coverage_zones.id | |
| day_of_week | TEXT | DEFAULT 'all' | 'all' or 0-6 |
| start_time | TIME | NOT NULL | e.g., 09:00 |
| end_time | TIME | NOT NULL | e.g., 12:00 |

#### `audit_log`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| timestamp | TIMESTAMP | NOT NULL | |
| event_type | TEXT | NOT NULL | auth, user_mgmt, visit, assessment, schedule, demographics, zone, data_request, admin |
| actor_id | INTEGER | | FK → users.id (nullable for anonymized) |
| actor_role | TEXT | | |
| actor_ip | TEXT | | |
| target_type | TEXT | | user, visit, assessment, slot, zone, etc. |
| target_id | INTEGER | | |
| action | TEXT | NOT NULL | login, logout, create, update, delete, transition, view, export, anonymize |
| details_json | TEXT | | Before/after values, reason, etc. |
| correlation_id | TEXT | | Request UUID |

**Indexes:** `(event_type, timestamp)`, `(target_type, target_id)`, `(actor_id)`
**Constraints:** No UPDATE or DELETE allowed (append-only)

#### `request_tokens`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| token | TEXT | UNIQUE, NOT NULL | UUID |
| user_id | INTEGER | FK → users.id | Bound to authenticated user |
| endpoint | TEXT | | Route path |
| created_at | TIMESTAMP | NOT NULL | |
| expires_at | TIMESTAMP | NOT NULL | created_at + 30 minutes |
| used_at | TIMESTAMP | | NULL until consumed |
| result_snapshot_json | TEXT | | Original response for idempotent replay |

#### `signed_nonces`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| nonce | TEXT | UNIQUE, NOT NULL | |
| timestamp | TIMESTAMP | NOT NULL | |
| expires_at | TIMESTAMP | NOT NULL | timestamp + 5 minutes |

#### `anomaly_alerts`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| alert_type | TEXT | NOT NULL | failed_login_burst, new_ip_session, high_error_rate |
| severity | TEXT | NOT NULL | critical, warning, info |
| message | TEXT | NOT NULL | |
| details_json | TEXT | | |
| created_at | TIMESTAMP | NOT NULL | |
| acknowledged_at | TIMESTAMP | | |
| acknowledged_by | INTEGER | FK → users.id | |

#### `slow_queries`
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| query_text_sanitized | TEXT | NOT NULL | No parameter values |
| duration_ms | REAL | NOT NULL | |
| endpoint | TEXT | | |
| correlation_id | TEXT | | |
| timestamp | TIMESTAMP | NOT NULL | |
