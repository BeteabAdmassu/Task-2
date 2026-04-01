# MeridianCare Clinic Operations Platform

A comprehensive clinic operations platform built with Flask, SQLite, and HTMX.

## Requirements

- Python 3.10+ (local development and unit tests)
- Docker (production deployment and E2E tests)

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

# Run in development mode (auto-generates ephemeral keys — not for production)
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

### `docker-compose.yml` — E2E testing only

The included `docker-compose.yml` contains **hardcoded example keys** intended solely for the
automated E2E test suite. **Do not use it for any real deployment.** Always supply your own
secrets via environment variables as shown above.

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

This script will:
1. Run unit/integration tests via pytest
2. Check that Docker is running
3. Build and start the app in a Docker container
4. Wait for the `/health` endpoint to respond
5. Run Playwright E2E tests against the containerized app
6. Tear down the Docker container
7. Exit with code 0 on success, non-zero on failure

## Security & Audit Features

### Encrypted Clinical Notes
Clinical notes are stored encrypted at rest using Fernet symmetric encryption (same key as all other field-level encryption). The `ClinicalNote` model exposes a `content` property that decrypts on access — the raw `content_encrypted` column is never exposed in responses or logs. Access control: patients may read their own notes via `GET /notes/my`; clinicians, front-desk staff, and administrators create and read notes via `GET/POST /notes/patient/<id>`.

### Admin Mutations — Reason Capture & Audit Trail
Both `change_role` and `change_status` in the admin panel require a non-empty `reason` field. On success, an `AuditLog` entry is written including: actor user ID, action (`change_role` / `change_status`), target user ID, before/after values, and the provided reason. Requests without a reason are rejected with HTTP 400.

### Assessment visit_id Validation
When a patient submits a health assessment with a `visit_id`, the route verifies the visit exists in the database and — for patient-role users — that `visit.patient_id` matches the submitting user. Invalid or unauthorized `visit_id` values return a validation error without creating an `AssessmentResult`.

## Project Structure

```
repo/
├── app/
│   ├── __init__.py          # App factory
│   ├── config.py            # Configuration classes
│   ├── extensions.py        # Flask extensions
│   ├── models/              # Database models
│   ├── routes/              # Blueprint route modules
│   ├── templates/           # Jinja2 templates
│   ├── static/              # CSS, JS, images
│   └── utils/               # Helpers (logging, crypto, etc.)
├── migrations/              # DB migration scripts
├── certs/                   # Self-signed certificates (auto-generated)
├── tests/                   # Unit & integration tests
│   └── e2e/                 # Playwright E2E tests
├── run_tests.sh             # Single script to run ALL tests
├── Dockerfile               # Production container image
├── docker-compose.yml       # Docker Compose config (E2E test keys — not for production)
├── requirements.txt         # Production dependencies
├── requirements-test.txt    # Test dependencies
└── run.py                   # Entry point
```
