"""Tests for bot.security — encryption, headers, rate limiting, validators."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_SECRET_TOKEN", "test-secret")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_RUN_SERVICE_URL", "https://test.run.app")

from bot.security.encryption import decrypt, encrypt
from bot.security.headers import SECURITY_HEADERS, SecurityHeadersMiddleware
from bot.security.rate_limiter import limiter, rate_limit_exceeded_handler
from bot.security.validators import (
    ValidationError,
    sanitize_for_logging,
    validate_text_length,
    validate_time_format,
    validate_timezone,
)


class TestEncryption:
    """Test encrypt/decrypt round-trip."""

    def test_encrypt_decrypt_roundtrip(self):
        """encrypt + decrypt returns identical plaintext."""
        plaintext = "my-secret-token-12345"
        encrypted = encrypt(plaintext)
        decrypted = decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_output(self):
        """Two encryptions of the same plaintext produce different ciphertexts (due to random nonce)."""
        plaintext = "my-secret-token"
        enc1 = encrypt(plaintext)
        enc2 = encrypt(plaintext)
        assert enc1 != enc2

    def test_encrypt_decrypt_empty_string(self):
        """Empty string can be encrypted and decrypted."""
        encrypted = encrypt("")
        decrypted = decrypt(encrypted)
        assert decrypted == ""

    def test_encrypt_decrypt_unicode(self):
        """Unicode text survives round-trip."""
        plaintext = "Zadzwonic do mamy po polsku"
        encrypted = encrypt(plaintext)
        decrypted = decrypt(encrypted)
        assert decrypted == plaintext


class TestSecurityHeaders:
    """Test security headers middleware."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        @app.get("/admin/test")
        async def test_admin():
            return JSONResponse({"ok": True})

        @app.get("/health")
        async def test_health():
            return JSONResponse({"status": "healthy"})

        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_security_headers_present_on_admin_routes(self, client):
        """Security headers are present on /admin/* responses."""
        response = client.get("/admin/test")
        assert response.status_code == 200

        for header, expected_value in SECURITY_HEADERS.items():
            assert header.lower() in {k.lower() for k in response.headers.keys()}, (
                f"Missing security header: {header}"
            )
            assert response.headers.get(header) == expected_value

    def test_security_headers_present_on_all_routes(self, client):
        """Security headers are present on all routes, not just admin."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"


class TestRateLimiter:
    """Test rate limiting functionality."""

    def test_rate_limiter_returns_429_after_limit(self):
        """Rate limiter returns 429 after exceeding the limit."""
        from slowapi import Limiter
        from slowapi.errors import RateLimitExceeded
        from slowapi.util import get_remote_address

        app = FastAPI()
        test_limiter = Limiter(key_func=get_remote_address)
        app.state.limiter = test_limiter
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

        @app.get("/auth/google/callback")
        @test_limiter.limit("3/minute")
        async def oauth_callback(request: Request):
            return JSONResponse({"ok": True})

        client = TestClient(app)

        # First 3 requests should succeed
        for i in range(3):
            response = client.get("/auth/google/callback")
            assert response.status_code == 200, f"Request {i+1} failed unexpectedly"

        # 4th request should be rate limited
        response = client.get("/auth/google/callback")
        assert response.status_code == 429
        data = response.json()
        assert data["error"]["code"] == "RATE_LIMITED"


class TestValidators:
    """Test input validators."""

    def test_validate_timezone_valid(self):
        result = validate_timezone("Europe/Warsaw")
        assert result == "Europe/Warsaw"

    def test_validate_timezone_invalid(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_timezone("Invalid/Zone")
        assert "Invalid timezone" in str(exc_info.value)

    def test_validate_timezone_empty(self):
        with pytest.raises(ValidationError):
            validate_timezone("")

    def test_validate_time_format_valid(self):
        assert validate_time_format("08:30") == "08:30"
        assert validate_time_format("00:00") == "00:00"
        assert validate_time_format("23:59") == "23:59"

    def test_validate_time_format_invalid_format(self):
        with pytest.raises(ValidationError):
            validate_time_format("8:30")

    def test_validate_time_format_invalid_hours(self):
        with pytest.raises(ValidationError):
            validate_time_format("25:00")

    def test_validate_time_format_invalid_minutes(self):
        with pytest.raises(ValidationError):
            validate_time_format("12:60")

    def test_validate_text_length_within_limit(self):
        result = validate_text_length("short text")
        assert result == "short text"

    def test_validate_text_length_exceeds_limit(self):
        with pytest.raises(ValidationError):
            validate_text_length("x" * 5000)

    def test_sanitize_for_logging_redacts_long_tokens(self):
        """Long alphanumeric strings are redacted."""
        text = "token abc123def456ghi789jkl012mno"
        sanitized = sanitize_for_logging(text)
        assert "abc123def456ghi789jkl012mno" not in sanitized
        assert "[REDACTED]" in sanitized

    def test_sanitize_for_logging_redacts_email(self):
        """Email addresses are redacted."""
        text = "user email: admin@example.com"
        sanitized = sanitize_for_logging(text)
        assert "admin@example.com" not in sanitized
        assert "[EMAIL_REDACTED]" in sanitized

    def test_sanitize_for_logging_preserves_short_text(self):
        """Short non-sensitive text is preserved."""
        text = "Hello world"
        sanitized = sanitize_for_logging(text)
        assert sanitized == "Hello world"
