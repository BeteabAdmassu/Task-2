# MeridianCare Clinic Operations Platform

A comprehensive clinic operations platform built with Flask, SQLite, and HTMX.

## Requirements

- Python 3.10+
- Docker (for E2E tests)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application (HTTPS on port 5000)
python run.py
```

Visit `https://localhost:5000` in your browser. Accept the self-signed certificate warning.

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
├── Dockerfile               # Container for E2E testing
├── docker-compose.yml       # Docker Compose config
├── requirements.txt         # Production dependencies
├── requirements-test.txt    # Test dependencies
└── run.py                   # Entry point
```
