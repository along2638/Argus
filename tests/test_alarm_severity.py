"""Tests for alarm severity escalation module."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.alarm_severity import compute_severity


class TestComputeSeverity:
    """Test compute_severity function."""

    @pytest.mark.asyncio
    async def test_normal_when_few_alarms(self):
        """Test severity is normal when alarm count is below threshold."""
        mock_session = AsyncMock()
        mock_scalar = AsyncMock(return_value=1)

        with patch("app.core.alarm_severity.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.scalar = mock_scalar

            result = await compute_severity("cam-1", "fire")
            assert result == "normal"

    @pytest.mark.asyncio
    async def test_important_when_threshold_met(self):
        """Test severity escalates to important at threshold."""
        mock_session = AsyncMock()
        mock_scalar = AsyncMock(return_value=3)

        with patch("app.core.alarm_severity.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.scalar = mock_scalar

            result = await compute_severity("cam-1", "fire")
            assert result == "important"

    @pytest.mark.asyncio
    async def test_critical_when_high_frequency(self):
        """Test severity escalates to critical at high frequency."""
        mock_session = AsyncMock()
        mock_scalar = AsyncMock(return_value=5)

        with patch("app.core.alarm_severity.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.scalar = mock_scalar

            result = await compute_severity("cam-1", "fire")
            assert result == "critical"

    @pytest.mark.asyncio
    async def test_zero_alarms_is_normal(self):
        """Test zero historical alarms results in normal severity."""
        mock_session = AsyncMock()
        mock_scalar = AsyncMock(return_value=0)

        with patch("app.core.alarm_severity.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session.scalar = mock_scalar

            result = await compute_severity("cam-1", "helmet")
            assert result == "normal"

    @pytest.mark.asyncio
    async def test_db_error_returns_normal(self):
        """Test that database errors default to normal severity."""
        with patch("app.core.alarm_severity.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))

            result = await compute_severity("cam-1", "fire")
            assert result == "normal"
