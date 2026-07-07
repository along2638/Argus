"""Tests for stream processor module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import numpy as np

from app.core.stream_processor import StreamProcessor, StreamManager


@pytest.fixture
def mock_frame():
    """Create a mock frame."""
    return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)


@pytest.fixture
def stream_manager():
    """Create a fresh StreamManager instance."""
    StreamManager._instance = None
    return StreamManager()


class TestStreamProcessor:
    """Test StreamProcessor class."""

    def test_init(self):
        """Test processor initialization."""
        processor = StreamProcessor("test-stream", "rtsp://test.com/stream")
        assert processor.stream_id == "test-stream"
        assert processor.stream_url == "rtsp://test.com/stream"
        assert processor._running is False

    def test_init_with_alarm_types(self):
        """Test processor initialization with custom alarm types."""
        processor = StreamProcessor("test-stream", "rtsp://test.com/stream", alarm_types=["helmet"])
        assert processor.alarm_types == ["helmet"]
        assert "helmet" in processor._models_to_use

    def test_init_models_to_use(self):
        """Test that alarm types map to correct models."""
        processor = StreamProcessor(
            "test-stream", "rtsp://test.com/stream",
            alarm_types=["helmet", "fire", "intrusion"],
        )
        assert "helmet" in processor._models_to_use
        assert "fire_smoke" in processor._models_to_use
        assert "general" in processor._models_to_use

    @pytest.mark.asyncio
    async def test_start_stop(self):
        """Test starting and stopping a processor."""
        processor = StreamProcessor("test-stream", "rtsp://test.com/stream")

        with patch.object(processor, "_process_loop", new_callable=AsyncMock):
            await processor.start()
            assert processor._running is True
            assert processor._task is not None

            await processor.stop()
            assert processor._running is False

    @pytest.mark.asyncio
    async def test_start_already_running(self):
        """Test starting a processor that's already running."""
        processor = StreamProcessor("test-stream", "rtsp://test.com/stream")
        processor._running = True

        # Should not raise, just return
        await processor.start()

    @pytest.mark.asyncio
    async def test_process_frame_with_detections(self, mock_frame):
        """Test frame processing with mock detections — new logic: person - helmet = no-helmet."""
        processor = StreamProcessor(
            "test-stream", "rtsp://test.com/stream",
            alarm_types=["helmet"],
        )

        # Mock unified detection result
        mock_result = {
            "person_boxes": [(100, 50, 300, 400, 0.9)],
            "helmet_boxes": [],
            "matched": [],
            "no_helmet": [{"person": (100, 50, 300, 400, 0.9)}],
            "inference_ms": 18.0,
        }

        with patch("app.core.stream_processor.detector") as mock_detector, \
             patch("app.core.stream_processor.alarm_dedup") as mock_dedup, \
             patch("app.core.stream_processor.minio_service") as mock_minio, \
             patch("app.core.stream_processor.enqueue_alarm_task") as mock_enqueue:

            mock_detector.detect_helmet_combined = AsyncMock(return_value=mock_result)
            mock_detector.get_class_name = MagicMock(return_value="person")
            mock_dedup.should_trigger_alarm = AsyncMock(return_value=True)
            mock_minio.upload_image = AsyncMock(return_value="2024/01/01/test-stream/test.jpg")
            mock_enqueue.return_value = AsyncMock()

            await processor._process_frame(mock_frame)

            # Verify unified method was called
            mock_detector.detect_helmet_combined.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_frame_no_detections(self, mock_frame):
        """Test frame processing with no detections."""
        processor = StreamProcessor(
            "test-stream", "rtsp://test.com/stream",
            alarm_types=["helmet"],
        )

        mock_empty = MagicMock()
        mock_empty.__len__ = MagicMock(return_value=0)

        with patch("app.core.stream_processor.detector") as mock_detector, \
             patch("app.core.stream_processor.alarm_dedup") as mock_dedup:

            async def fake_detect(frame, model_name, confidence_threshold=None):
                return (mock_empty, 10.0)

            mock_detector.detect_with_model = AsyncMock(side_effect=fake_detect)
            mock_dedup.should_trigger_alarm = AsyncMock(return_value=False)

            # Should not raise
            await processor._process_frame(mock_frame)

    def test_get_alarm_type(self):
        """Test alarm type mapping from model and class name."""
        processor = StreamProcessor("test-stream", "rtsp://test.com/stream")

        # Helmet model
        assert processor._get_alarm_type("helmet", "no-helmet") == "helmet"
        assert processor._get_alarm_type("helmet", "helmet") == "helmet"
        assert processor._get_alarm_type("helmet", "person") is None

        # Fire/smoke model
        assert processor._get_alarm_type("fire_smoke", "fire") == "fire"
        assert processor._get_alarm_type("fire_smoke", "smoke") == "fire"
        assert processor._get_alarm_type("fire_smoke", "person") is None

        # General model
        assert processor._get_alarm_type("general", "person") == "intrusion"
        assert processor._get_alarm_type("general", "bird") == "intrusion"
        assert processor._get_alarm_type("general", "cat") == "intrusion"
        assert processor._get_alarm_type("general", "car") is None

        # Unknown model
        assert processor._get_alarm_type("unknown", "person") is None


