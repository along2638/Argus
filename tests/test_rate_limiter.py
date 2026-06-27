"""Tests for rate limiter module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.rate_limiter import RateLimiter


class TestRateLimiter:
    """Test RateLimiter class."""

    @pytest.mark.asyncio
    async def test_allowed_under_limit(self):
        """Test request is allowed when under the limit."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()

        with patch.object(RateLimiter, "_get_redis", return_value=mock_redis):
            allowed, retry_after = await RateLimiter.is_allowed("test_key", max_requests=5, window_seconds=60)

            assert allowed is True
            assert retry_after == 0
            mock_redis.incr.assert_called_once_with("ratelimit:test_key")
            mock_redis.expire.assert_called_once_with("ratelimit:test_key", 60)

    @pytest.mark.asyncio
    async def test_allowed_at_limit(self):
        """Test request is allowed when exactly at the limit."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()

        with patch.object(RateLimiter, "_get_redis", return_value=mock_redis):
            allowed, retry_after = await RateLimiter.is_allowed("test_key", max_requests=5, window_seconds=60)

            assert allowed is True
            assert retry_after == 0

    @pytest.mark.asyncio
    async def test_rejected_over_limit(self):
        """Test request is rejected when over the limit."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=6)
        mock_redis.ttl = AsyncMock(return_value=45)

        with patch.object(RateLimiter, "_get_redis", return_value=mock_redis):
            allowed, retry_after = await RateLimiter.is_allowed("test_key", max_requests=5, window_seconds=60)

            assert allowed is False
            assert retry_after == 45

    @pytest.mark.asyncio
    async def test_redis_error_fail_open(self):
        """Test that Redis errors allow the request (fail-open)."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(side_effect=Exception("Redis down"))

        with patch.object(RateLimiter, "_get_redis", return_value=mock_redis):
            allowed, retry_after = await RateLimiter.is_allowed("test_key", max_requests=5, window_seconds=60)

            assert allowed is True
            assert retry_after == 0

    @pytest.mark.asyncio
    async def test_no_EXPIRE_on_subsequent_requests(self):
        """Test that TTL is not reset on subsequent requests in the same window."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=3)
        # Second call should not trigger expire (key already has TTL)

        with patch.object(RateLimiter, "_get_redis", return_value=mock_redis):
            allowed, _ = await RateLimiter.is_allowed("test_key", max_requests=5, window_seconds=60)

            assert allowed is True
            # expire should NOT be called when incr returns > 1
            mock_redis.expire.assert_not_called()

    @pytest.mark.asyncio
    async def test_retry_after_at_least_1(self):
        """Test retry_after is at least 1 even if TTL returns 0."""
        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=10)
        mock_redis.ttl = AsyncMock(return_value=0)

        with patch.object(RateLimiter, "_get_redis", return_value=mock_redis):
            allowed, retry_after = await RateLimiter.is_allowed("test_key", max_requests=5, window_seconds=60)

            assert allowed is False
            assert retry_after >= 1
