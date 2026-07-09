"""Tests for alarm severity escalation module."""

from unittest.mock import AsyncMock, MagicMock, patch
import time

import pytest

from app.core.alarm_severity import compute_severity


class TestComputeSeverity:
    """Test compute_severity function."""

    @pytest.mark.asyncio
    async def test_normal_when_few_alarms(self):
        """Test severity is normal when alarm count is below threshold."""
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch("app.core.alarm_severity.alarm_dedup") as mock_dedup:
            mock_dedup.get_redis = AsyncMock(return_value=mock_redis)
            result = await compute_severity("cam-1", "fire")
            assert result == "normal"

    @pytest.mark.asyncio
    async def test_important_when_threshold_met(self):
        """Test severity escalates to important at threshold."""
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=3)
        mock_redis.expire = AsyncMock()

        with patch("app.core.alarm_severity.alarm_dedup") as mock_dedup:
            mock_dedup.get_redis = AsyncMock(return_value=mock_redis)
            result = await compute_severity("cam-1", "fire")
            assert result == "important"

    @pytest.mark.asyncio
    async def test_critical_when_high_frequency(self):
        """Test severity escalates to critical at high frequency."""
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()

        with patch("app.core.alarm_severity.alarm_dedup") as mock_dedup:
            mock_dedup.get_redis = AsyncMock(return_value=mock_redis)
            result = await compute_severity("cam-1", "fire")
            assert result == "critical"

    @pytest.mark.asyncio
    async def test_zero_alarms_is_normal(self):
        """Test zero historical alarms results in normal severity."""
        mock_redis = AsyncMock()
        mock_redis.zadd = AsyncMock()
        mock_redis.zremrangebyscore = AsyncMock()
        mock_redis.zcard = AsyncMock(return_value=0)
        mock_redis.expire = AsyncMock()

        with patch("app.core.alarm_severity.alarm_dedup") as mock_dedup:
            mock_dedup.get_redis = AsyncMock(return_value=mock_redis)
            result = await compute_severity("cam-1", "helmet")
            assert result == "normal"

    @pytest.mark.asyncio
    async def test_db_error_returns_normal(self):
        """Test that Redis errors default to normal severity."""
        with patch("app.core.alarm_severity.alarm_dedup") as mock_dedup:
            mock_dedup.get_redis = AsyncMock(side_effect=Exception("Redis down"))
            result = await compute_severity("cam-1", "fire")
            assert result == "normal"
