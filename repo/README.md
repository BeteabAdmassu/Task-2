# MeridianCare Clinic Operations Platform

**Project type:** Fullstack (Flask + HTMX + SQLite)

A clinic operations platform with scheduling, health assessments, visit tracking, coverage zones, encrypted demographics, and role-based access control.

## Quick Start (Docker Compose)

Prerequisites: **Docker** and **Docker Compose** installed. No local Python required.

```bash
# Build and start (seeds demo data automatically)
docker compose up --build -d

# Wait for the health check to pass (~10 seconds)
docker inspect --format='{{.State.Health.Status}}' TASK-2
```

Open **https://localhost:5000** in your browser and accept the self-signed certificate warning.

## Demo Credentials

The Docker Compose configuration seeds the following accounts automatically:

| Role | Username | Password |
|---|---|---|
| Administrator | `admin` | `Admin123` |
| Front Desk | `frontdesk` | `FrontDesk1` |
| Clinician | `drclinician` | `Clinician1` |
| Patient | `patient` | `Patient1` |

All four accounts are seeded automatically when the container starts. Additional patient accounts can be created via the **Register** page.

## Verify It Works

After `docker compose up --build -d` and the container is healthy:

1. **Admin login** -- Go to `https://localhost:5000/auth/login`. Log in as `admin` / `Admin123`. Open **Users** in the nav bar. Confirm the users table loads with at least `admin`, `frontdesk`, `drclinician`, `patient`.

2. **Patient login + demographics** -- Click **Logout**. Log in as `patient` / `Patient1`. Navigate to **My Profile**. Fill in the demographics form (name, DOB, phone) and click **Save Demographics**. Reload the page -- the saved values appear pre-filled.

3. **Appointment booking** -- As `patient`, click **Book Appointment**. Click **Hold** on any available slot. On the confirm page, click **Confirm Booking**. Navigate to **My Appointments** -- the booking shows as **Confirmed**.

4. **Health assessment** -- Click **Assessments** in the nav bar. Click **New Assessment**. Complete all 5 steps (PHQ-9, GAD-7, Blood Pressure, Fall Risk, Medication Adherence) and submit. The result page shows a risk level (Low/Moderate/High).

5. **Coverage check** -- Log in as `admin` / `Admin123`. Navigate to **Zones**. A "Downtown" zone is pre-seeded. Log out and log in as `patient` / `Patient1`. Visit `https://localhost:5000/coverage/check?zip=10001` -- the JSON response shows `"covered": true`.

## Run Tests (Docker)

All tests run inside Docker containers. No local Python or pip required.

```bash
# 1. Start the web container (if not already running)
docker compose up --build -d

# 2. Run the full suite (unit + integration + E2E)
bash run_tests.sh
```

`run_tests.sh` will:
1. Verify Docker is available and the web container is healthy
2. Run unit/integration tests with coverage (`--cov-fail-under=90`)
3. Run Playwright E2E tests against the live container
4. Exit 0 on success, non-zero on failure

To run only unit/integration tests (faster, no browser):
```bash
docker compose --profile test run --rm test-runner \
  python -m pytest tests/ --ignore=tests/e2e/ -v
```

## Access

| URL | Description |
|---|---|
| `https://localhost:5000` | Main application |
| `https://localhost:5000/health` | Health check (JSON) |
| `https://localhost:5000/health/detailed` | Detailed health (admin only) |
| `https://localhost:5000/admin/observability` | System dashboard (admin only) |

## Security and Audit Features

### Token-at-Rest Protection

All request/idempotency tokens are stored as **SHA-256 hex digests** -- the raw value never reaches the database or logs.

### Anti-Replay

State-changing endpoints require HMAC-signed `_nonce` + `_timestamp` + `_signature` fields. The server verifies the signature and rejects replayed nonces within a 5-minute window.

### Encrypted Fields

Patient `insurance_id` and `government_id` are encrypted at rest using Fernet. Clinical note content is also encrypted. Masked display (last 4 chars) with explicit reveal action.

### Audit Logging

Admin mutations (role change, status change) require a `reason` field. All actions are logged to `audit_logs` with actor, resource, timestamp, IP, and user-agent.

### Account Anonymization

`POST /patient/delete-account` anonymizes all PII (demographics, clinical notes, login attempts) while retaining de-identified visit/assessment records for legal compliance.

## Production Deployment

> The `docker-compose.yml` contains **hardcoded test keys** for the E2E test suite. For real deployments, supply your own secrets.

### Required environment variables

| Variable | Description | Generate with (Docker) |
|---|---|---|
| `SECRET_KEY` | Flask session signing | `docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | Fernet field encryption | `docker run --rm python:3.12-slim python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` |
| `REQUEST_SIGNING_SECRET` | HMAC anti-replay signing | `docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_hex(32))"` |

A `.env.example` template is provided. Copy to `.env`, fill in secrets, and pass to Docker:

```bash
docker run -d -p 5000:5000 --env-file .env meridiancare
```

> **Stability warning:** Changing `SECRET_KEY` invalidates all sessions. Changing `ENCRYPTION_KEY` makes encrypted patient data unreadable.

### Nginx reverse proxy

For internet-facing deployments, use `nginx/nginx.conf` which provides:
- HTTP-to-HTTPS redirect
- TLS 1.2/1.3 with modern ciphers
- Login rate limiting (10 req/min per IP)
- General rate limiting (120 req/min per IP)
- Security headers and static asset caching

### Hold Expiry

Reservation holds expire after 10 minutes via two mechanisms:
1. **APScheduler job** (every 1 min) -- authoritative, traffic-independent
2. **Lazy cleanup** on schedule blueprint requests -- immediate for active users

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
|   +-- utils/               # Helpers (encryption, audit, scoring, etc.)
+-- tests/                   # Unit and integration tests
|   +-- e2e/                 # Playwright E2E tests
+-- nginx/                   # Production nginx config
+-- run_tests.sh             # Dockerized test runner
+-- Dockerfile               # Production image
+-- docker-compose.yml       # Compose config (test keys only)
+-- .env.example             # Secret template for production
+-- requirements.txt         # Python dependencies
+-- run.py                   # Entry point
```
