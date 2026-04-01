"""E2E tests for the foundation — run against the Docker container."""

import urllib.request
import ssl
import json


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_health_endpoint(base_url):
    """Verify the /health endpoint returns OK."""
    resp = urllib.request.urlopen(f"{base_url}/health", context=_ssl_ctx(), timeout=5)
    assert resp.status == 200
    data = json.loads(resp.read())
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_index_page(base_url):
    """Verify the landing page loads."""
    resp = urllib.request.urlopen(f"{base_url}/", context=_ssl_ctx(), timeout=5)
    assert resp.status == 200
    body = resp.read().decode()
    assert "MeridianCare" in body


def test_correlation_id_header(base_url):
    """Verify X-Correlation-ID is in response headers."""
    resp = urllib.request.urlopen(f"{base_url}/health", context=_ssl_ctx(), timeout=5)
    assert "X-Correlation-ID" in resp.headers


def test_security_headers(base_url):
    """Verify security headers are present."""
    resp = urllib.request.urlopen(f"{base_url}/health", context=_ssl_ctx(), timeout=5)
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
