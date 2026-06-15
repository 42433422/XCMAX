"""app/utils/performance_monitor 测试。"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from app.utils.performance_monitor import (
    APIMetric,
    MemorySnapshot,
    PerformanceAlert,
    PerformanceMetric,
    PerformanceMonitor,
    get_performance_monitor,
    performance_timer,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_performance_metric(self):
        m = PerformanceMetric(name="test", duration_ms=100.0)
        assert m.name == "test"
        assert m.duration_ms == 100.0
        assert m.success is True
        assert m.metadata == {}

    def test_api_metric(self):
        m = APIMetric(
            endpoint="/api/test",
            method="GET",
            status_code=200,
            duration_ms=50.0,
        )
        assert m.endpoint == "/api/test"
        assert m.method == "GET"
        assert m.status_code == 200
        assert m.user_id is None

    def test_memory_snapshot(self):
        s = MemorySnapshot(timestamp=time.time(), rss_mb=100.0, vms_mb=200.0, percent=5.0)
        assert s.rss_mb == 100.0
        assert s.cache_objects == 0

    def test_performance_alert(self):
        a = PerformanceAlert(
            level="warning",
            metric_type="slow_api",
            message="Slow API",
            value=2000.0,
            threshold=1000.0,
        )
        assert a.level == "warning"
        assert a.timestamp > 0


# ---------------------------------------------------------------------------
# PerformanceMonitor.__init__
# ---------------------------------------------------------------------------


class TestPerformanceMonitorInit:
    def test_init(self):
        monitor = PerformanceMonitor()
        assert len(monitor._metrics) == 0
        assert len(monitor._api_metrics) == 0
        assert len(monitor._alerts) == 0


# ---------------------------------------------------------------------------
# record_metric
# ---------------------------------------------------------------------------


class TestRecordMetric:
    def test_records_metric(self):
        monitor = PerformanceMonitor()
        monitor.record_metric("test_op", 100.0)
        assert len(monitor._metrics) == 1
        assert monitor._metrics[0].name == "test_op"

    def test_records_failed_metric(self):
        monitor = PerformanceMonitor()
        monitor.record_metric("test_op", 100.0, success=False)
        assert monitor._metrics[0].success is False

    def test_records_metadata(self):
        monitor = PerformanceMonitor()
        monitor.record_metric("test_op", 100.0, key="value")
        assert monitor._metrics[0].metadata["key"] == "value"


# ---------------------------------------------------------------------------
# record_api_call
# ---------------------------------------------------------------------------


class TestRecordApiCall:
    def test_records_api_call(self):
        monitor = PerformanceMonitor()
        monitor.record_api_call("/api/test", "GET", 200, 50.0)
        assert len(monitor._api_metrics) == 1
        assert monitor._api_metrics[0].endpoint == "/api/test"

    def test_slow_api_creates_alert(self):
        monitor = PerformanceMonitor()
        monitor.record_api_call("/api/slow", "GET", 200, 5000.0)
        assert len(monitor._alerts) == 1
        assert monitor._alerts[0].metric_type == "slow_api"


# ---------------------------------------------------------------------------
# record_memory
# ---------------------------------------------------------------------------


class TestRecordMemory:
    def test_with_psutil(self):
        monitor = PerformanceMonitor()
        with patch("psutil.Process") as mock_process_cls:
            mock_process = MagicMock()
            mock_process.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024, vms=200 * 1024 * 1024)
            mock_process.memory_percent.return_value = 5.0
            mock_process_cls.return_value = mock_process
            snapshot = monitor.record_memory()
            assert snapshot.rss_mb == 100.0
            assert len(monitor._memory_history) == 1

    def test_without_psutil(self):
        monitor = PerformanceMonitor()
        with patch.dict("sys.modules", {"psutil": None}):
            snapshot = monitor.record_memory()
            assert snapshot.rss_mb == 0


# ---------------------------------------------------------------------------
# track (context manager)
# ---------------------------------------------------------------------------


class TestTrack:
    def test_tracks_success(self):
        monitor = PerformanceMonitor()
        with monitor.track("test_op"):
            time.sleep(0.01)
        assert len(monitor._metrics) == 1
        assert monitor._metrics[0].success is True

    def test_tracks_failure(self):
        monitor = PerformanceMonitor()
        with pytest.raises(ValueError):
            with monitor.track("test_op"):
                raise ValueError("oops")
        assert len(monitor._metrics) == 1
        assert monitor._metrics[0].success is False
        assert "error" in monitor._metrics[0].metadata


# ---------------------------------------------------------------------------
# timer decorator
# ---------------------------------------------------------------------------


class TestTimerDecorator:
    def test_decorates_function(self):
        monitor = PerformanceMonitor()

        @monitor.timer("my_func")
        def my_func():
            return 42

        result = my_func()
        assert result == 42
        assert len(monitor._metrics) == 1
        assert monitor._metrics[0].name == "my_func"

    def test_auto_name(self):
        monitor = PerformanceMonitor()

        @monitor.timer()
        def my_func():
            return 42

        result = my_func()
        assert result == 42
        assert "my_func" in monitor._metrics[0].name

    def test_include_args(self):
        monitor = PerformanceMonitor()

        @monitor.timer(include_args=True)
        def my_func(x):
            return x

        result = my_func(5)
        assert result == 5

    def test_exception_recorded(self):
        monitor = PerformanceMonitor()

        @monitor.timer("failing_func")
        def my_func():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            my_func()
        assert len(monitor._metrics) == 1
        assert monitor._metrics[0].success is False


# ---------------------------------------------------------------------------
# api_timer decorator
# ---------------------------------------------------------------------------


class TestApiTimerDecorator:
    def test_success(self):
        monitor = PerformanceMonitor()

        @monitor.api_timer()
        def my_api():
            return "ok"

        result = my_api()
        assert result == "ok"
        assert len(monitor._api_metrics) == 1
        assert monitor._api_metrics[0].status_code == 200

    def test_failure(self):
        monitor = PerformanceMonitor()

        @monitor.api_timer()
        def my_api():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError, match="fail"):
            my_api()
        assert len(monitor._api_metrics) == 1
        assert monitor._api_metrics[0].status_code == 500


# ---------------------------------------------------------------------------
# get_metrics_summary
# ---------------------------------------------------------------------------


class TestGetMetricsSummary:
    def test_no_data(self):
        monitor = PerformanceMonitor()
        summary = monitor.get_metrics_summary()
        assert "暂无数据" in summary["message"]

    def test_with_data(self):
        monitor = PerformanceMonitor()
        monitor.record_metric("op1", 100.0)
        monitor.record_metric("op2", 200.0)
        summary = monitor.get_metrics_summary()
        assert summary["total_calls"] == 2
        assert summary["avg_duration_ms"] == 150.0
        assert summary["success_rate"] == 100.0

    def test_with_api_data(self):
        monitor = PerformanceMonitor()
        monitor.record_api_call("/api/test", "GET", 200, 50.0)
        summary = monitor.get_metrics_summary()
        assert summary["api_stats"]["total"] == 1

    def test_with_memory(self):
        monitor = PerformanceMonitor()
        snapshot = MemorySnapshot(timestamp=time.time(), rss_mb=100.0, vms_mb=200.0, percent=5.0)
        monitor._memory_history.append(snapshot)
        summary = monitor.get_metrics_summary()
        # Need some metric data first
        monitor.record_metric("op", 10.0)
        summary = monitor.get_metrics_summary()
        assert "memory" in summary


# ---------------------------------------------------------------------------
# get_prometheus_metrics
# ---------------------------------------------------------------------------


class TestGetPrometheusMetrics:
    def test_empty_metrics(self):
        monitor = PerformanceMonitor()
        output = monitor.get_prometheus_metrics()
        assert "xcagi_request_duration_seconds" in output

    def test_with_metrics(self):
        monitor = PerformanceMonitor()
        monitor.record_metric("test_op", 100.0)
        output = monitor.get_prometheus_metrics()
        assert "test_op" in output

    def test_with_api_metrics(self):
        monitor = PerformanceMonitor()
        monitor.record_api_call("/api/test", "GET", 200, 50.0)
        output = monitor.get_prometheus_metrics()
        assert "xcagi_api_requests_total" in output


# ---------------------------------------------------------------------------
# get_alerts
# ---------------------------------------------------------------------------


class TestGetAlerts:
    def test_no_alerts(self):
        monitor = PerformanceMonitor()
        alerts = monitor.get_alerts()
        assert alerts == []

    def test_with_alerts(self):
        monitor = PerformanceMonitor()
        monitor._alerts.append(
            PerformanceAlert(
                level="warning",
                metric_type="slow_api",
                message="Slow",
                value=2000.0,
                threshold=1000.0,
            )
        )
        alerts = monitor.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["level"] == "warning"

    def test_filter_by_level(self):
        monitor = PerformanceMonitor()
        monitor._alerts.append(
            PerformanceAlert(
                level="warning",
                metric_type="slow_api",
                message="Slow",
                value=2000.0,
                threshold=1000.0,
            )
        )
        monitor._alerts.append(
            PerformanceAlert(
                level="critical",
                metric_type="high_memory",
                message="High memory",
                value=1000.0,
                threshold=512.0,
            )
        )
        warnings = monitor.get_alerts(level="warning")
        assert len(warnings) == 1

    def test_limit(self):
        monitor = PerformanceMonitor()
        for i in range(30):
            monitor._alerts.append(
                PerformanceAlert(
                    level="warning",
                    metric_type="test",
                    message=f"Alert {i}",
                    value=float(i),
                    threshold=0.0,
                )
            )
        alerts = monitor.get_alerts(limit=5)
        assert len(alerts) == 5


# ---------------------------------------------------------------------------
# clear_history
# ---------------------------------------------------------------------------


class TestClearHistory:
    def test_clears_all(self):
        monitor = PerformanceMonitor()
        monitor.record_metric("op", 10.0)
        monitor.record_api_call("/api/test", "GET", 200, 50.0)
        monitor.clear_history()
        assert len(monitor._metrics) == 0
        assert len(monitor._api_metrics) == 0
        assert len(monitor._alerts) == 0


# ---------------------------------------------------------------------------
# get_performance_monitor / performance_timer
# ---------------------------------------------------------------------------


class TestGlobalFunctions:
    def test_get_performance_monitor(self):
        import app.utils.performance_monitor as pm

        old = pm._performance_monitor_instance
        pm._performance_monitor_instance = None
        try:
            monitor = get_performance_monitor()
            assert isinstance(monitor, PerformanceMonitor)
        finally:
            pm._performance_monitor_instance = old

    def test_performance_timer_decorator(self):
        @performance_timer("test_func")
        def my_func():
            return 42

        result = my_func()
        assert result == 42
