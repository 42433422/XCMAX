"""
健康检查与监控 - Level 4 可靠性机制

提供：
- 系统健康检查
- 性能监控
- 告警机制
- 仪表盘数据
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.dead_letter_queue import get_dead_letter_queue
from app.neuro_bus.event_store import EventStore, EventStoreMode, get_event_store
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

from app.neuro_bus.health_monitor_checks import HealthCheckMixin
from app.neuro_bus.health_monitor_remediation import HealthRemediationMixin
from app.neuro_bus.health_monitor_types import (
    INCIDENT_REPORTED as INCIDENT_REPORTED,
)
from app.neuro_bus.health_monitor_types import (
    REASON_EVENT_STORE_UNAVAILABLE as REASON_EVENT_STORE_UNAVAILABLE,
)
from app.neuro_bus.health_monitor_types import (
    REASON_NOT_REGISTERED as REASON_NOT_REGISTERED,
)
from app.neuro_bus.health_monitor_types import (
    REASON_POSTCONDITION_UNHEALTHY as REASON_POSTCONDITION_UNHEALTHY,
)
from app.neuro_bus.health_monitor_types import (
    REASON_REMEDIATION_FAILED as REASON_REMEDIATION_FAILED,
)
from app.neuro_bus.health_monitor_types import (
    RECOVERY_FAILED as RECOVERY_FAILED,
)
from app.neuro_bus.health_monitor_types import (
    RECOVERY_REPORTED as RECOVERY_REPORTED,
)
from app.neuro_bus.health_monitor_types import (
    REMEDIATION_FAILED as REMEDIATION_FAILED,
)
from app.neuro_bus.health_monitor_types import (
    REMEDIATION_REPORTED as REMEDIATION_REPORTED,
)
from app.neuro_bus.health_monitor_types import (
    REMEDIATION_SKIPPED as REMEDIATION_SKIPPED,
)
from app.neuro_bus.health_monitor_types import (
    STATUS_EVIDENCE_UNAVAILABLE as STATUS_EVIDENCE_UNAVAILABLE,
)
from app.neuro_bus.health_monitor_types import (
    Alert as Alert,
)
from app.neuro_bus.health_monitor_types import (
    AlertLevel as AlertLevel,
)
from app.neuro_bus.health_monitor_types import (
    HealthCheckResult as HealthCheckResult,
)
from app.neuro_bus.health_monitor_types import (
    HealthStatus as HealthStatus,
)
from app.neuro_bus.health_monitor_types import (
    RemediationHandler as RemediationHandler,
)
from app.neuro_bus.health_monitor_types import (
    RemediationOutcome as RemediationOutcome,
)


class HealthMonitor(HealthCheckMixin, HealthRemediationMixin):
    """
    健康监控器

    Level 4 可靠性机制:
    - 定期检查各组件健康状态
    - 收集性能指标
    - 触发告警
    - 提供监控数据
    """

    def __init__(self, check_interval_seconds: int = 30, event_store: Any | None = None):
        self._check_interval = check_interval_seconds
        self._checks: dict[str, Callable[[], HealthCheckResult]] = {}
        self._last_results: dict[str, HealthCheckResult] = {}
        self._alerts: deque = deque(maxlen=1000)
        self._active_alerts: dict[str, Alert] = {}
        self._metrics_history: dict[str, deque] = {}
        self._is_running = False
        self._task: asyncio.Task | None = None

        # 闭环自愈状态
        self._event_store: Any | None = event_store
        # 组件 -> (action_id, handler)，按精确注册的组件查找，绝不执行任意来源的 handler 名
        self._remediation_handlers: dict[str, tuple[str, RemediationHandler]] = {}
        # 未决 incident：component -> incident_id（同一未决 incident 至多执行一次 handler）
        self._open_incidents: dict[str, str] = {}
        # 已经执行过 handler 的 incident_id（至少一次保障）
        self._remediated_incidents: set[str] = set()
        # 已发出 recovery 接收单的 incident_id（有界：同一 incident 至多一条 recovery 接收单）
        self._recovery_emitted: set[str] = set()

        # 告警回调
        self._alert_callbacks: list[Callable[[Alert], None]] = []

        # 注册默认检查
        self._register_default_checks()

        logger.info("[HealthMonitor] 初始化完成 (interval=%ss)", check_interval_seconds)

    async def start_monitoring(self):
        """启动监控循环"""
        if self._is_running:
            return

        self._is_running = True
        logger.info("[HealthMonitor] 监控循环已启动")

        while self._is_running:
            try:
                await self.run_all_checks()
                await asyncio.sleep(self._check_interval)
            except RECOVERABLE_ERRORS as e:
                logger.error("[HealthMonitor] 监控循环错误: %s", e)
                await asyncio.sleep(5)

    def stop_monitoring(self):
        """停止监控循环"""
        self._is_running = False
        logger.info("[HealthMonitor] 监控循环已停止")

    # ========== 查询 ==========

    def get_health_summary(self) -> dict[str, Any]:
        """获取健康摘要"""
        status_counts = {s.value: 0 for s in HealthStatus}

        for result in self._last_results.values():
            status_counts[result.status.value] += 1

        overall = HealthStatus.HEALTHY
        if status_counts[HealthStatus.UNHEALTHY.value] > 0:
            overall = HealthStatus.UNHEALTHY
        elif status_counts[HealthStatus.DEGRADED.value] > 0:
            overall = HealthStatus.DEGRADED
        elif status_counts[HealthStatus.UNKNOWN.value] > 0:
            overall = HealthStatus.UNKNOWN

        return {
            "overall_status": overall.value,
            "components": len(self._last_results),
            "status_breakdown": status_counts,
            "active_alerts": len(self._active_alerts),
            "last_check": max(
                (r.checked_at.isoformat() for r in self._last_results.values()), default=None
            ),
        }

    def get_component_health(self, component: str) -> HealthCheckResult | None:
        """获取组件健康状态"""
        return self._last_results.get(component)

    def get_all_components_health(self) -> dict[str, HealthCheckResult]:
        """获取所有组件健康状态"""
        return self._last_results.copy()

    def get_active_alerts(self) -> list[Alert]:
        """获取活动告警"""
        return list(self._active_alerts.values())

    def get_alert_history(self, limit: int = 100) -> list[Alert]:
        """获取告警历史"""
        return list(self._alerts)[-limit:]

    def get_metrics_history(self, component: str) -> list[HealthCheckResult]:
        """获取指标历史"""
        return list(self._metrics_history.get(component, []))

    # ========== 回调注册 ==========

    def on_alert(self, callback: Callable[[Alert], None]):
        """注册告警回调"""
        self._alert_callbacks.append(callback)


class DashboardDataProvider:
    """
    仪表盘数据提供者

    为监控仪表盘提供数据
    """

    def __init__(self, monitor: HealthMonitor | None = None):
        self._monitor = monitor or HealthMonitor()

    def get_dashboard_data(self) -> dict[str, Any]:
        """获取完整的仪表盘数据"""
        bus = get_neuro_bus()
        dlq = get_dead_letter_queue()
        store = get_event_store()

        return {
            "timestamp": datetime.now().isoformat(),
            "health": self._monitor.get_health_summary(),
            "neuro_bus": bus.get_stats(),
            "dead_letter_queue": dlq.get_stats(),
            "event_store": store.get_stats(),
            "active_alerts": [
                {
                    "id": a.alert_id,
                    "level": a.level.value,
                    "component": a.component,
                    "message": a.message,
                    "created_at": a.created_at.isoformat(),
                }
                for a in self._monitor.get_active_alerts()
            ],
        }


# ========== 运行时接线（real FastAPI runtime wiring） ==========

# 唯一的固定、预声明自愈动作：只确保进程内单例 NeuroBus 在运行。
# action_id 为固定字面量，绝不从健康结果内容派生。
NEURO_BUS_REMEDIATION_COMPONENT = "neuro_bus"
NEURO_BUS_REMEDIATION_ACTION = "neuro_bus.ensure_running.v1"
# 专用持久化事件存储文件名（位于正常 XCAGI 用户/运行时数据根之下）
HEALTH_EVENTS_DB_NAME = "neuro_health_events.db"


async def ensure_neuro_bus_running(_result: HealthCheckResult) -> None:
    """固定、幂等的 neuro_bus 修复动作。

    只确保进程内单例 NeuroBus 正在运行；已运行则直接返回。绝不执行 shell/进程命令、
    网络请求、任意 handler 名、任意文本，也不重启整个 OS/应用。因为需要 await
    ``bus.start()``，故为异步 handler。
    """
    bus = get_neuro_bus()
    if bus.is_running:
        return
    await bus.start()


def configure_runtime_health_monitor(
    data_dir: str | os.PathLike[str] | None = None,
) -> tuple[HealthMonitor, bool]:
    """在真实 FastAPI 运行时接线单例 HealthMonitor。

    在正常 XCAGI 用户/运行时数据根（由 ``XCAGI_DATA_DIR`` 决定，绝不回落到源码树或
    cwd）下创建专用 SQLite EventStore，并把唯一的固定动作 neuro_bus.ensure_running.v1
    注册到组件 neuro_bus。

    返回 ``(monitor, durable_available)``。fail-safe：若持久化事件存储不可用，监控可
    继续，但自动修复被禁用（不注册 handler），因此绝无 recovered 声明。
    """
    from app.desktop_runtime.paths import get_desktop_data_dir

    monitor = get_health_monitor()
    # 先显式注销固定自愈动作，再尝试持久化存储构建。这样即使本次调用失败，先前已成功
    # 接线留下的 handler 也不会残留为可调用状态（单例复用前提下，避免一个进程先成功后
    # 失败时仍保留可触发的自动修复）。
    monitor.unregister_remediation(NEURO_BUS_REMEDIATION_COMPONENT)
    store: EventStore | None = None
    durable = False
    try:
        root = get_desktop_data_dir(data_dir)
        data_root = root / "data"
        data_root.mkdir(parents=True, exist_ok=True)
        store = EventStore(
            mode=EventStoreMode.SQLITE,
            storage_path=str(data_root / HEALTH_EVENTS_DB_NAME),
        )
        durable = True
    except RECOVERABLE_ERRORS:  # noqa: BLE001 - 持久化存储边界，任何失败都必须 fail-safe
        logger.warning(
            "[HealthMonitor] 持久化事件存储不可用，自动修复已禁用 (component=%s)",
            NEURO_BUS_REMEDIATION_COMPONENT,
        )
        store = None
        durable = False

    monitor.configure_event_store(store)
    if durable:
        monitor.register_remediation(
            NEURO_BUS_REMEDIATION_COMPONENT,
            NEURO_BUS_REMEDIATION_ACTION,
            ensure_neuro_bus_running,
        )
    return monitor, durable


# ========== 全局实例 ==========

_health_monitor_instance: HealthMonitor | None = None


def get_health_monitor() -> HealthMonitor:
    """获取全局健康监控器"""
    global _health_monitor_instance
    if _health_monitor_instance is None:
        _health_monitor_instance = HealthMonitor()
    return _health_monitor_instance


# 快捷函数


def get_health() -> dict[str, Any]:
    """快捷函数：获取健康状态"""
    return get_health_monitor().get_health_summary()


def check_component(component: str) -> HealthCheckResult | None:
    """快捷函数：检查组件"""
    return get_health_monitor().get_component_health(component)


def get_system_status() -> str:
    """快捷函数：获取系统状态字符串"""
    summary = get_health()
    return cast("str", summary.get("overall_status", "unknown"))
