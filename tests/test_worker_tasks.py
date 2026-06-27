"""Tests for ARQ worker tasks module."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.worker_tasks import (
    enqueue_alarm_task,
    save_alarm,
    check_queue_depth,
    WorkerSettings,
)


def make_mock_ctx():
    """Create a mock ARQ context with a mock db pool."""
    ctx = {}

    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.lastrowid = 42

    @asynccontextmanager
    async def mock_cursor_ctx():
        yield mock_cursor

    mock_conn = AsyncMock()
    mock_conn.cursor = mock_cursor_ctx

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.acquire = mock_acquire
    mock_pool.close = AsyncMock()

    ctx["db_pool"] = mock_pool
    return ctx, mock_cursor


class TestEnqueueAlarmTask:
    """Test enqueue_alarm_task function."""

    @pytest.mark.asyncio
    async def test_enqueue_success(self):
        """Test successful task enqueue."""
        mock_pool = AsyncMock()
        mock_job = MagicMock()
        mock_job.job_id = "test-job-123"
        mock_pool.enqueue_job = AsyncMock(return_value=mock_job)

        with patch("app.services.worker_tasks.get_arq_pool", return_value=mock_pool):
            job_id = await enqueue_alarm_task(
                stream_url="rtsp://test.com",
                stream_id="test-stream",
                alarm_type="no-helmet",
                confidence=0.85,
                minio_key="2024/01/01/test.jpg",
                track_id=1,
            )

            assert job_id == "test-job-123"
            mock_pool.enqueue_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_enqueue_failure(self):
        """Test task enqueue failure."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(return_value=None)

        with patch("app.services.worker_tasks.get_arq_pool", return_value=mock_pool):
            job_id = await enqueue_alarm_task(
                stream_url="rtsp://test.com",
                stream_id="test-stream",
                alarm_type="no-helmet",
                confidence=0.85,
                minio_key="2024/01/01/test.jpg",
                track_id=1,
            )

            assert job_id is None

    @pytest.mark.asyncio
    async def test_enqueue_exception(self):
        """Test task enqueue with exception."""
        mock_pool = AsyncMock()
        mock_pool.enqueue_job = AsyncMock(side_effect=Exception("Redis error"))

        with patch("app.services.worker_tasks.get_arq_pool", return_value=mock_pool):
            job_id = await enqueue_alarm_task(
                stream_url="rtsp://test.com",
                stream_id="test-stream",
                alarm_type="no-helmet",
                confidence=0.85,
                minio_key="2024/01/01/test.jpg",
                track_id=1,
            )

            assert job_id is None


class TestSaveAlarm:
    """Test save_alarm function."""

    @pytest.mark.asyncio
    async def test_save_success(self):
        """Test successful alarm save."""
        ctx, mock_cursor = make_mock_ctx()

        result = await save_alarm(
            ctx,
            stream_url="rtsp://test.com",
            stream_id="test-stream",
            alarm_type="no-helmet",
            confidence=0.85,
            minio_key="2024/01/01/test.jpg",
            track_id=1,
        )

        assert result is True
        mock_cursor.execute.assert_called_once()
        # Verify SQL contains INSERT
        call_args = mock_cursor.execute.call_args
        assert "INSERT" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_save_success_creates_pool(self):
        """Test save_alarm creates pool when not in ctx."""
        ctx = {}  # Empty ctx, no db_pool

        mock_cursor = AsyncMock()
        mock_cursor.execute = AsyncMock()
        mock_cursor.lastrowid = 99

        @asynccontextmanager
        async def mock_cursor_ctx():
            yield mock_cursor

        mock_conn = AsyncMock()
        mock_conn.cursor = mock_cursor_ctx

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = mock_acquire

        with patch("app.services.worker_tasks.aiomysql") as mock_aiomysql:
            mock_aiomysql.create_pool = AsyncMock(return_value=mock_pool)

            result = await save_alarm(
                ctx,
                stream_url="rtsp://test.com",
                stream_id="test-stream",
                alarm_type="no-helmet",
                confidence=0.85,
                minio_key="2024/01/01/test.jpg",
                track_id=1,
            )

            assert result is True
            assert "db_pool" in ctx
            mock_aiomysql.create_pool.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_failure_raises(self):
        """Test alarm save failure raises exception for ARQ retry."""
        ctx, mock_cursor = make_mock_ctx()
        mock_cursor.execute = AsyncMock(side_effect=Exception("Database error"))

        with pytest.raises(Exception, match="Database error"):
            await save_alarm(
                ctx,
                stream_url="rtsp://test.com",
                stream_id="test-stream",
                alarm_type="no-helmet",
                confidence=0.85,
                minio_key="2024/01/01/test.jpg",
                track_id=1,
            )


class TestCheckQueueDepth:
    """Test check_queue_depth function."""

    @pytest.mark.asyncio
    async def test_check_normal(self):
        """Test queue depth check with normal depth."""
        mock_ctx = MagicMock()
        mock_pool = AsyncMock()
        mock_pool.zcard = AsyncMock(return_value=50)

        with patch("app.services.worker_tasks.get_arq_pool", return_value=mock_pool), \
             patch("app.services.worker_tasks.settings") as mock_settings:
            mock_settings.ARQ_QUEUE_WARNING_THRESHOLD = 100

            # Should not raise
            await check_queue_depth(mock_ctx)

    @pytest.mark.asyncio
    async def test_check_high_depth(self):
        """Test queue depth check with high depth."""
        mock_ctx = MagicMock()
        mock_pool = AsyncMock()
        mock_pool.zcard = AsyncMock(return_value=150)

        with patch("app.services.worker_tasks.get_arq_pool", return_value=mock_pool), \
             patch("app.services.worker_tasks.settings") as mock_settings:
            mock_settings.ARQ_QUEUE_WARNING_THRESHOLD = 100

            # Should log warning but not raise
            await check_queue_depth(mock_ctx)

    @pytest.mark.asyncio
    async def test_check_error(self):
        """Test queue depth check with error."""
        mock_ctx = MagicMock()
        mock_pool = AsyncMock()
        mock_pool.zcard = AsyncMock(side_effect=Exception("Redis error"))

        with patch("app.services.worker_tasks.get_arq_pool", return_value=mock_pool):
            # Should handle error gracefully
            await check_queue_depth(mock_ctx)


class TestWorkerSettings:
    """Test WorkerSettings class."""

    def test_functions(self):
        """Test worker functions list."""
        assert save_alarm in WorkerSettings.functions

    def test_max_jobs(self):
        """Test max jobs setting."""
        assert WorkerSettings.max_jobs == 20

    def test_retry_settings(self):
        """Test retry settings."""
        assert WorkerSettings.retry_jobs is True
        assert WorkerSettings.max_tries == 3
        assert WorkerSettings.retry_delay == 5
