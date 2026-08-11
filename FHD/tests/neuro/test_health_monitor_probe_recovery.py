"""COVERAGE_RAMP C3.1: HealthMonitor 探针失败 / 告警 / 回调 / 摘要 路径。

覆盖：
- _check_neuro_bus: not running / queue 积压 / error 率高
- _check_event_queue: queue 严重积压 / dropped 多
- _check_memory: 正常 / psutil 缺 / 检查失败
- run_check 同步 / 异步 handler
- run_all_checks 聚合
- _evaluate_alert 触发 WARNING / CRITICAL / 回调被吞
- 健康恢复：HEALTHY 时 _resolve_alert_if_exists
- start_monitoring / stop_monitoring 幂等
- get_health_summary 4 态
- DashboardDataProvider
- 全局快捷函数 get_health / check_component / get_system_status
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.neuro_bus import health_monitor as hm
from app.neuro_bus.event_store import EventStore, EventStoreMode
from app.neuro_bus.health_monitor import (
    INCIDENT_REPORTED,
    REASON_EVENT_STORE_UNAVAILABLE,
    RECOVERY_FAILED,
    RECOVERY_REPORTED,
    REMEDIATION_REPORTED,
    AlertLevel,
    DashboardDataProvider,
    HealthCheckResult,
    HealthMonitor,
    HealthStatus,
    check_component,
    get_health,
    get_health_monitor,
    get_system_status,
)


@pytest.fixture
def monitor():
    # 不 _register_default_checks，自动用 mock
    hm._health_monitor_instance = None
    return HealthMonitor(check_interval_seconds=60)


# ---------------------------------------------------------------------------
# _check_neuro_bus 分支
# ---------------------------------------------------------------------------


def test_check_neuro_bus_not_running(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {
        "running": False,
        "queue_size": 0,
        "errors": 0,
        "processed": 1,
    }
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_neuro_bus()
    assert result.status == HealthStatus.UNHEALTHY
    assert "未运行" in result.message


def test_check_neuro_bus_degraded_queue(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {
        "running": True,
        "queue_size": 6000,
        "errors": 0,
        "processed": 100,
    }
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_neuro_bus()
    assert result.status == HealthStatus.DEGRADED
    assert "队列积压" in result.message


def test_check_neuro_bus_degraded_high_error_rate(monitor):
    fake_bus = MagicMock()
    # errors > processed * 0.1 -> degraded
    fake_bus.get_stats.return_value = {
        "running": True,
        "queue_size": 0,
        "errors": 50,
        "processed": 100,
    }
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_neuro_bus()
    assert result.status == HealthStatus.DEGRADED
    assert "错误率" in result.message


def test_check_neuro_bus_healthy(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {
        "running": True,
        "queue_size": 10,
        "errors": 0,
        "processed": 1000,
    }
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_neuro_bus()
    assert result.status == HealthStatus.HEALTHY


def test_check_neuro_bus_exception(monitor):
    with patch.object(hm, "get_neuro_bus", side_effect=RuntimeError("bus down")):
        result = monitor._check_neuro_bus()
    assert result.status == HealthStatus.UNHEALTHY
    assert "bus down" in result.message


# ---------------------------------------------------------------------------
# _check_event_queue 分支
# ---------------------------------------------------------------------------


def test_check_event_queue_unhealthy(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {"queue_size": 9000, "dropped": 0}
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_event_queue()
    assert result.status == HealthStatus.UNHEALTHY


def test_check_event_queue_degraded(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {"queue_size": 5500, "dropped": 0}
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_event_queue()
    assert result.status == HealthStatus.DEGRADED


def test_check_event_queue_degraded_dropped(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {"queue_size": 100, "dropped": 200}
    with patch.object(hm, "get_neuro_bus", return_value=fake_bus):
        result = monitor._check_event_queue()
    assert result.status == HealthStatus.DEGRADED
    assert "丢弃" in result.message


def test_check_event_queue_exception(monitor):
    with patch.object(hm, "get_neuro_bus", side_effect=RuntimeError("err")):
        result = monitor._check_event_queue()
    assert result.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# _check_memory 分支
# ---------------------------------------------------------------------------


def test_check_memory_healthy(monitor):
    fake_proc = MagicMock()
    fake_proc.memory_info.return_value.rss = 200 * 1024 * 1024
    fake_psutil = MagicMock()
    fake_psutil.Process.return_value = fake_proc
    with patch.dict("sys.modules", {"psutil": fake_psutil}):
        result = monitor._check_memory()
    assert result.status == HealthStatus.HEALTHY


def test_check_memory_degraded(monitor):
    fake_proc = MagicMock()
    fake_proc.memory_info.return_value.rss = 1500 * 1024 * 1024
    fake_psutil = MagicMock()
    fake_psutil.Process.return_value = fake_proc
    with patch.dict("sys.modules", {"psutil": fake_psutil}):
        result = monitor._check_memory()
    assert result.status == HealthStatus.DEGRADED


def test_check_memory_no_psutil(monitor):
    # import psutil 时 ImportError
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        result = monitor._check_memory()
    assert result.status == HealthStatus.UNKNOWN


def test_check_memory_exception(monitor):
    fake_psutil = MagicMock()
    fake_psutil.Process.side_effect = RuntimeError("proc error")
    with patch.dict("sys.modules", {"psutil": fake_psutil}):
        result = monitor._check_memory()
    assert result.status == HealthStatus.UNHEALTHY


# ---------------------------------------------------------------------------
# register / unregister check
# ---------------------------------------------------------------------------


def test_register_and_unregister_check(monitor):
    def my_check():
        return None

    monitor.register_check("custom", my_check)
    assert "custom" in monitor._checks
    assert "custom" in monitor._metrics_history
    monitor.unregister_check("custom")
    assert "custom" not in monitor._checks


# ---------------------------------------------------------------------------
# run_check (同步 / 异步 / 异常)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_check_unknown_returns_none(monitor):
    out = await monitor.run_check("not_registered")
    assert out is None


@pytest.mark.asyncio
async def test_run_check_sync_handler(monitor):
    def good():
        from app.neuro_bus.health_monitor import HealthCheckResult

        return HealthCheckResult("x", HealthStatus.HEALTHY, "ok", 0.1)

    monitor.register_check("x", good)
    out = await monitor.run_check("x")
    assert out.status == HealthStatus.HEALTHY
    assert "x" in monitor._last_results


@pytest.mark.asyncio
async def test_run_check_async_handler(monitor):
    async def good():
        from app.neuro_bus.health_monitor import HealthCheckResult

        return HealthCheckResult("y", HealthStatus.HEALTHY, "ok-async", 0.1)

    monitor.register_check("y", good)
    out = await monitor.run_check("y")
    assert out.message == "ok-async"


@pytest.mark.asyncio
async def test_run_check_handler_exception_returns_none(monitor):
    def bad():
        raise RuntimeError("fail")

    monitor.register_check("z", bad)
    out = await monitor.run_check("z")
    assert out is None


@pytest.mark.asyncio
async def test_run_all_checks(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    def c1():
        return HealthCheckResult("c1", HealthStatus.HEALTHY, "ok", 0.1)

    monitor.register_check("c1", c1)
    monitor._checks.pop("neuro_bus", None)
    monitor._checks.pop("event_queue", None)
    monitor._checks.pop("memory", None)

    out = await monitor.run_all_checks()
    assert "c1" in out


# ---------------------------------------------------------------------------
# _evaluate_alert
# ---------------------------------------------------------------------------


def test_evaluate_alert_warning(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    res = HealthCheckResult("comp-w", HealthStatus.DEGRADED, "slow", 200.0)
    monitor._evaluate_alert(res)
    assert "comp-w" in monitor._active_alerts
    assert monitor._active_alerts["comp-w"].level == AlertLevel.WARNING


def test_evaluate_alert_critical(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    res = HealthCheckResult("comp-c", HealthStatus.UNHEALTHY, "down", 500.0)
    monitor._evaluate_alert(res)
    assert monitor._active_alerts["comp-c"].level == AlertLevel.CRITICAL


def test_evaluate_alert_callback_exception_swallowed(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    def bad_callback(alert):
        raise RuntimeError("cb fail")

    monitor.on_alert(bad_callback)
    res = HealthCheckResult("comp-cb", HealthStatus.UNHEALTHY, "down", 0.1)
    monitor._evaluate_alert(res)  # 不抛


def test_evaluate_alert_healthy_resolves_existing(monitor):
    from app.neuro_bus.health_monitor import Alert, HealthCheckResult

    # 注入一个 active alert
    monitor._active_alerts["comp-r"] = Alert(
        alert_id="x",
        level=AlertLevel.WARNING,
        component="comp-r",
        message="old",
        created_at=__import__("datetime").datetime.now(),
    )
    res = HealthCheckResult("comp-r", HealthStatus.HEALTHY, "ok", 0.1)
    monitor._evaluate_alert(res)
    assert "comp-r" not in monitor._active_alerts


# ---------------------------------------------------------------------------
# start / stop monitoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_monitoring_idempotent(monitor):
    monitor._is_running = True
    await monitor.start_monitoring()  # 第二次直接返回
    assert monitor._is_running is True


@pytest.mark.asyncio
async def test_stop_monitoring_sets_flag(monitor):
    monitor._is_running = True
    monitor.stop_monitoring()
    assert monitor._is_running is False


# ---------------------------------------------------------------------------
# get_health_summary
# ---------------------------------------------------------------------------


def test_get_health_summary_no_results(monitor):
    summary = monitor.get_health_summary()
    assert summary["overall_status"] == "healthy"
    assert summary["components"] == 0
    assert summary["status_breakdown"]["healthy"] == 0


def test_get_health_summary_unhealthy_overall(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    monitor._last_results["a"] = HealthCheckResult("a", HealthStatus.UNHEALTHY, "x", 0.1)
    monitor._last_results["b"] = HealthCheckResult("b", HealthStatus.HEALTHY, "y", 0.1)
    summary = monitor.get_health_summary()
    assert summary["overall_status"] == "unhealthy"
    assert summary["components"] == 2


def test_get_health_summary_unknown_overall(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    monitor._last_results["a"] = HealthCheckResult("a", HealthStatus.UNKNOWN, "x", 0.1)
    summary = monitor.get_health_summary()
    assert summary["overall_status"] == "unknown"


def test_get_health_summary_degraded_overall(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    monitor._last_results["a"] = HealthCheckResult("a", HealthStatus.DEGRADED, "x", 0.1)
    summary = monitor.get_health_summary()
    assert summary["overall_status"] == "degraded"


# ---------------------------------------------------------------------------
# 查询接口
# ---------------------------------------------------------------------------


def test_get_component_health_returns_result(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    monitor._last_results["c"] = HealthCheckResult("c", HealthStatus.HEALTHY, "ok", 0.1)
    assert monitor.get_component_health("c") is not None
    assert monitor.get_component_health("missing") is None


def test_get_active_alerts_and_history(monitor):
    import datetime

    from app.neuro_bus.health_monitor import Alert

    monitor._active_alerts["z"] = Alert(
        "z1", AlertLevel.WARNING, "z", "msg", datetime.datetime.now()
    )
    monitor._alerts.append(monitor._active_alerts["z"])
    assert len(monitor.get_active_alerts()) == 1
    assert len(monitor.get_alert_history()) == 1
    assert monitor.get_metrics_history("missing") == []


def test_get_all_components_health_returns_copy(monitor):
    from app.neuro_bus.health_monitor import HealthCheckResult

    monitor._last_results["a"] = HealthCheckResult("a", HealthStatus.HEALTHY, "ok", 0.1)
    out = monitor.get_all_components_health()
    assert "a" in out
    assert out is not monitor._last_results


# ---------------------------------------------------------------------------
# DashboardDataProvider
# ---------------------------------------------------------------------------


def test_dashboard_data_provider(monitor):
    fake_bus = MagicMock()
    fake_bus.get_stats.return_value = {"running": True}
    fake_dlq = MagicMock()
    fake_dlq.get_stats.return_value = {"size": 0}
    fake_store = MagicMock()
    fake_store.get_stats.return_value = {"persisted": 0}

    with (
        patch.object(hm, "get_neuro_bus", return_value=fake_bus),
        patch.object(hm, "get_dead_letter_queue", return_value=fake_dlq),
        patch.object(hm, "get_event_store", return_value=fake_store),
    ):
        provider = DashboardDataProvider(monitor=monitor)
        data = provider.get_dashboard_data()
    assert "timestamp" in data
    assert "health" in data
    assert "neuro_bus" in data
    assert "dead_letter_queue" in data
    assert "event_store" in data


# ---------------------------------------------------------------------------
# 全局快捷函数
# ---------------------------------------------------------------------------


def test_get_health_monitor_singleton():
    hm._health_monitor_instance = None
    a = get_health_monitor()
    b = get_health_monitor()
    assert a is b
    hm._health_monitor_instance = None


def test_get_health_returns_summary(monkeypatch):
    fake = MagicMock()
    fake.get_health_summary.return_value = {"overall_status": "healthy"}
    monkeypatch.setattr(hm, "get_health_monitor", lambda: fake)
    assert get_health()["overall_status"] == "healthy"


def test_check_component(monkeypatch):
    fake = MagicMock()
    fake.get_component_health.return_value = "result"
    monkeypatch.setattr(hm, "get_health_monitor", lambda: fake)
    assert check_component("c") == "result"


def test_get_system_status(monkeypatch):
    fake = MagicMock()
    fake.get_health_summary.return_value = {"overall_status": "healthy"}
    monkeypatch.setattr(hm, "get_health_monitor", lambda: fake)
    assert get_system_status() == "healthy"


# ---------------------------------------------------------------------------
# 闭环自愈（safe remediation closed loop）
# ---------------------------------------------------------------------------


class _FailingStore:
    """append 始终抛错的存储：模拟事件存储不可用。"""

    def __init__(self):
        self.appends = []

    def append(self, event, stream_id=None):
        self.appends.append(event)
        raise RuntimeError("secret-db-error-TOKEN123")


def _health_receipts(store):
    return [
        stored.event for stored in store.get_all() if stored.event.event_type.startswith("health.")
    ]


@pytest.mark.asyncio
async def test_closed_loop_run_check_invokes_handler_and_recovers_on_fresh_healthy_postcondition():
    store = EventStore(mode=EventStoreMode.MEMORY)
    mon = HealthMonitor(check_interval_seconds=60, event_store=store)
    state = {"calls": 0, "handler_calls": 0}

    def svc_check():
        state["calls"] += 1
        # 第一次 = 原始非健康；强制后置条件复查（第二次）= 健康，模拟修复成功
        if state["calls"] == 1:
            return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)
        return HealthCheckResult("svc", HealthStatus.HEALTHY, "ok", 0.1)

    def handler(_result):
        state["handler_calls"] += 1

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    result = await mon.run_check("svc")

    assert result is not None
    # run_check 自动驱动闭环，调用已注册 handler
    assert state["handler_calls"] == 1
    # 复查为健康 -> 报告恢复，且不出现恢复失败
    types = [ev.event_type for ev in _health_receipts(store)]
    assert INCIDENT_REPORTED in types
    assert REMEDIATION_REPORTED in types
    assert RECOVERY_REPORTED in types
    assert RECOVERY_FAILED not in types


@pytest.mark.asyncio
async def test_closed_loop_receipt_action_id_present_and_payload_safe():
    store = EventStore(mode=EventStoreMode.MEMORY)
    mon = HealthMonitor(check_interval_seconds=60, event_store=store)

    def svc_check():
        return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down-raw-token", 0.1)

    def handler(_result):
        pass

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    result = HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down-raw-token", 0.1)
    await mon.run_remediation_closed_loop(result)

    receipts = _health_receipts(store)
    assert receipts
    allowed_keys = {
        "incident_id",
        "component",
        "stage",
        "status",
        "reason_code",
        "durable",
        "action_id",
        "stream_id",
    }
    for ev in receipts:
        # 每条接收单都带注册的 action_id
        assert ev.payload.get("action_id") == "act-fix-svc"
        # 只含固定安全字段，绝不携带 message/details/异常/命令/url/token
        assert set(ev.payload.keys()) == allowed_keys
        assert "down-raw-token" not in str(ev.payload)


@pytest.mark.asyncio
async def test_closed_loop_store_unavailable_no_handler_no_recovery_safe_reason():
    store = _FailingStore()
    mon = HealthMonitor(check_interval_seconds=60, event_store=store)
    state = {"handler_calls": 0}

    def svc_check():
        return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)

    def handler(_result):
        state["handler_calls"] += 1

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    # 自动路径（run_check）：append 失败 -> 不调用 handler、不报告恢复
    await mon.run_check("svc")
    assert state["handler_calls"] == 0
    assert not mon._open_incidents

    # 闭环 outcome：fail safe，原因码安全且不泄漏原始异常文本
    result = HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)
    outcome = await mon.run_remediation_closed_loop(result)
    assert outcome.recovered is False
    assert outcome.reason_code == REASON_EVENT_STORE_UNAVAILABLE
    assert outcome.handler_invoked is False
    assert state["handler_calls"] == 0
    assert "secret-db-error-TOKEN123" not in str(outcome)
    assert not mon._open_incidents


@pytest.mark.asyncio
async def test_closed_loop_no_event_store_fails_safe():
    mon = HealthMonitor(check_interval_seconds=60, event_store=None)

    def svc_check():
        return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)

    def handler(_result):
        pass

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    result = HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)
    outcome = await mon.run_remediation_closed_loop(result)

    assert outcome.recovered is False
    assert outcome.reason_code == REASON_EVENT_STORE_UNAVAILABLE
    assert outcome.handler_invoked is False


@pytest.mark.asyncio
async def test_closed_loop_memory_store_reports_nondurable():
    store = EventStore(mode=EventStoreMode.MEMORY)
    mon = HealthMonitor(check_interval_seconds=60, event_store=store)

    def svc_check():
        return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)

    def handler(_result):
        pass

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    result = HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)
    outcome = await mon.run_remediation_closed_loop(result)

    assert outcome.durable_receipts is False
    receipts = _health_receipts(store)
    assert receipts
    assert all(ev.payload.get("durable") is False for ev in receipts)


@pytest.mark.asyncio
async def test_closed_loop_sqlite_store_reports_durable(tmp_path):
    db = tmp_path / "health_events.db"
    store = EventStore(mode=EventStoreMode.SQLITE, storage_path=str(db))
    mon = HealthMonitor(check_interval_seconds=60, event_store=store)

    def svc_check():
        return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)

    def handler(_result):
        pass

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    result = HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)
    outcome = await mon.run_remediation_closed_loop(result)

    assert outcome.durable_receipts is True
    receipts = _health_receipts(store)
    assert receipts
    assert all(ev.payload.get("durable") is True for ev in receipts)


@pytest.mark.asyncio
async def test_closed_loop_at_most_once_per_pending_incident():
    store = EventStore(mode=EventStoreMode.MEMORY)
    mon = HealthMonitor(check_interval_seconds=60, event_store=store)
    state = {"handler_calls": 0}

    def svc_check():
        return HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)

    def handler(_result):
        state["handler_calls"] += 1

    mon.register_check("svc", svc_check)
    mon.register_remediation("svc", "act-fix-svc", handler)

    result = HealthCheckResult("svc", HealthStatus.UNHEALTHY, "down", 0.1)

    # 第一次：执行 handler，postcondition 仍非健康 -> recovery_failed，incident 保持未决
    first = await mon.run_remediation_closed_loop(result)
    assert first.handler_invoked is True
    assert first.recovered is False
    assert state["handler_calls"] == 1

    # 第二次：同一未决 incident -> 不重复执行 handler（至少一次保障）
    second = await mon.run_remediation_closed_loop(result)
    assert second.status == "already_attempted"
    assert second.handler_invoked is False
    assert state["handler_calls"] == 1
