"""Tests for batch video analyzer module."""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.core.batch_analyzer import (
    analyze_video_file,
    batch_analyze,
    generate_html_report,
)


class TestAnalyzeVideoFile:
    @pytest.mark.asyncio
    async def test_nonexistent_file(self):
        """Test analyzing a nonexistent file returns error."""
        result = await analyze_video_file("/nonexistent/video.mp4")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_analyze_with_mock(self):
        """Test analyze with mocked video capture."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True

        # Mock get() to return different values for different constants
        def mock_get(prop):
            if prop == 5:  # CAP_PROP_FPS
                return 25.0
            elif prop == 7:  # CAP_PROP_FRAME_COUNT
                return 3.0
            return 0.0

        mock_cap.get = mock_get

        # Return 3 frames then stop
        frame_count = [0]
        def mock_read():
            frame_count[0] += 1
            if frame_count[0] > 3:
                return False, None
            return True, np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

        mock_cap.read = mock_read

        mock_detections = MagicMock()
        mock_detections.__len__ = MagicMock(return_value=0)

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("app.core.batch_analyzer.detector") as mock_det:
            mock_det.detect_with_model = AsyncMock(return_value=(mock_detections, 10.0))
            mock_det.get_class_name = MagicMock(return_value="person")

            result = await analyze_video_file("test.mp4", frame_interval=1)

            assert result["total_frames"] == 3
            assert "file" in result


class TestBatchAnalyze:
    @pytest.mark.asyncio
    async def test_empty_directory(self):
        """Test batch analyze with no video files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await batch_analyze(tmpdir)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self):
        """Test batch analyze with nonexistent directory."""
        result = await batch_analyze("/nonexistent/dir")
        assert "error" in result


class TestGenerateHtmlReport:
    def test_empty_report(self):
        """Test HTML report generation with empty data."""
        analysis = {
            "model": "general",
            "confidence": 0.3,
            "total_files": 0,
            "total_detections_frames": 0,
            "classes_found": [],
            "files": [],
        }
        html = generate_html_report(analysis)
        assert "<html" in html
        assert "批量视频分析报告" in html
        assert "0" in html

    def test_report_with_data(self):
        """Test HTML report with sample data."""
        analysis = {
            "model": "helmet",
            "confidence": 0.5,
            "total_files": 2,
            "total_detections_frames": 10,
            "classes_found": ["helmet", "no-helmet"],
            "files": [
                {"file": "video1.mp4", "total_frames": 100, "frames_with_detections": 5, "fps": 25.0, "results": [
                    {"frame": 10, "time": 0.4, "detections": [{"class_name": "helmet", "confidence": 0.9, "bbox": [10, 20, 100, 200]}]},
                ]},
                {"file": "video2.mp4", "total_frames": 200, "frames_with_detections": 5, "fps": 30.0, "results": []},
            ],
        }
        html = generate_html_report(analysis)
        assert "video1.mp4" in html
        assert "video2.mp4" in html
        assert "helmet" in html
        assert "2" in html  # total_files
