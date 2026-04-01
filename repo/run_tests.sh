#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== MeridianCare Test Suite ==="

# ── Step 1: Install dependencies ──
echo ""
echo "--- Installing dependencies ---"
pip install -r requirements.txt -r requirements-test.txt 2>&1 | tail -3

# ── Step 2: Run unit/integration tests ──
echo ""
echo "--- Running unit/integration tests ---"
python -m pytest tests/ -v --ignore=tests/e2e/ --tb=short
UNIT_EXIT=$?

if [ "$UNIT_EXIT" -ne 0 ]; then
    echo "Unit tests failed. Skipping E2E tests."
    exit "$UNIT_EXIT"
fi
echo "--- Unit/integration tests passed ---"

# ── Step 3: Check Docker is available ──
echo ""
echo "--- Checking Docker availability ---"
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed or not in PATH."
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "ERROR: Docker is not running. Please start Docker and try again."
    exit 1
fi
echo "Docker is available."

# ── Step 4: Build and start the app container ──
echo ""
echo "--- Building and starting Docker container ---"
docker compose down --remove-orphans 2>/dev/null || true
docker compose build
docker compose up -d

# ── Step 5: Wait for healthy response ──
echo ""
echo "--- Waiting for /health endpoint (up to 30 seconds) ---"
HEALTHY=false
for i in $(seq 1 30); do
    if python -c "
import urllib.request, ssl, sys
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
try:
    resp = urllib.request.urlopen('https://localhost:5000/health', context=ctx, timeout=2)
    sys.exit(0 if resp.status == 200 else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        HEALTHY=true
        echo "App is healthy after ${i}s."
        break
    fi
    sleep 1
done

if [ "$HEALTHY" != "true" ]; then
    echo "ERROR: App did not become healthy within 30 seconds."
    docker compose logs
    docker compose down --remove-orphans
    exit 1
fi

# ── Step 6: Install Playwright browsers ──
echo ""
echo "--- Installing Playwright browsers ---"
python -m playwright install chromium --with-deps 2>/dev/null || python -m playwright install chromium 2>/dev/null || true

# ── Step 7: Run E2E tests ──
echo ""
echo "--- Running E2E Playwright tests ---"
E2E_EXIT=0
python -m pytest tests/e2e/ -v --tb=short ${HEADED:+--headed} || E2E_EXIT=$?

# ── Step 8: Tear down ──
echo ""
echo "--- Tearing down Docker container ---"
docker compose down --remove-orphans

if [ "$E2E_EXIT" -ne 0 ]; then
    echo "E2E tests failed."
    exit "$E2E_EXIT"
fi

echo ""
echo "=== All tests passed ==="
exit 0
