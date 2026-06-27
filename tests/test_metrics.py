"""Tests for lightweight metrics module."""

import pytest

from app.core.metrics import (
    inc_counter, set_gauge, observe_histogram,
    render_metrics, reset, _counters, _gauges, _histograms,
)


class TestMetrics:
    """Test metrics collection and rendering."""

    def setup_method(self):
        reset()

    def test_inc_counter(self):
        inc_counter("requests_total")
        inc_counter("requests_total")
        inc_counter("requests_total", value=3)
        assert _counters["requests_total"] == 5.0

    def test_inc_counter_with_labels(self):
        inc_counter("errors_total", method="GET", path="/api")
        inc_counter("errors_total", method="GET", path="/api")
        inc_counter("errors_total", method="POST", path="/api")
        key_get = 'errors_total{method="GET", path="/api"}'
        key_post = 'errors_total{method="POST", path="/api"}'
        assert _counters[key_get] == 2.0
        assert _counters[key_post] == 1.0

    def test_set_gauge(self):
        set_gauge("active_streams", 5)
        set_gauge("active_streams", 3)
        assert _gauges["active_streams"] == 3.0

    def test_observe_histogram(self):
        observe_histogram("latency_seconds", 0.05)
        observe_histogram("latency_seconds", 0.15)
        observe_histogram("latency_seconds", 0.5)
        h = _histograms["latency_seconds"]
        assert h["count"] == 3
        assert h["sum"] == pytest.approx(0.7, rel=0.01)
        # 0.05 falls in bucket 0.05, 0.15 in 0.25, 0.5 in 0.5
        assert h["buckets"][0.05] == 1
        assert h["buckets"][0.25] == 2
        assert h["buckets"][0.5] == 3

    def test_render_metrics_format(self):
        inc_counter("test_counter")
        set_gauge("test_gauge", 42.0)
        observe_histogram("test_histogram", 0.1)

        output = render_metrics()
        assert "test_counter" in output
        assert "test_gauge" in output
        assert "test_histogram_bucket" in output
        assert "# TYPE test_counter counter" in output
        assert "# TYPE test_gauge gauge" in output
        assert "# TYPE test_histogram histogram" in output

    def test_render_empty_metrics(self):
        output = render_metrics()
        # Should be a valid (possibly empty) string
        assert isinstance(output, str)

    def test_reset_clears_all(self):
        inc_counter("c1")
        set_gauge("g1", 1)
        observe_histogram("h1", 0.1)
        reset()
        assert len(_counters) == 0
        assert len(_gauges) == 0
        assert len(_histograms) == 0

    def test_histogram_plus_inf_bucket(self):
        observe_histogram("big_latency", 100.0)
        output = render_metrics()
        assert 'big_latency_bucket{le="+Inf"} 1' in output
