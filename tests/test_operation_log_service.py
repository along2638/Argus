"""Tests for operation_log_service module."""

from datetime import datetime
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.operation_log_service import write_log, get_logs, delete_logs


def _mock_ctx(scalar_return=None, scalars_return=None):
    """Create a mock for async_session context manager."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.scalar = AsyncMock(return_value=scalar_return)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_return or []
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def ctx():
        yield mock_session

    return ctx(), mock_session

    return ctx(), mock_session


class TestWriteLog:
    @pytest.mark.asyncio
    async def test_write_log_success(self):
        """Test successful log write."""
        ctx, mock_session = _mock_ctx()

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            await write_log(
                action="login",
                user_id=1,
                username="admin",
                target_type="api",
                target_id="/login",
                detail={"ip": "127.0.0.1"},
                ip_address="127.0.0.1",
            )

            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()
            log_obj = mock_session.add.call_args[0][0]
            assert log_obj.action == "login"
            assert log_obj.username == "admin"

    @pytest.mark.asyncio
    async def test_write_log_minimal(self):
        """Test log write with minimal params."""
        ctx, mock_session = _mock_ctx()

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            await write_log(action="test_action")

            mock_session.add.assert_called_once()
            log_obj = mock_session.add.call_args[0][0]
            assert log_obj.action == "test_action"
            assert log_obj.user_id is None

    @pytest.mark.asyncio
    async def test_write_log_db_error(self):
        """Test log write handles DB errors gracefully."""
        ctx, mock_session = _mock_ctx()
        mock_session.commit = AsyncMock(side_effect=Exception("DB down"))

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            # Should not raise
            await write_log(action="fail_test")


class TestGetLogs:
    @pytest.mark.asyncio
    async def test_get_logs_empty(self):
        """Test get_logs with no results."""
        ctx, mock_session = _mock_ctx(scalar_return=0, scalars_return=[])

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            result = await get_logs()

            assert result["total"] == 0
            assert result["items"] == []

    @pytest.mark.asyncio
    async def test_get_logs_with_results(self):
        """Test get_logs returns formatted items."""
        mock_log = MagicMock()
        mock_log.id = 1
        mock_log.user_id = 10
        mock_log.username = "admin"
        mock_log.action = "login"
        mock_log.target_type = "api"
        mock_log.target_id = "/login"
        mock_log.detail = None
        mock_log.ip_address = "127.0.0.1"
        mock_log.create_time = datetime(2026, 1, 1, 12, 0, 0)

        ctx, mock_session = _mock_ctx(scalar_return=1, scalars_return=[mock_log])

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            result = await get_logs()

            assert result["total"] == 1
            assert len(result["items"]) == 1
            assert result["items"][0]["action"] == "login"

    @pytest.mark.asyncio
    async def test_get_logs_filter_action(self):
        """Test get_logs with action filter."""
        ctx, mock_session = _mock_ctx(scalar_return=5)

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            result = await get_logs(action="login")
            assert result["total"] == 5

    @pytest.mark.asyncio
    async def test_get_logs_filter_username(self):
        """Test get_logs with username filter."""
        ctx, mock_session = _mock_ctx(scalar_return=3)

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            result = await get_logs(username="admin")
            assert result["total"] == 3


class TestDeleteLogs:
    @pytest.mark.asyncio
    async def test_delete_all_logs(self):
        """Test deleting all logs."""
        ctx, mock_session = _mock_ctx(scalar_return=10)

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            count = await delete_logs()
            assert count == 10
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_logs_before_date(self):
        """Test deleting logs before a specific date."""
        ctx, mock_session = _mock_ctx(scalar_return=5)

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            count = await delete_logs(before_date="2026-01-01")
            assert count == 5

    @pytest.mark.asyncio
    async def test_delete_logs_empty(self):
        """Test deleting when no logs exist."""
        ctx, mock_session = _mock_ctx(scalar_return=0)

        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            count = await delete_logs()
            assert count == 0
