"""Tests for schedule checker module."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.schedule_checker import _matches_cron


class TestCronMatcher:
    """Test _matches_cron function."""

    def test_all_wildcards(self):
        """Test * * * * * matches everything."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("* * * * *", now) is True

    def test_exact_minute(self):
        """Test exact minute match."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("30 * * * *", now) is True
        assert _matches_cron("29 * * * *", now) is False

    def test_exact_hour(self):
        """Test exact hour match."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("* 14 * * *", now) is True
        assert _matches_cron("* 15 * * *", now) is False

    def test_range(self):
        """Test range like 8-18."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("* 8-18 * * *", now) is True
        assert _matches_cron("* 8-12 * * *", now) is False

    def test_step_wildcard(self):
        """Test */5 step with wildcard."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("*/5 * * * *", now) is True
        assert _matches_cron("*/10 * * * *", now) is True

    def test_step_base(self):
        """Test 10/5 step from base."""
        now = datetime(2026, 6, 27, 14, 25)
        assert _matches_cron("10/5 * * * *", now) is True
        now2 = datetime(2026, 6, 27, 14, 27)
        assert _matches_cron("10/5 * * * *", now2) is False

    def test_list(self):
        """Test comma-separated list."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("30,45 * * * *", now) is True
        assert _matches_cron("15,45 * * * *", now) is False

    def test_weekday(self):
        """Test weekday (0=Sunday)."""
        # 2026-06-27 is Saturday (isoweekday=6, cron weekday=6)
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("* * * * 6", now) is True
        assert _matches_cron("* * * * 1", now) is False

    def test_invalid_format(self):
        """Test invalid cron expression."""
        now = datetime(2026, 6, 27, 14, 30)
        assert _matches_cron("invalid", now) is False
        assert _matches_cron("* * *", now) is False

    def test_workday_hours(self):
        """Test Mon-Fri 8-18."""
        # Saturday
        now_sat = datetime(2026, 6, 27, 10, 0)  # Saturday
        assert _matches_cron("* 8-18 * * 1-5", now_sat) is False
        # Monday
        now_mon = datetime(2026, 6, 29, 10, 0)  # Monday
        assert _matches_cron("* 8-18 * * 1-5", now_mon) is True
