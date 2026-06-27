"""Lightweight Prometheus-compatible metrics — zero external dependencies.

Exposes /metrics in Prometheus text format. Counters, gauges, and histograms
are tracked in-memory. No prometheus_client library required.
"""

import time
import threading
from typing import Dict, Optional
from collections import defaultdict

from app.utils.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()

# ── Counters ──
_counters: Dict[str, float] = defaultdict(float)

# ── Gauges ──
_gauges: Dict[str, float] = {}

# ── Histograms (simplified: track count, sum, and bucket boundaries) ──
_HISTOGRAM_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_histograms: Dict[str, Dict] = {}


def inc_counter(name: str, value: float = 1.0, **labels: str) -> None:
    key = _label_key(name, labels)
    with _lock:
        _counters[key] += value


def set_gauge(name: str, value: float, **labels: str) -> None:
    key = _label_key(name, labels)
    with _lock:
        _gauges[key] = value


def observe_histogram(name: str, value: float, **labels: str) -> None:
    key = _label_key(name, labels)
    with _lock:
        if key not in _histograms:
            _histograms[key] = {
                "count": 0,
                "sum": 0.0,
                "buckets": {b: 0 for b in _HISTOGRAM_BUCKETS},
            }
        h = _histograms[key]
        h["count"] += 1
        h["sum"] += value
        for b in _HISTOGRAM_BUCKETS:
            if value <= b:
                h["buckets"][b] += 1


def _label_key(name: str, labels: dict) -> str:
    if labels:
        label_str = ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"
    return name


def render_metrics() -> str:
    """Render all metrics in Prometheus text exposition format."""
    lines = []

    with _lock:
        # Counters
        for key, val in sorted(_counters.items()):
            lines.append(f"# TYPE {_extract_name(key)} counter")
            lines.append(f"{key} {val}")

        # Gauges
        for key, val in sorted(_gauges.items()):
            lines.append(f"# TYPE {_extract_name(key)} gauge")
            lines.append(f"{key} {val}")

        # Histograms
        for key, h in sorted(_histograms.items()):
            base_name = _extract_name(key)
            lines.append(f"# TYPE {base_name} histogram")
            for bucket_bound, bucket_count in sorted(h["buckets"].items()):
                lines.append(f'{key}_bucket{{le="{bucket_bound}"}} {bucket_count}')
            lines.append(f'{key}_bucket{{le="+Inf"}} {h["count"]}')
            lines.append(f"{key}_sum {h['sum']}")
            lines.append(f"{key}_count {h['count']}")

    return "\n".join(lines) + "\n"


def _extract_name(key: str) -> str:
    return key.split("{")[0]


def reset() -> None:
    """Reset all metrics (for testing)."""
    with _lock:
        _counters.clear()
        _gauges.clear()
        _histograms.clear()
