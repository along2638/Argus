"""GPU memory monitor — detect low VRAM and notify."""

import asyncio
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class GPUMonitor:
    """Monitor GPU memory usage and detect issues."""

    def __init__(self):
        self._available: Optional[bool] = None
        self._total_mb: float = 0
        self._used_mb: float = 0
        self._percent: float = 0

    def check_availability(self) -> bool:
        """Check if CUDA GPU is available."""
        try:
            import onnxruntime as ort
            providers = ort.get_available_providers()
            self._available = "CUDAExecutionProvider" in providers
            return self._available
        except Exception:
            self._available = False
            return False

    def get_memory_info(self) -> dict:
        """Get current GPU memory info.

        Returns dict with total_mb, used_mb, free_mb, percent, available.
        """
        if self._available is None:
            self.check_availability()

        if not self._available:
            return {
                "available": False,
                "total_mb": 0,
                "used_mb": 0,
                "free_mb": 0,
                "percent": 0,
            }

        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                if len(parts) >= 3:
                    self._total_mb = float(parts[0].strip())
                    self._used_mb = float(parts[1].strip())
                    free_mb = float(parts[2].strip())
                    self._percent = (self._used_mb / self._total_mb * 100) if self._total_mb > 0 else 0
                    return {
                        "available": True,
                        "total_mb": self._total_mb,
                        "used_mb": self._used_mb,
                        "free_mb": free_mb,
                        "percent": round(self._percent, 1),
                    }
        except FileNotFoundError:
            logger.debug("nvidia_smi_not_found")
        except Exception as e:
            logger.warning("gpu_memory_query_failed", error=str(e))

        return {
            "available": True,
            "total_mb": 0,
            "used_mb": 0,
            "free_mb": 0,
            "percent": 0,
        }

    def is_low_memory(self, threshold_percent: float = 90.0) -> bool:
        """Check if GPU memory usage exceeds threshold."""
        info = self.get_memory_info()
        if not info["available"]:
            return False
        return info["percent"] >= threshold_percent

    def get_status_summary(self) -> dict:
        """Get a summary for the health endpoint."""
        info = self.get_memory_info()
        return {
            "gpu_available": info["available"],
            "gpu_memory_total_mb": info["total_mb"],
            "gpu_memory_used_mb": info["used_mb"],
            "gpu_memory_percent": info["percent"],
            "gpu_low_memory": self.is_low_memory(),
        }


# Singleton
gpu_monitor = GPUMonitor()
