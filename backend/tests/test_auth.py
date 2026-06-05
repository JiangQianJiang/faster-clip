"""Tests for authentication middleware."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def set_test_token(monkeypatch):
    """Set a test ACCESS_TOKEN for all tests in this module."""
    monkeypatch.setenv("ACCESS_TOKEN", "test-token-" + "x" * 20)  # >= 32 chars
    monkeypatch.setenv("PYTEST_RUNNING", "true")
    # Do NOT import app until env is set
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


# --- Protected routes: no auth ---

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
def test_protected_route_no_auth_returns_401(client, method, path):
    """All protected routes should return 401 without auth."""
    if method == "GET":
        res = client.get(path)
    else:
        res = client.request(method, path)

    assert res.status_code == 401
    assert "WWW-Authenticate" in res.headers
    assert res.headers["WWW-Authenticate"] == "Bearer"
    body = res.json()
    assert body["code"] == "UNAUTHORIZED"


# --- Protected routes: wrong token ---

@pytest.mark.parametrize("method,path", PROTECTED_ROUTES[:3])  # Sample a few
def test_protected_route_wrong_token_returns_401(client, method, path):
    """Protected routes with wrong token should return 401."""
    if method == "GET":
        res = client.get(
            path,
            headers={"Authorization": "Bearer wrong-token"},
        )
    else:
        res = client.request(
            method,
            path,
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert res.status_code == 401


# --- Malformed auth header ---

def test_malformed_auth_header(client):
    """Auth header without Bearer prefix should return 401."""
    res = client.get(
        "/api/tasks",
        headers={"Authorization": "test-token-" + "x" * 20},
    )
    assert res.status_code == 401


def test_empty_auth_header(client):
    """Empty Authorization header should return 401."""
    res = client.get(
        "/api/tasks",
        headers={"Authorization": ""},
    )
    assert res.status_code == 401


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


def test_security_headers_on_error(client):
    """Error responses should also include security headers."""
    res = client.get("/api/tasks")
    assert res.status_code == 401
    assert "x-content-type-options" in res.headers


# --- Token not logged ---

def test_auth_failure_does_not_log_token(client, caplog):
    """Auth failure should not log the submitted token."""
    import logging
    caplog.set_level(logging.WARNING, logger="app.auth")

    token = "secret-token-that-should-not-be-logged"
    res = client.get(
        "/api/tasks",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 401

    # Check that the token value is not in log output
    log_text = caplog.text
    assert token not in log_text


# --- Const-time comparison test ---

def test_token_prefix_only_attack(client):
    """Bearer prefix without valid token should fail (const-time prevents prefix attacks)."""
    valid_token = "test-token-" + "x" * 20
    # Try with just the prefix matching
    res = client.get(
        "/api/tasks",
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 401
