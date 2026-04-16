#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== MeridianCare Test Suite ==="

RUN_E2E="${RUN_E2E:-1}"

# ── Step 1: Check Docker availability ──
echo ""
echo "--- Checking Docker availability ---"
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker is not installed or not in PATH."
    exit 1
fi
if ! docker info &>/dev/null; then
    echo "ERROR: Docker daemon is not running. Please start Docker and try again."
    exit 1
fi
echo "Docker is available."

# ── Step 2: Wait for app to become healthy ──
# CI starts the web container before calling this script; we wait here because
# the container may still be initialising.  Uses `docker inspect` — no Python
# required on the host.
echo ""
echo "--- Waiting for app to become healthy (up to 60 seconds) ---"
HEALTHY=false
CONTAINER_ID=$(docker compose ps -q web)
for i in $(seq 1 30); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_ID" 2>/dev/null || echo "starting")
    if [ "$STATUS" = "healthy" ]; then
        HEALTHY=true
        echo "App is healthy after $((i * 2))s."
        break
    fi
    sleep 2
done

if [ "$HEALTHY" != "true" ]; then
    echo "ERROR: App did not become healthy within 60 seconds."
    docker compose logs web
    exit 1
fi

# ── Step 3: Run unit/integration tests inside test-runner container ──
echo ""
echo "--- Running unit/integration tests ---"
docker compose --profile test run --rm test-runner \
    python -m pytest tests/ -v --ignore=tests/e2e/ --tb=short \
    --cov=app --cov-report=term-missing --cov-fail-under=90
UNIT_EXIT=$?

if [ "$UNIT_EXIT" -ne 0 ]; then
    echo "Unit tests failed. Skipping E2E tests."
    exit "$UNIT_EXIT"
fi
echo "--- Unit/integration tests passed ---"

if [ "$RUN_E2E" != "1" ]; then
    echo ""
    echo "=== Unit/integration tests passed (E2E skipped) ==="
    echo "Set RUN_E2E=0 to skip E2E tests."
    exit 0
fi

# ── Step 4: Run E2E tests inside test-runner container ──
# network_mode: host (set in docker-compose.yml) lets the container reach
# localhost:5000 — the port the web container binds on the host.
echo ""
echo "--- Running E2E Playwright tests ---"
docker compose --profile test run --rm test-runner \
    python -m pytest tests/e2e/ -v --tb=short ${HEADED:+--headed}
E2E_EXIT=$?

if [ "$E2E_EXIT" -ne 0 ]; then
    echo "E2E tests failed."
    exit "$E2E_EXIT"
fi

echo ""
echo "=== All tests passed ==="
exit 0