class TestStreamManager:
    """Test StreamManager class."""

    @pytest.mark.asyncio
    async def test_start_stream(self, stream_manager):
        """Test starting a stream."""
        with patch.object(StreamProcessor, "start", new_callable=AsyncMock):
            result = await stream_manager.start_stream("test", "rtsp://test.com", validate=False)
            assert result["success"] is True
            assert stream_manager.active_streams == 1
            assert "test" in stream_manager.stream_ids

    @pytest.mark.asyncio
    async def test_start_duplicate_stream(self, stream_manager):
        """Test starting a duplicate stream."""
        with patch.object(StreamProcessor, "start", new_callable=AsyncMock):
            await stream_manager.start_stream("test", "rtsp://test.com", validate=False)
            result = await stream_manager.start_stream("test", "rtsp://test.com", validate=False)
            assert result["success"] is False
            assert "已存在" in result["message"]

    @pytest.mark.asyncio
    async def test_max_streams_limit(self, stream_manager):
        """Test max streams limit."""
        with patch.object(StreamProcessor, "start", new_callable=AsyncMock), \
             patch("app.core.stream_processor.settings") as mock_settings:
            mock_settings.MAX_CONCURRENT_STREAMS = 2

            await stream_manager.start_stream("stream1", "rtsp://test1.com", validate=False)
            await stream_manager.start_stream("stream2", "rtsp://test2.com", validate=False)
            result = await stream_manager.start_stream("stream3", "rtsp://test3.com", validate=False)
            assert result["success"] is False
            assert "最大并发" in result["message"]

    @pytest.mark.asyncio
    async def test_stop_stream(self, stream_manager):
        """Test stopping a stream."""
        with patch.object(StreamProcessor, "start", new_callable=AsyncMock), \
             patch.object(StreamProcessor, "stop", new_callable=AsyncMock):
            await stream_manager.start_stream("test", "rtsp://test.com", validate=False)
            result = await stream_manager.stop_stream("test")
            assert result is True
            assert stream_manager.active_streams == 0

    @pytest.mark.asyncio
    async def test_stop_nonexistent_stream(self, stream_manager):
        """Test stopping a nonexistent stream."""
        result = await stream_manager.stop_stream("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_all(self, stream_manager):
        """Test stopping all streams."""
        with patch.object(StreamProcessor, "start", new_callable=AsyncMock), \
             patch.object(StreamProcessor, "stop", new_callable=AsyncMock):
            await stream_manager.start_stream("stream1", "rtsp://test1.com", validate=False)
            await stream_manager.start_stream("stream2", "rtsp://test2.com", validate=False)

            await stream_manager.stop_all()
            assert stream_manager.active_streams == 0

    @pytest.mark.asyncio
    async def test_validate_stream_failure(self, stream_manager):
        """Test stream validation failure."""
        with patch.object(stream_manager, "_validate_stream", new_callable=AsyncMock) as mock_validate:
            mock_validate.return_value = (False, "连接超时")

            result = await stream_manager.start_stream("test", "rtsp://invalid.com", validate=True)
            assert result["success"] is False
            assert "验证失败" in result["message"]


class TestStreamProcessorROI:
    """Test ROI (Region of Interest) support."""

    def test_init_with_roi(self):
        """Test processor with ROI coordinates."""
        processor = StreamProcessor("test", "rtsp://test.com", roi=(100, 50, 400, 300))
        assert processor._roi == (100, 50, 400, 300)

    def test_init_without_roi(self):
        """Test processor without ROI (full frame)."""
        processor = StreamProcessor("test", "rtsp://test.com")
        assert processor._roi is None

    @pytest.mark.asyncio
    async def test_process_frame_with_roi(self, mock_frame):
        """Test frame processing with ROI crops the frame before detection."""
        processor = StreamProcessor(
            "test", "rtsp://test.com",
            alarm_types=["helmet"],
            roi=(10, 10, 100, 100),
        )

        mock_result = {"person_boxes": [], "helmet_boxes": [], "matched": [], "no_helmet": [], "inference_ms": 10.0}

        with patch("app.core.stream_processor.detector") as mock_detector:
            mock_detector.detect_helmet_combined = AsyncMock(return_value=mock_result)

            await processor._process_frame(mock_frame)

            # Verify detector was called with cropped frame
            call_args = mock_detector.detect_helmet_combined.call_args_list[0]
            cropped_frame = call_args[0][0]
            assert cropped_frame.shape[0] <= mock_frame.shape[0]
            assert cropped_frame.shape[1] <= mock_frame.shape[1]

    @pytest.mark.asyncio
    async def test_process_frame_roi_none_uses_full_frame(self, mock_frame):
        """Test without ROI, full frame is passed to detector."""
        processor = StreamProcessor(
            "test", "rtsp://test.com",
            alarm_types=["helmet"],
        )

        mock_result = {"person_boxes": [], "helmet_boxes": [], "matched": [], "no_helmet": [], "inference_ms": 10.0}

        with patch("app.core.stream_processor.detector") as mock_detector:
            mock_detector.detect_helmet_combined = AsyncMock(return_value=mock_result)

            await processor._process_frame(mock_frame)

            call_args = mock_detector.detect_helmet_combined.call_args_list[0]
            passed_frame = call_args[0][0]
            assert passed_frame.shape == mock_frame.shape

    @pytest.mark.asyncio
    async def test_start_stream_with_roi(self):
        """Test starting a stream with ROI coordinates."""
        StreamManager._instance = None
        manager = StreamManager()

        with patch.object(StreamProcessor, "start", new_callable=AsyncMock):
            result = await manager.start_stream(
                "test", "rtsp://test.com", validate=False,
                roi=(100, 200, 300, 400),
            )
            assert result["success"] is True
            proc = manager._streams["test"]
            assert proc._roi == (100, 200, 300, 400)
