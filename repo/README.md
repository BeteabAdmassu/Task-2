# MeridianCare Clinic Operations Platform

A comprehensive clinic operations platform built with Flask, SQLite, and HTMX.

## Requirements

- Python 3.10+ (local development and unit tests)
- Docker (production deployment and E2E tests)

### Python dependencies

All dependencies are listed in `requirements.txt` and are **required** (none are optional):

| Package | Purpose |
|---|---|
| `cryptography` | Fernet field-level encryption, self-signed TLS cert generation |
| `APScheduler` | Background jobs: hold expiry (every 1 min), reminder generation (every 15 min) |
| `Flask-WTF` | CSRF protection |
| `bcrypt` | Password hashing |

Install with `pip install -r requirements.txt`.

## Environment Variables (Production)

The following environment variables **must** be set when running with `FLASK_ENV=production`:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Stable secret key for Flask session signing (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `ENCRYPTION_KEY` | Stable Fernet key for field-level encryption (e.g. `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `REQUEST_SIGNING_SECRET` | Stable HMAC secret used to sign anti-replay request fields (`_nonce`, `_timestamp`, `_signature` / `X-Signature`) (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`) |

The app will raise `RuntimeError` at startup if any of these are missing in production.
In development and testing, random/default keys are generated automatically.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run in development mode (auto-generates ephemeral keys -- not for production)
FLASK_ENV=development python run.py
```

Visit `https://localhost:5000` in your browser. Accept the self-signed certificate warning.

> **Note:** `python run.py` defaults to `production` mode. Set `FLASK_ENV=development` for local
> development (ephemeral keys are generated automatically). For production, set the required
> environment variables listed above before starting the app.

## Docker (Production Deployment)

Docker is the recommended way to run MeridianCare in production. The `Dockerfile` builds a
self-contained image that runs under `FLASK_ENV=production` and generates its own self-signed
TLS certificate at build time.

### Build and run manually

```bash
# Build the image
docker build -t meridiancare .

# Generate secrets (run once, store the output securely)
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
export REQUEST_SIGNING_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Run the container
docker run -d \
  -p 5000:5000 \
  -e FLASK_ENV=production \
  -e SECRET_KEY="$SECRET_KEY" \
  -e ENCRYPTION_KEY="$ENCRYPTION_KEY" \
  -e REQUEST_SIGNING_SECRET="$REQUEST_SIGNING_SECRET" \
  --name meridiancare \
  meridiancare
```

Visit `https://localhost:5000`. Accept the self-signed certificate warning (replace with a CA-issued
certificate for internet-facing deployments).

> **Important:** The three secret environment variables must be kept stable across restarts.
> Changing `SECRET_KEY` invalidates all active sessions; changing `ENCRYPTION_KEY` makes
> previously encrypted patient data unreadable.

### `docker-compose.yml` -- E2E testing only

The included `docker-compose.yml` contains **hardcoded example keys** intended solely for the
automated E2E test suite. **Do not use it for any real deployment.** Always supply your own
secrets via environment variables as shown above.

## Production Deployment Hardening

For internet-facing deployments, place nginx in front of the Flask app to add real TLS
termination and upstream rate limiting. A ready-to-use config is provided at
`nginx/nginx.conf`.

### What the nginx config provides

| Feature | Detail |
|---|---|
| HTTP → HTTPS redirect | All port 80 traffic redirected to 443 |
| TLS 1.2 / 1.3 only | Weak protocols and ciphers disabled |
| Login rate limiting | 10 req/min per IP (matches in-app Flask limit), burst of 5 |
| General rate limiting | 120 req/min per IP for all other routes, burst of 30 |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` |
| Static asset caching | 7-day `Cache-Control` on `/static/` |

### Quick setup

```bash
# Copy config and supply your TLS certificate
cp nginx/nginx.conf /etc/nginx/conf.d/meridiancare.conf
# Edit ssl_certificate / ssl_certificate_key paths, then:
nginx -t && nginx -s reload
```

For the upstream address, update the `meridiancare_app` upstream block in
`nginx/nginx.conf` to match your deployment (same-host `127.0.0.1:5000` or a
Docker service name such as `web:5000`).

### Secrets via `.env`

Copy `.env.example` to `.env`, fill in the three required secrets, then source it:

```bash
cp .env.example .env
# edit .env with your generated secrets
set -a && source .env && set +a
python run.py
```

## Running Tests

### Unit/Integration Tests Only

```bash
pip install -r requirements-test.txt
python -m pytest tests/ --ignore=tests/e2e/ -v
```

### Full Test Suite (Unit + E2E via Docker)

```bash
bash run_tests.sh
```

This script requires the web container to already be running (`docker compose up web -d`).

It will:
1. Run unit/integration tests via pytest
2. Check that Docker is running and the web container is up
3. Wait for the `/health` endpoint to respond
4. Run Playwright E2E tests against the containerized app
5. Exit with code 0 on success, non-zero on failure

## Token-at-Rest Protection

All request/idempotency tokens are stored as **SHA-256 hex digests** -- the raw client-supplied value is never written to the database or application logs.

| Column | Model | Storage |
|---|---|---|
| `AssessmentResult.request_token` | `app/models/assessment.py` | SHA-256 hash of the submitted token |
| `Reservation.request_token` | `app/models/scheduling.py` | SHA-256 hash of the submitted token |
| `RequestToken.token` | `app/models/idempotency.py` | SHA-256 hash (via `app/utils/idempotency.py`) |
| Anti-replay nonces (`SignedRequest.nonce`) | `app/models/audit.py` | SHA-256 hash (via `app/utils/antireplay.py`) |

Idempotency lookups hash the incoming token before querying, so duplicate-detection still works correctly without exposing the raw value.

## Time-Driven Hold Expiry

Reservation holds (10-minute window) are expired by **two complementary mechanisms**:

1. **Scheduled job** (`hold_expiry`, every 1 min) -- runs inside the APScheduler background thread started by `create_app()`. Holds are expired on a fixed cadence regardless of user traffic. This is the authoritative mechanism. With a 10-minute hold window and a 1-minute sweep, a hold can remain active for at most ~11 minutes -- one sweep interval beyond its nominal expiry.
2. **Lazy cleanup** (`schedule_bp.before_request`) -- `expire_stale_holds()` is also called on every request to the schedule blueprint. This provides immediate cleanup for active users but is not relied upon alone.

The scheduler is skipped in `testing` mode. Tests that need to verify time-driven expiry call `expire_stale_holds()` directly to simulate a scheduler firing.

```python
# Verify fixes without Docker:
python -m pytest tests/ --ignore=tests/e2e/ -v
# Targeted token-at-rest tests:
python -m pytest tests/test_assessments.py tests/test_scheduling.py -k "hash" -v
# Targeted expiry tests:
python -m pytest tests/test_scheduling.py -k "expiry" -v
# User-switch isolation:
python -m pytest tests/test_user_isolation.py -v
```

## Account Deletion & Anonymization

When a patient submits `POST /patient/delete-account` with a correct password and valid anti-replay token, the following happens:

### What is anonymized

| Record | Action |
|---|---|
| `users` row | `username` -> `deleted_<id>`, `is_active` -> `False` |
| `patient_demographics` | `full_name` -> "Deleted User"; `phone` -> placeholder "0000000"; `date_of_birth` -> epoch placeholder 1900-01-01; all other PII fields cleared |
| `demographics_change_log` | `old_value` and `new_value` set to `NULL`; timestamp and field name retained |
| `clinical_notes` (patient's notes) | `content_encrypted` replaced with encrypted placeholder "[content removed - account deleted]"; record structure (author, timestamp, visit link) retained |
| `assessment_drafts` | Deleted entirely (incomplete submissions, no legal hold) |
| `login_attempts` | `username` field set to `NULL` for all attempts using the original username |

### What is retained for legal/audit reasons

- **`audit_logs`** -- never modified; all audit entries are preserved indefinitely
- **`assessment_results`** -- record and scores retained; `patient_id` FK points to the now-deactivated anonymized user row
- **`visits`** -- appointment records retained; `patient_id` FK preserved for operational/audit queries
- **`reservations`** -- booking records retained; `patient_id` FK preserved
- **`demographics_change_log`** -- log entries retained (with PII values scrubbed); timestamps and field names preserved

### Limits and boundaries

- The deleted account cannot be reactivated or logged into (enforced by `is_active=False` and username replacement)
- Clinical note records authored by clinicians are not deleted -- only the encrypted content is replaced with a placeholder. Record structure is preserved for the clinician's practice audit trail.
- Staff-authored clinical note content is fully replaced; the note's link to the visit and the authoring clinician is kept.
- No schema migrations are required -- the anonymization operates entirely at the data level within existing columns.

## Security & Audit Features

### Encrypted Clinical Notes
Clinical notes are stored encrypted at rest using Fernet symmetric encryption (same key as all other field-level encryption). The `ClinicalNote` model exposes a `content` property that decrypts on access -- the raw `content_encrypted` column is never exposed in responses or logs. Access control: patients may read their own notes via `GET /notes/my`; clinicians, front-desk staff, and administrators create and read notes via `GET/POST /notes/patient/<id>`.

### Admin Mutations -- Reason Capture & Audit Trail
Both `change_role` and `change_status` in the admin panel require a non-empty `reason` field. On success, an `AuditLog` entry is written including: actor user ID, action (`change_role` / `change_status`), target user ID, before/after values, and the provided reason. Requests without a reason are rejected with HTTP 400.

### Assessment visit_id Validation
When a patient submits a health assessment with a `visit_id`, the route verifies the visit exists in the database and -- for patient-role users -- that `visit.patient_id` matches the submitting user. Invalid or unauthorized `visit_id` values return a validation error without creating an `AssessmentResult`.

## Project Structure

```
repo/
+-- app/
|   +-- __init__.py          # App factory
|   +-- config.py            # Configuration classes
|   +-- extensions.py        # Flask extensions
|   +-- models/              # Database models
|   +-- routes/              # Blueprint route modules
|   +-- templates/           # Jinja2 templates
|   +-- static/              # CSS, JS, images
|   +-- utils/               # Helpers (logging, crypto, etc.)
+-- migrations/              # DB migration scripts
+-- certs/                   # Self-signed certificates (auto-generated)
+-- tests/                   # Unit & integration tests
|   +-- e2e/                 # Playwright E2E tests
+-- run_tests.sh             # Single script to run ALL tests
+-- Dockerfile               # Production container image
+-- docker-compose.yml       # Docker Compose config (E2E test keys -- not for production)
+-- requirements.txt         # Production dependencies
+-- requirements-test.txt    # Test dependencies
+-- run.py                   # Entry point
```
