"""HealthMonitor 真实 FastAPI 运行时接线（runtime wiring）E2E。

覆盖：
- configure_runtime_health_monitor：在正常 XCAGI 数据根下创建专用 SQLite EventStore，
  注册唯一固定动作 neuro_bus.ensure_running.v1，且不改动全局 EventStore 默认值。
- 真实 E2E：temp XCAGI_DATA_DIR + 已停止（executor 已 shutdown）的 NeuroBus ->
  实际配置的固定 handler 重启 -> running/healthy 后置条件 -> SQLite 记录 incident /
  remediation / recovery，且只含安全结构化字段。
- bus.py 重启安全修复证明：stop() 后 start() 重建执行器。
- store 设置失败（fail-safe）：不注册 handler、不自动修复、无 recovered 声明。
- FastAPI 启动入口（lifespan._init_neuro_ddd_async）接线单例监控器并启动监控循环。
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.neuro_bus.event_store import EventStoreMode
from app.neuro_bus.events.base import EventMetadata, NeuroEvent
from app.neuro_bus.health_monitor import (
    HEALTH_EVENTS_DB_NAME,
    INCIDENT_REPORTED,
    NEURO_BUS_REMEDIATION_ACTION,
    RECOVERY_FAILED,
    RECOVERY_REPORTED,
    REMEDIATION_REPORTED,
    configure_runtime_health_monitor,
)

_ALLOWED_RECEIPT_KEYS = {
    "incident_id",
    "component",
    "stage",
    "status",
    "reason_code",
    "durable",
    "action_id",
    "stream_id",
}


def _health_receipts(store):
    return [
        stored.event for stored in store.get_all() if stored.event.event_type.startswith("health.")
    ]


def test_runtime_wiring_creates_durable_sqlite_store_and_fixed_action(
    tmp_path, monkeypatch, reset_health_monitor
):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    monitor, durable = configure_runtime_health_monitor()

    assert durable is True
    assert monitor.has_remediation("neuro_bus")
    # action_id 是固定字面量，绝不从健康内容派生
    action_id, _handler = monitor._remediation_handlers["neuro_bus"]
    assert action_id == NEURO_BUS_REMEDIATION_ACTION
    assert action_id == "neuro_bus.ensure_running.v1"
    # 事件存储位于数据根下且为 SQLite（durable）
    store = monitor._event_store
    assert store is not None
    assert getattr(store, "_mode", None) == EventStoreMode.SQLITE
    # 专用 SQLite 存储路径必须精确落在临时 XCAGI 数据根之下（tmp_path/data/<db>），
    # 绝不回落到源码树或 cwd。
    assert store._storage_path == str(tmp_path / "data" / HEALTH_EVENTS_DB_NAME)
    assert HEALTH_EVENTS_DB_NAME == "neuro_health_events.db"
    # 该存储路径不得出现在任何接收单 payload 中（payload 仅含固定安全字段）
    assert all(
        str(store._storage_path) not in ev.payload.values()
        for stored in store.get_all()
        for ev in [stored.event]
    )
    # 不改动全局 EventStore 默认（仍为内存）
    from app.neuro_bus.event_store import get_event_store

    assert getattr(get_event_store(), "_mode", None) == EventStoreMode.MEMORY


@pytest.mark.asyncio
async def test_runtime_e2e_stopped_bus_restart_healthy_durable_receipts(
    tmp_path, monkeypatch, reset_health_monitor, reset_bus_singleton
):
    """真实 E2E：已停止的 NeuroBus -> 实际配置的固定 handler -> 健康后置条件 ->
    SQLite 记录三阶段接收单且只含安全结构化字段；并证明 bus.py 重启安全修复。

    重启证明包含白盒与黑盒两层：先断言执行器被重建（_shutdown 翻转为 False），再以
    黑盒续证——重启后 register 一个同步（is_async=False）handler、发布最小安全事件，
    并 await 有界 Event 以证明真实后重启处理路径经 run_in_executor 调用了该同步
    handler。若重启未真正重建执行器，publish 后 run_in_executor 会在已关闭的线程池上
    抛错，probe 永不置位，从而该断言失败。
    """
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    from app.neuro_bus.bus import get_neuro_bus

    monitor, durable = configure_runtime_health_monitor()
    assert durable is True
    store = monitor._event_store

    # 构造"已停止"的总线：先启动再 stop()，令 executor 被 shutdown
    bus = get_neuro_bus()
    await bus.start()
    await bus.stop()
    assert bus.is_running is False
    assert bus._executor._shutdown is True  # stop() 确实关掉了执行器

    # 运行配置好的运行时检查 -> 触发实际 handler -> 强制后置条件复查
    result = await monitor.run_check("neuro_bus")
    assert result is not None
    # 已由实际配置的 handler 重启（executor 被重建 -> 重启安全）
    assert bus.is_running is True
    assert bus._executor._shutdown is False

    # durable SQLite 接收单：incident / remediation / recovery，安全字段
    receipts = _health_receipts(store)
    types = {ev.event_type for ev in receipts}
    assert INCIDENT_REPORTED in types
    assert REMEDIATION_REPORTED in types
    assert RECOVERY_REPORTED in types
    assert RECOVERY_FAILED not in types
    for ev in receipts:
        assert set(ev.payload.keys()) == _ALLOWED_RECEIPT_KEYS
        assert ev.payload.get("action_id") == NEURO_BUS_REMEDIATION_ACTION
        assert ev.payload.get("durable") is True

    # —— 黑盒续证：重启后的总线必须真实可处理事件（同步 handler 经 run_in_executor 执行）。
    # 仅断言 _shutdown 标志是"白盒"证据；这里用真实 publish -> 处理循环 -> run_in_executor
    # 调用同步 handler 来证明重启后执行器真实可用（若重启未重建执行器，此步会在已关闭的
    # 线程池上抛错，probe 永不置位 -> 失败）。所有 payload 仅测试使用，无任何外部调用。
    probe_called = threading.Event()

    def _sync_probe_handler(event: NeuroEvent) -> None:
        probe_called.set()

    bus.subscribe("health.test.sync_probe", _sync_probe_handler, is_async=False)
    probe_event = NeuroEvent(
        event_type="health.test.sync_probe",
        payload={"probe": True},
        metadata=EventMetadata(source="test", domain="health"),
    )
    assert bus.publish(probe_event) is True
    # 同步 handler 在线程池执行：以有界超时等待，避免挂起
    await asyncio.to_thread(probe_called.wait, 3.0)
    assert probe_called.is_set()  # 真实后重启处理路径已调用同步 handler

    # 清理：关闭总线，避免后台任务泄漏到事件循环
    await bus.stop()


@pytest.mark.asyncio
async def test_runtime_wiring_store_setup_failure_disables_remediation(
    tmp_path, monkeypatch, reset_health_monitor, reset_bus_singleton
):
    """fail-safe：持久化事件存储不可用 -> 自动修复被禁用，无 handler、无 recovered。"""
    data_dir = tmp_path / "datadir"
    data_dir.mkdir()
    # 用文件占住 "data" 位置，令 durable store 建库失败
    (data_dir / "data").write_text("occupied")
    monkeypatch.setenv("XCAGI_DATA_DIR", str(data_dir))

    from app.neuro_bus.bus import get_neuro_bus

    monitor, durable = configure_runtime_health_monitor()
    assert durable is False
    assert not monitor.has_remediation("neuro_bus")  # 自动修复被禁用
    assert monitor._event_store is None

    # 即便总线已停止，也绝不自动重启、绝不产生 recovered 声明
    bus = get_neuro_bus()
    await bus.start()
    await bus.stop()
    result = await monitor.run_check("neuro_bus")
    assert result is not None
    assert bus.is_running is False  # 无自动修复
    assert not monitor._recovery_emitted


@pytest.mark.asyncio
async def test_singleton_reuse_failure_clears_stale_remediation(
    tmp_path, monkeypatch, reset_health_monitor, reset_bus_singleton
):
    """单例复用：先成功接线，后一次持久化存储失败不得残留可调用的修复 handler。

    同一进程内先 configure 成功（handler 已注册），随后在数据根下放置名为 ``data`` 的
    文件令 durable store 构建失败再次 configure：必须 durable=False、event store=None、
    has_remediation=False，且已停止的总线 run_check 后仍保持停止、无 recovery 声明。
    """
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    # 第一次：成功接线，单例上注册了固定 handler
    monitor, durable = configure_runtime_health_monitor()
    assert durable is True
    assert monitor.has_remediation("neuro_bus")

    # 第二次：用含同名文件 "data" 的数据根强制 durable store 构建失败
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    (bad_dir / "data").write_text("occupied")
    monitor2, durable2 = configure_runtime_health_monitor(data_dir=str(bad_dir))

    # 仍是同一个单例
    assert monitor2 is monitor
    assert durable2 is False
    assert monitor._event_store is None
    # 先前成功接线残留的 handler 必须被清除，绝不保留可调用状态
    assert not monitor.has_remediation("neuro_bus")

    # 已停止的总线 run_check 后仍保持停止，无自动修复、无 recovery 声明
    from app.neuro_bus.bus import get_neuro_bus

    bus = get_neuro_bus()
    await bus.start()
    await bus.stop()
    assert bus.is_running is False
    result = await monitor.run_check("neuro_bus")
    assert result is not None
    assert bus.is_running is False  # 不再自动重启
    assert not monitor._recovery_emitted


@pytest.mark.asyncio
async def test_lifespan_startup_wires_configured_monitor(
    tmp_path, monkeypatch, reset_health_monitor, reset_bus_singleton
):
    """FastAPI 启动入口（lifespan._init_neuro_ddd_async）接线单例监控器并启动监控循环。"""
    import importlib

    from app.neuro_bus.bus import get_neuro_bus
    from app.neuro_bus.health_monitor import get_health_monitor

    lifespan_mod = importlib.import_module("app.fastapi_app.lifespan")

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))

    state = SimpleNamespace()
    app = SimpleNamespace(state=state)

    # 仅 stub 无关的重型运行时依赖；监控器接线走真实路径
    monkeypatch.setattr(lifespan_mod, "passive_node_enabled", lambda: False)

    async def _fake_register_neuro_runtime():
        return SimpleNamespace(registered_domains=[])

    monkeypatch.setattr(
        "app.neuro_bus.register_runtime.register_neuro_runtime",
        _fake_register_neuro_runtime,
    )
    monkeypatch.setattr(
        "app.neuro_bus.bus_setup.get_neuro_bus_manager",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "app.domain.neuro.register_cognition_handlers.register_cognition_handlers",
        lambda: {"enabled": False},
    )

    await lifespan_mod._init_neuro_ddd_async(app)

    monitor = get_health_monitor()
    # 已接线：durable 事件存储 + 固定动作 + 已启动监控循环
    assert monitor.has_remediation("neuro_bus")
    assert getattr(monitor._event_store, "_mode", None) == EventStoreMode.SQLITE
    task = getattr(state, "neuro_health_monitor_task", None)
    assert task is not None
    # 让已调度的监控任务开始执行，_is_running 翻转为 True
    await asyncio.sleep(0)
    assert monitor._is_running is True

    # 清理：取消并 await 监控任务（抑制 CancelledError），再停止监控与总线，
    # 恢复全局单例（fixture teardown 亦会重置）。避免遗留尚未完成取消的 pending 任务。
    task = getattr(state, "neuro_health_monitor_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    monitor.stop_monitoring()
    bus = get_neuro_bus()
    if bus.is_running:
        await bus.stop()
