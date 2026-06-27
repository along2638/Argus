"""Tests for stream health recorder module."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.health_recorder import record_stream_health, RECORD_INTERVAL


class TestHealthRecorder:
    """Test record_stream_health function."""

    @pytest.mark.asyncio
    async def test_records_snapshots(self):
        """Test that health snapshots are recorded for active streams."""
        mock_manager = MagicMock()
        mock_manager.get_streams_info.return_value = [
            {"stream_id": "cam-1", "status": "running", "fps": 15.0, "error_message": ""},
        ]

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()

        with patch("app.core.health_recorder.async_session") as mock_ctx, \
             patch("app.core.health_recorder.RECORD_INTERVAL", 0.05):
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            task = asyncio.create_task(record_stream_health(mock_manager))
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_session.add.assert_called()
            recorded = mock_session.add.call_args_list[0][0][0]
            assert recorded.stream_id == "cam-1"
            assert recorded.status == "running"

    @pytest.mark.asyncio
    async def test_skips_when_no_streams(self):
        """Test no DB writes when no active streams."""
        mock_manager = MagicMock()
        mock_manager.get_streams_info.return_value = []

        with patch("app.core.health_recorder.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock()
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            task = asyncio.create_task(record_stream_health(mock_manager))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            # Should not have entered a session
            mock_ctx.return_value.__aenter__.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_db_error(self):
        """Test recorder continues after database error."""
        mock_manager = MagicMock()
        mock_manager.get_streams_info.return_value = [
            {"stream_id": "cam-1", "status": "running", "fps": 10.0, "error_message": ""},
        ]

        with patch("app.core.health_recorder.async_session") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))

            task = asyncio.create_task(record_stream_health(mock_manager))
            await asyncio.sleep(0.1)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            # Should not crash

    def test_record_interval(self):
        """Test that record interval is defined."""
        assert RECORD_INTERVAL > 0
