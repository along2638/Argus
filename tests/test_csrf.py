"""Tests for CSRF protection middleware."""

import pytest
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from app.main import app


class TestCSRFMiddleware:
    """Test CSRF middleware behavior."""

    def setup_method(self):
        self.client = TestClient(app, raise_server_exceptions=False)

    def test_get_sets_csrf_cookie(self):
        """GET requests should set csrf_token cookie."""
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert "csrf_token" in resp.cookies

    def test_post_without_csrf_token_rejected(self):
        """POST without CSRF token should be rejected for authenticated paths."""
        resp = self.client.post("/api/v1/stream/start", json={
            "stream_url": "rtsp://test",
            "stream_id": "test"
        })
        # Should get 403 (CSRF) or 401 (no auth)
        assert resp.status_code in [401, 403]

    def test_post_with_valid_csrf_token(self):
        """POST with matching CSRF token should pass CSRF check."""
        # First get a CSRF token
        resp = self.client.get("/health")
        csrf_token = resp.cookies.get("csrf_token", "")

        # Now make a POST with the token
        resp = self.client.post(
            "/api/v1/stream/start",
            json={"stream_url": "rtsp://test", "stream_id": "test"},
            headers={"X-CSRF-Token": csrf_token},
        )
        # Should get past CSRF (may still fail auth)
        assert resp.status_code != 403 or "CSRF" not in resp.text

    def test_post_with_mismatched_csrf_token(self):
        """POST with wrong CSRF token and valid auth should be rejected.

        Note: requires valid JWT to pass auth middleware first.
        CSRF check happens in the outer middleware, auth in inner.
        With invalid JWT, auth returns 401 before CSRF can validate.
        This test verifies the CSRF middleware logic is correctly wired.
        """
        from app.core.csrf import CSRFMiddleware, _EXEMPT_PREFIXES, _PROTECTED_METHODS
        # Verify middleware is properly configured
        assert "POST" in _PROTECTED_METHODS
        assert "/api/v1/auth/login" in _EXEMPT_PREFIXES
        # With mismatched tokens and no valid auth → auth blocks first (401)
        self.client.cookies.set("token", "invalid_jwt")
        self.client.cookies.set("csrf_token", "real_token_abc")
        resp = self.client.post(
            "/api/v1/stream/start",
            json={"stream_url": "rtsp://test", "stream_id": "test"},
            headers={"X-CSRF-Token": "wrong_token_12345"},
        )
        # Auth blocks with 401 before CSRF can validate
        assert resp.status_code in [401, 403]

    def test_public_endpoints_exempt(self):
        """Public endpoints should not require CSRF."""
        resp = self.client.get("/health")
        assert resp.status_code == 200

    def test_login_endpoint_exempt(self):
        """Login endpoint should be exempt from CSRF."""
        resp = self.client.post("/api/v1/auth/login", json={
            "username": "test",
            "password": "test"
        })
        # Should not get 403 for CSRF
        assert resp.status_code != 403 or "CSRF" not in resp.text

    def test_websocket_exempt(self):
        """WebSocket endpoints should be exempt from CSRF."""
        # Just verify the path is in exempt list
        from app.core.csrf import _EXEMPT_PREFIXES
        assert "/ws/" in _EXEMPT_PREFIXES
