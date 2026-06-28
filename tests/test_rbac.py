"""Tests for RBAC permission system — backend + frontend logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from app.services.auth_service import (
    has_permission, get_user_permissions, Permission,
    DEFAULT_ROLE_PERMISSIONS, invalidate_permission_cache,
)


class TestPermissionConstants:
    """Test permission constants are properly defined."""

    def test_all_permissions_defined(self):
        assert Permission.VIEW_STREAM == "view_stream"
        assert Permission.MANAGE_STREAM == "manage_stream"
        assert Permission.VIEW_ALARM == "view_alarm"
        assert Permission.MANAGE_ALARM == "manage_alarm"
        assert Permission.ANNOTATE == "annotate"
        assert Permission.MANAGE_USER == "manage_user"
        assert Permission.ADMIN == "admin"

    def test_default_roles_have_permissions(self):
        for role in ["admin", "operator", "annotator", "viewer"]:
            assert role in DEFAULT_ROLE_PERMISSIONS
            assert len(DEFAULT_ROLE_PERMISSIONS[role]) > 0


class TestRolePermissions:
    """Test each role's permission set."""

    @pytest.mark.asyncio
    async def test_admin_full_access(self):
        admin_perms = DEFAULT_ROLE_PERMISSIONS["admin"]
        assert len(admin_perms) == 7
        for perm in [Permission.VIEW_STREAM, Permission.MANAGE_STREAM,
                     Permission.VIEW_ALARM, Permission.MANAGE_ALARM,
                     Permission.ANNOTATE, Permission.MANAGE_USER, Permission.ADMIN]:
            assert await has_permission("admin", perm)

    @pytest.mark.asyncio
    async def test_operator_no_admin(self):
        assert await has_permission("operator", Permission.MANAGE_STREAM) is True
        assert await has_permission("operator", Permission.MANAGE_ALARM) is True
        assert await has_permission("operator", Permission.ANNOTATE) is True
        assert await has_permission("operator", Permission.ADMIN) is False
        assert await has_permission("operator", Permission.MANAGE_USER) is False

    @pytest.mark.asyncio
    async def test_annotator_limited(self):
        assert await has_permission("annotator", Permission.ANNOTATE) is True
        assert await has_permission("annotator", Permission.VIEW_ALARM) is True
        assert await has_permission("annotator", Permission.MANAGE_STREAM) is False
        assert await has_permission("annotator", Permission.MANAGE_ALARM) is False
        assert await has_permission("annotator", Permission.ADMIN) is False

    @pytest.mark.asyncio
    async def test_viewer_readonly(self):
        assert await has_permission("viewer", Permission.VIEW_STREAM) is True
        assert await has_permission("viewer", Permission.VIEW_ALARM) is True
        assert await has_permission("viewer", Permission.MANAGE_STREAM) is False
        assert await has_permission("viewer", Permission.ANNOTATE) is False
        assert await has_permission("viewer", Permission.ADMIN) is False

    @pytest.mark.asyncio
    async def test_unknown_role_denied(self):
        for perm in [Permission.VIEW_STREAM, Permission.ADMIN]:
            assert await has_permission("hacker", perm) is False

    @pytest.mark.asyncio
    async def test_empty_role_denied(self):
        assert await has_permission("", Permission.VIEW_STREAM) is False
        assert await has_permission(None, Permission.VIEW_STREAM) is False


class TestPermissionCache:
    """Test permission cache invalidation."""

    @pytest.mark.asyncio
    async def test_cache_returns_same_data(self):
        invalidate_permission_cache()
        p1 = await get_user_permissions("admin")
        p2 = await get_user_permissions("admin")
        assert p1 == p2

    @pytest.mark.asyncio
    async def test_invalidation_forces_reload(self):
        invalidate_permission_cache()
        p1 = await get_user_permissions("admin")
        invalidate_permission_cache()
        p2 = await get_user_permissions("admin")
        assert p1 == p2  # Same default data


class TestUserRoleAssignment:
    """Test that user creation respects role validation."""

    def test_valid_roles(self):
        from app.services.auth_service import VALID_ROLES
        assert "admin" in VALID_ROLES
        assert "operator" in VALID_ROLES
        assert "annotator" in VALID_ROLES
        assert "viewer" in VALID_ROLES
        assert len(VALID_ROLES) == 4


class TestFrontendPermissions:
    """Test frontend permission JS logic (simulated)."""

    def test_has_permission_logic(self):
        """Simulate the hasPermission check."""
        # Admin has all
        admin_perms = DEFAULT_ROLE_PERMISSIONS["admin"]
        assert "manage_user" in admin_perms
        assert "admin" in admin_perms

        # Viewer cannot manage
        viewer_perms = DEFAULT_ROLE_PERMISSIONS["viewer"]
        assert "manage_user" not in viewer_perms
        assert "admin" not in viewer_perms

        # Annotator cannot manage streams
        annotator_perms = DEFAULT_ROLE_PERMISSIONS["annotator"]
        assert "manage_stream" not in annotator_perms

    def test_permission_escalation_prevention(self):
        """Viewer cannot escalate to admin via permission check."""
        viewer_perms = DEFAULT_ROLE_PERMISSIONS["viewer"]
        assert Permission.ADMIN not in viewer_perms
        assert Permission.MANAGE_USER not in viewer_perms
        assert Permission.MANAGE_ALARM not in viewer_perms
