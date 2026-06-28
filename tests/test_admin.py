"""Tests for admin API endpoints."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager

from app.services.operation_log_service import write_log, get_logs, delete_logs


def _mock_ctx(scalar_return=None, scalars_return=None):
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.scalar = AsyncMock(return_value=scalar_return)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = scalars_return or []
    mock_session.execute = AsyncMock(return_value=mock_result)

    @asynccontextmanager
    async def ctx():
        yield mock_session

    return ctx(), mock_session


class TestOperationLogService:
    """Test operation log service functions."""

    @pytest.mark.asyncio
    async def test_write_log_success(self):
        ctx, mock_session = _mock_ctx()
        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            await write_log(action="login", username="admin", detail="test")
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_log_db_error(self):
        ctx, mock_session = _mock_ctx()
        mock_session.commit = AsyncMock(side_effect=Exception("DB down"))
        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            await write_log(action="login")  # Should not raise

    @pytest.mark.asyncio
    async def test_get_logs_empty(self):
        ctx, mock_session = _mock_ctx(scalar_return=0, scalars_return=[])
        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            result = await get_logs()
            assert result["total"] == 0
            assert result["items"] == []

    @pytest.mark.asyncio
    async def test_get_logs_with_data(self):
        mock_log = MagicMock()
        mock_log.id = 1
        mock_log.user_id = 10
        mock_log.username = "admin"
        mock_log.action = "login"
        mock_log.target_type = "api"
        mock_log.target_id = "/login"
        mock_log.detail = None
        mock_log.ip_address = "127.0.0.1"
        mock_log.create_time = datetime(2026, 1, 1) if 'datetime' in dir() else None

        ctx, mock_session = _mock_ctx(scalar_return=1, scalars_return=[mock_log])
        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            result = await get_logs()
            assert result["total"] == 1
            assert len(result["items"]) == 1

    @pytest.mark.asyncio
    async def test_delete_logs_all(self):
        ctx, mock_session = _mock_ctx(scalar_return=10)
        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            count = await delete_logs()
            assert count == 10

    @pytest.mark.asyncio
    async def test_delete_logs_before_date(self):
        ctx, mock_session = _mock_ctx(scalar_return=5)
        with patch("app.services.operation_log_service.async_session", return_value=ctx):
            count = await delete_logs(before_date="2026-01-01")
            assert count == 5
