"""Tests for alarm deduplication module."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.alarm_dedup import AlarmDeduplicator


class TestAlarmDeduplicator:
    """Test AlarmDeduplicator class."""

    def test_make_key_with_track_id(self):
        """Test Redis key generation with valid track ID."""
        key = AlarmDeduplicator._make_key("cam-1", "fire", 42)
        assert key == "alarm:cam-1:fire:42"

    def test_make_key_without_tracking(self):
        """Test Redis key generation uses grid when track_id is -1."""
        key = AlarmDeduplicator._make_key("cam-1", "fire", -1, position=(100, 200))
        assert "alarm:cam-1:fire:g" in key

    def test_make_key_no_position(self):
        """Test key with track_id=-1 and no position falls back to generic."""
        key = AlarmDeduplicator._make_key("cam-1", "fire", -1)
        assert key == "alarm:cam-1:fire:-1"

    @pytest.mark.asyncio
    async def test_should_trigger_first_time(self):
        """Test alarm triggers on first occurrence (key not set)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(AlarmDeduplicator, "get_redis", return_value=mock_redis):
            result = await AlarmDeduplicator.should_trigger_alarm("cam-1", "fire", 1)
            assert result is True
            mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_should_not_trigger_in_cooldown(self):
        """Test alarm blocked during cooldown period."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)

        with patch.object(AlarmDeduplicator, "get_redis", return_value=mock_redis):
            result = await AlarmDeduplicator.should_trigger_alarm("cam-1", "fire", 1)
            assert result is False

    @pytest.mark.asyncio
    async def test_redis_error_fail_open(self):
        """Test alarm fires when Redis is down (fail-open)."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Redis down"))

        with patch.object(AlarmDeduplicator, "get_redis", return_value=mock_redis):
            result = await AlarmDeduplicator.should_trigger_alarm("cam-1", "fire", 1)
            assert result is True

    @pytest.mark.asyncio
    async def test_custom_ttl(self):
        """Test alarm with custom TTL."""
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        with patch.object(AlarmDeduplicator, "get_redis", return_value=mock_redis):
            await AlarmDeduplicator.should_trigger_alarm("cam-1", "fire", 1, ttl=60)
            call_kwargs = mock_redis.set.call_args
            assert call_kwargs[1]["ex"] == 60

    @pytest.mark.asyncio
    async def test_get_queue_depth(self):
        """Test queue depth counting."""
        mock_redis = AsyncMock()

        async def fake_scan_iter(**kwargs):
            for k in ["alarm:cam-1:fire:1", "alarm:cam-1:fire:2", "alarm:cam-2:helmet:1"]:
                yield k

        mock_redis.scan_iter = fake_scan_iter

        with patch.object(AlarmDeduplicator, "get_redis", return_value=mock_redis):
            depth = await AlarmDeduplicator.get_queue_depth()
            assert depth == 3

    @pytest.mark.asyncio
    async def test_get_queue_depth_error(self):
        """Test queue depth returns -1 on error."""
        mock_redis = AsyncMock()
        mock_redis.scan_iter = AsyncMock(side_effect=Exception("Redis down"))

        with patch.object(AlarmDeduplicator, "get_redis", return_value=mock_redis):
            depth = await AlarmDeduplicator.get_queue_depth()
            assert depth == -1
