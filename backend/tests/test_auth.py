"""Tests for authentication middleware."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_test_token(monkeypatch):
    """Set a test ACCESS_TOKEN for all tests in this module."""
    token = "test-token-" + "x" * 20
    monkeypatch.setenv("ACCESS_TOKEN", token)  # >= 32 chars
    monkeypatch.setenv("PYTEST_RUNNING", "true")
    # Do NOT import app until env is set
    import app.config

    monkeypatch.setattr(app.config.settings, "access_token", token)
    from app.main import app

    return app


@pytest.fixture
def client(set_test_token):
    return TestClient(set_test_token)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer test-token-" + "x" * 20}


# --- Health endpoint (public) ---


def test_health_no_auth(client):
    """Health endpoint should be accessible without authentication."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_with_auth(client, auth_headers):
    """Health endpoint should also work with authentication."""
    res = client.get("/api/health", headers=auth_headers)
    assert res.status_code == 200


# --- Auth verify endpoint (public but requires valid token for success) ---


def test_auth_verify_no_token(client):
    """Auth verify without token should return 401."""
    res = client.get("/api/auth/verify")
    assert res.status_code == 401


def test_auth_verify_valid_token(client, auth_headers):
    """Auth verify with valid token should return 200."""
    res = client.get("/api/auth/verify", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_auth_verify_invalid_token(client):
    """Auth verify with wrong token should return 401."""
    res = client.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer wrong-token-value-here"},
    )
    assert res.status_code == 401


# --- API routes: accessible without auth (AuthMiddleware removed) ---

PROTECTED_ROUTES = [
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/test-task-id-12345678"),
    ("GET", "/api/tasks/test-task-id-12345678/status"),
    ("GET", "/api/tasks/test-task-id-12345678/transcript"),
    ("GET", "/api/tasks/test-task-id-12345678/transcript/export"),
    ("GET", "/api/tasks/test-task-id-12345678/video"),
    ("GET", "/api/tasks/test-task-id-12345678/clips/0/download"),
    ("GET", "/api/tasks/test-task-id-12345678/clips/0/thumbnail"),
    ("GET", "/api/tasks/test-task-id-12345678/clips/0/subtitles"),
    ("GET", "/api/tasks/test-task-id-12345678/clips/0/subtitles/json"),
]


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES)
def test_api_route_accessible_without_auth(client, method, path):
    """API routes should be accessible without auth (AuthMiddleware removed).

    Returns 404 (task not found) for non-existent task IDs, not 401.
    """
    if method == "GET":
        res = client.get(path)
    else:
        res = client.request(method, path)

    # Without auth middleware, routes should NOT return 401.
    # Non-existent task IDs will return 404.
    assert res.status_code != 401


# --- Auth header is ignored (AuthMiddleware removed) ---


@pytest.mark.parametrize("method,path", PROTECTED_ROUTES[:3])  # Sample a few
def test_api_route_with_any_auth_header_still_accessible(client, method, path):
    """API routes with any auth header should still be accessible (auth is not enforced)."""
    if method == "GET":
        res = client.get(
            path,
            headers={"Authorization": "Bearer any-random-token"},
        )
    else:
        res = client.request(
            method,
            path,
            headers={"Authorization": "Bearer any-random-token"},
        )
    # Not enforced — should get 404 (not found) not 401
    assert res.status_code != 401


# --- Malformed auth header ---


def test_malformed_auth_header_ignored(client):
    """Auth header without Bearer prefix is ignored (no auth enforcement)."""
    res = client.get(
        "/api/tasks",
        headers={"Authorization": "test-token-" + "x" * 20},
    )
    assert res.status_code != 401


def test_empty_auth_header_ignored(client):
    """Empty Authorization header is ignored (no auth enforcement)."""
    res = client.get(
        "/api/tasks",
        headers={"Authorization": ""},
    )
    assert res.status_code != 401


# --- OPTIONS preflight ---


def test_options_preflight_no_auth(client):
    """OPTIONS requests should pass through without auth."""
    res = client.options("/api/tasks")
    assert res.status_code in (200, 204, 405)  # 405 = method not allowed, which is fine


# --- Security headers ---


def test_security_headers_present(client):
    """All responses should include security headers."""
    res = client.get("/api/health")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert "referrer-policy" in res.headers
    assert "content-security-policy" in res.headers
    assert "permissions-policy" in res.headers


def test_security_headers_on_success(client):
    """Responses should include security headers."""
    res = client.get("/api/health")
    assert res.status_code == 200
    assert "x-content-type-options" in res.headers


# --- Token is not required (AuthMiddleware removed) ---


def test_api_route_without_token_succeeds_or_404(client):
    """Without auth middleware, API routes should not return 401."""
    res = client.get("/api/tasks")
    # Either 200 (empty list) or another non-401 status
    assert res.status_code != 401


# --- Const-time comparison: verify endpoint still enforces auth internally ---


def test_auth_verify_still_checks_token(client):
    """The /api/auth/verify endpoint still validates tokens internally."""
    valid_token = "test-token-" + "x" * 20
    # Wrong token should still fail at the verify endpoint
    res = client.get(
        "/api/auth/verify",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res.status_code == 401
