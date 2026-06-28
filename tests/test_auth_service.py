"""Tests for auth_service module — password hashing, JWT, permissions, CRUD."""

import hashlib
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.auth_service import (
    _b64,
    make_password,
    check_password,
    create_access_token,
    decode_access_token,
    has_permission,
    get_user_permissions,
    validate_password,
    Permission,
    DEFAULT_ROLE_PERMISSIONS,
)


# ── Password Hashing ──

class TestPasswordHashing:
    def test_make_password_format(self):
        h = make_password("test123", salt="abcd1234", iterations=1000)
        parts = h.split("$")
        assert parts[0] == "pbkdf2_sha256"
        assert parts[1] == "1000"
        assert parts[2] == "abcd1234"
        assert len(parts[3]) > 0

    def test_make_password_deterministic_with_salt(self):
        h1 = make_password("test", salt="fixed", iterations=1000)
        h2 = make_password("test", salt="fixed", iterations=1000)
        assert h1 == h2

    def test_make_password_random_salt(self):
        h1 = make_password("test")
        h2 = make_password("test")
        assert h1 != h2

    def test_check_password_correct(self):
        h = make_password("hello", salt="mysalt", iterations=1000)
        assert check_password("hello", h) is True

    def test_check_password_wrong(self):
        h = make_password("hello", salt="mysalt", iterations=1000)
        assert check_password("wrong", h) is False

    def test_check_password_invalid_format(self):
        assert check_password("test", "bad_format") is False
        assert check_password("test", "") is False
        assert check_password("test", "a$b$c") is False

    def test_check_password_wrong_algo(self):
        h = make_password("test", salt="salt", iterations=1000)
        broken = h.replace("pbkdf2_sha256", "md5")
        assert check_password("test", broken) is False

    def test_b64_no_padding(self):
        assert _b64(b"abc") == "YWJj"

    def test_b64_strips_padding(self):
        import base64
        raw = base64.b64encode(b"test").decode()
        assert "=" not in _b64(b"test")


# ── JWT ──

class TestJWT:
    def test_create_and_decode_token(self):
        token = create_access_token(42, "alice", "admin")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["id"] == 42
        assert payload["username"] == "alice"
        assert payload["role"] == "admin"
        assert payload["exp"] is not None

    def test_decode_expired_token(self):
        from app.services.auth_service import create_access_token
        import jwt as pyjwt
        from app.config import settings

        expire = datetime.now(timezone.utc) - timedelta(hours=1)
        payload = {
            "sub": "1",
            "username": "old",
            "role": "viewer",
            "exp": expire,
            "iat": datetime.now(timezone.utc),
        }
        token = pyjwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        assert decode_access_token(token) is None

    def test_decode_invalid_token(self):
        assert decode_access_token("garbage.token.here") is None

    def test_decode_wrong_secret(self):
        import jwt as pyjwt
        from app.config import settings

        payload = {"sub": "1", "username": "x", "role": "viewer",
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                    "iat": datetime.now(timezone.utc)}
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        assert decode_access_token(token) is None


# ── Permissions ──

class TestPermissions:
    @pytest.mark.asyncio
    async def test_admin_has_all_permissions(self):
        all_perms = [v for k, v in Permission.__dict__.items() if not k.startswith("_")]
        for perm in all_perms:
            assert await has_permission("admin", perm) is True

    @pytest.mark.asyncio
    async def test_viewer_limited_permissions(self):
        assert await has_permission("viewer", Permission.VIEW_STREAM) is True
        assert await has_permission("viewer", Permission.VIEW_ALARM) is True
        assert await has_permission("viewer", Permission.MANAGE_STREAM) is False
        assert await has_permission("viewer", Permission.ADMIN) is False

    @pytest.mark.asyncio
    async def test_annotator_permissions(self):
        assert await has_permission("annotator", Permission.ANNOTATE) is True
        assert await has_permission("annotator", Permission.VIEW_ALARM) is True
        assert await has_permission("annotator", Permission.MANAGE_STREAM) is False

    @pytest.mark.asyncio
    async def test_operator_permissions(self):
        assert await has_permission("operator", Permission.MANAGE_STREAM) is True
        assert await has_permission("operator", Permission.MANAGE_ALARM) is True
        assert await has_permission("operator", Permission.ADMIN) is False

    @pytest.mark.asyncio
    async def test_unknown_role(self):
        assert await has_permission("hacker", Permission.VIEW_STREAM) is False

    @pytest.mark.asyncio
    async def test_get_user_permissions(self):
        perms = await get_user_permissions("admin")
        assert len(perms) == 7

    @pytest.mark.asyncio
    async def test_get_user_permissions_unknown(self):
        assert await get_user_permissions("nonexistent") == []

    def test_default_role_permissions_defined(self):
        assert "admin" in DEFAULT_ROLE_PERMISSIONS
        assert "viewer" in DEFAULT_ROLE_PERMISSIONS
        assert len(DEFAULT_ROLE_PERMISSIONS["admin"]) == 7


# ── Password Validation ──

class TestPasswordValidation:
    def test_valid_password(self):
        ok, msg = validate_password("MyPass123!")
        assert ok is True
        assert msg == ""

    def test_too_short(self):
        ok, msg = validate_password("Ab1!")
        assert ok is False
        assert "8位" in msg

    def test_no_uppercase(self):
        ok, msg = validate_password("mypass123!")
        assert ok is False
        assert "大写" in msg

    def test_no_lowercase(self):
        ok, msg = validate_password("MYPASS123!")
        assert ok is False
        assert "小写" in msg

    def test_no_digit(self):
        ok, msg = validate_password("MyPassWord!")
        assert ok is False
        assert "数字" in msg

    def test_no_special_char(self):
        ok, msg = validate_password("MyPass123")
        assert ok is False
        assert "特殊字符" in msg

    def test_various_valid_passwords(self):
        for pw in ["Abcdef1!", "Test@1234", "P@ssw0rd", "X1y2z3#w"]:
            ok, _ = validate_password(pw)
            assert ok is True, f"Expected valid: {pw}"
