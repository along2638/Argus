"""Tests for GPU monitor module."""

import sys
from unittest.mock import patch, MagicMock

import pytest

from app.core.gpu_monitor import GPUMonitor


class TestGPUMonitor:
    """Test GPUMonitor class."""

    def test_check_availability_no_cuda(self):
        """Test GPU detection when CUDA is not available."""
        monitor = GPUMonitor()
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            result = monitor.check_availability()
            assert result is False

    def test_check_availability_with_cuda(self):
        """Test GPU detection when CUDA is available."""
        monitor = GPUMonitor()
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        with patch.dict(sys.modules, {"onnxruntime": mock_ort}):
            result = monitor.check_availability()
            assert result is True

    def test_check_availability_import_error(self):
        """Test GPU detection when onnxruntime import fails."""
        monitor = GPUMonitor()
        with patch.dict(sys.modules, {"onnxruntime": None}):
            result = monitor.check_availability()
            assert result is False

    def test_get_memory_info_no_gpu(self):
        """Test memory info when GPU is not available."""
        monitor = GPUMonitor()
        monitor._available = False
        info = monitor.get_memory_info()
        assert info["available"] is False
        assert info["total_mb"] == 0

    def test_get_memory_info_with_nvidia_smi(self):
        """Test memory info from nvidia-smi output."""
        monitor = GPUMonitor()
        monitor._available = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "16384, 8192, 8192\n"

        with patch("subprocess.run", return_value=mock_result):
            info = monitor.get_memory_info()
            assert info["available"] is True
            assert info["total_mb"] == 16384
            assert info["used_mb"] == 8192
            assert info["free_mb"] == 8192
            assert info["percent"] == 50.0

    def test_get_memory_info_nvidia_smi_not_found(self):
        """Test memory info when nvidia-smi is not installed."""
        monitor = GPUMonitor()
        monitor._available = True

        with patch("subprocess.run", side_effect=FileNotFoundError):
            info = monitor.get_memory_info()
            assert info["available"] is True
            assert info["total_mb"] == 0

    def test_is_low_memory(self):
        """Test low memory detection."""
        monitor = GPUMonitor()
        monitor._available = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "16384, 15500, 884\n"

        with patch("subprocess.run", return_value=mock_result):
            assert monitor.is_low_memory(threshold_percent=90) is True

    def test_is_not_low_memory(self):
        """Test normal memory usage."""
        monitor = GPUMonitor()
        monitor._available = True

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "16384, 4096, 12288\n"

        with patch("subprocess.run", return_value=mock_result):
            assert monitor.is_low_memory(threshold_percent=90) is False

    def test_get_status_summary(self):
        """Test status summary output."""
        monitor = GPUMonitor()
        monitor._available = False
        summary = monitor.get_status_summary()
        assert "gpu_available" in summary
        assert "gpu_memory_total_mb" in summary
        assert "gpu_low_memory" in summary
