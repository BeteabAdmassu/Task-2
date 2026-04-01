"""E2E tests for cross-cutting concerns."""

import urllib.request
import ssl
import json
import pytest


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_health_check_json(base_url):
    """Health endpoint returns valid JSON."""
    resp = urllib.request.urlopen(f"{base_url}/health", context=_ssl_ctx(), timeout=5)
    data = json.loads(resp.read())
    assert data["status"] == "ok"
    assert "timestamp" in data


def test_correlation_id_present(base_url):
    """Every response includes X-Correlation-ID header."""
    resp = urllib.request.urlopen(f"{base_url}/health", context=_ssl_ctx(), timeout=5)
    cid = resp.headers.get("X-Correlation-ID")
    assert cid is not None
    assert len(cid) > 0


def test_security_headers_present(base_url):
    """Security headers are set on all responses."""
    resp = urllib.request.urlopen(f"{base_url}/", context=_ssl_ctx(), timeout=5)
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "max-age" in (resp.headers.get("Strict-Transport-Security") or "")


def test_htmx_loaded_on_page(base_url):
    """HTMX JS is loaded on the landing page."""
    resp = urllib.request.urlopen(f"{base_url}/", context=_ssl_ctx(), timeout=5)
    body = resp.read().decode()
    assert "htmx.min.js" in body


def test_csrf_meta_tag_present(base_url):
    """CSRF token meta tag is in the base template."""
    resp = urllib.request.urlopen(f"{base_url}/", context=_ssl_ctx(), timeout=5)
    body = resp.read().decode()
    assert 'name="csrf-token"' in body
