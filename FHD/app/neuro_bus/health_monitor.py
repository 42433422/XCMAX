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
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, cast

from app.neuro_bus.bus import get_neuro_bus
from app.neuro_bus.dead_letter_queue import get_dead_letter_queue
from app.neuro_bus.event_store import EventStore, EventStoreMode, get_event_store
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """健康状态"""

    HEALTHY = "healthy"  # 健康
    DEGRADED = "degraded"  # 降级
    UNHEALTHY = "unhealthy"  # 不健康
    UNKNOWN = "unknown"  # 未知


class AlertLevel(Enum):
    """告警级别"""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class HealthCheckResult:
    """健康检查结果"""

    component: str
    status: HealthStatus
    message: str
    latency_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=datetime.now)


# ========== 闭环自愈（safe remediation closed loop） ==========

# 结构化接收单（event_type）—— 全部为固定字符串，不携带任意数据
INCIDENT_REPORTED = "health.incident.reported"
REMEDIATION_REPORTED = "health.remediation.reported"
REMEDIATION_FAILED = "health.remediation.failed"
REMEDIATION_SKIPPED = "health.remediation.skipped"
RECOVERY_REPORTED = "health.recovery.reported"
RECOVERY_FAILED = "health.recovery.failed"

# 固定原因码 —— 绝不写入 result.details / 异常文本 / 命令 / URL / token 等任意字符串
REASON_NOT_REGISTERED = "remediation_not_registered"
REASON_REMEDIATION_FAILED = "remediation_failed"
REASON_POSTCONDITION_UNHEALTHY = "postcondition_unhealthy"
REASON_EVENT_STORE_UNAVAILABLE = "event_store_unavailable"

# 固定状态码
STATUS_EVIDENCE_UNAVAILABLE = "evidence_unavailable"

# 组件修复处理器：仅接收结构化 HealthCheckResult，同步或异步均可
RemediationHandler = Callable[[HealthCheckResult], Any]


@dataclass
class RemediationOutcome:
    """闭环自愈结果（安全、结构化、无任意字符串）"""

    component: str
    status: str  # healthy | remediation_skipped | remediation_failed | already_attempted | recovered | recovery_failed | evidence_unavailable
    incident_id: str | None
    action_id: str | None
    reason_code: str | None
    handler_invoked: bool
    recovered: bool
    durable_receipts: bool
    stream_id: str | None


@dataclass
class Alert:
    """告警"""

    alert_id: str
    level: AlertLevel
    component: str
    message: str
    created_at: datetime
    resolved_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthMonitor:
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

    def _register_default_checks(self):
        """注册默认健康检查"""
        self.register_check("neuro_bus", self._check_neuro_bus)
        self.register_check("event_queue", self._check_event_queue)
        self.register_check("memory", self._check_memory)

    # ========== 健康检查注册 ==========

    def register_check(self, name: str, check_fn: Callable[[], HealthCheckResult]):
        """注册健康检查"""
        self._checks[name] = check_fn
        self._metrics_history[name] = deque(maxlen=100)
        logger.info("[HealthMonitor] 注册检查: %s", name)

    def unregister_check(self, name: str):
        """注销健康检查"""
        if name in self._checks:
            del self._checks[name]
            self._last_results.pop(name, None)
            del self._metrics_history[name]

    # ========== 健康检查实现 ==========

    def _check_neuro_bus(self) -> HealthCheckResult:
        """检查 NeuroBus 状态"""
        t0 = time.perf_counter()

        try:
            bus = get_neuro_bus()
            stats = bus.get_stats()

            latency_ms = (time.perf_counter() - t0) * 1000

            # 判断状态
            if not stats.get("running"):
                status = HealthStatus.UNHEALTHY
                message = "NeuroBus 未运行"
            elif stats.get("queue_size", 0) > 5000:
                status = HealthStatus.DEGRADED
                message = f"队列积压: {stats['queue_size']}"
            elif stats.get("errors", 0) > stats.get("processed", 1) * 0.1:
                status = HealthStatus.DEGRADED
                message = f"错误率过高: {stats['errors']}/{stats.get('processed', 0)}"
            else:
                status = HealthStatus.HEALTHY
                message = "NeuroBus 运行正常"

            return HealthCheckResult(
                component="neuro_bus",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details=stats,
            )

        except RECOVERABLE_ERRORS as e:
            return HealthCheckResult(
                component="neuro_bus",
                status=HealthStatus.UNHEALTHY,
                message=f"检查失败: {str(e)}",
                latency_ms=(time.perf_counter() - t0) * 1000,
                details={"error": str(e)},
            )

    def _check_event_queue(self) -> HealthCheckResult:
        """检查事件队列状态"""
        t0 = time.perf_counter()

        try:
            bus = get_neuro_bus()
            stats = bus.get_stats()
            queue_size = stats.get("queue_size", 0)
            dropped = stats.get("dropped", 0)

            latency_ms = (time.perf_counter() - t0) * 1000

            if queue_size > 8000:
                status = HealthStatus.UNHEALTHY
                message = f"队列严重积压: {queue_size}"
            elif queue_size > 5000:
                status = HealthStatus.DEGRADED
                message = f"队列积压: {queue_size}"
            elif dropped > 100:
                status = HealthStatus.DEGRADED
                message = f"事件丢弃过多: {dropped}"
            else:
                status = HealthStatus.HEALTHY
                message = f"队列正常: {queue_size}"

            return HealthCheckResult(
                component="event_queue",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details={
                    "queue_size": queue_size,
                    "dropped": dropped,
                },
            )

        except RECOVERABLE_ERRORS as e:
            return HealthCheckResult(
                component="event_queue",
                status=HealthStatus.UNHEALTHY,
                message=f"检查失败: {str(e)}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    def _check_memory(self) -> HealthCheckResult:
        """检查内存使用"""
        t0 = time.perf_counter()

        try:
            import psutil

            process = psutil.Process()
            memory_mb = process.memory_info().rss / 1024 / 1024

            latency_ms = (time.perf_counter() - t0) * 1000

            if memory_mb > 1024:  # 1GB
                status = HealthStatus.DEGRADED
                message = f"内存使用较高: {memory_mb:.1f}MB"
            else:
                status = HealthStatus.HEALTHY
                message = f"内存使用正常: {memory_mb:.1f}MB"

            return HealthCheckResult(
                component="memory",
                status=status,
                message=message,
                latency_ms=latency_ms,
                details={"memory_mb": memory_mb},
            )

        except ImportError:
            return HealthCheckResult(
                component="memory",
                status=HealthStatus.UNKNOWN,
                message="无法检查（psutil 未安装）",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )
        except RECOVERABLE_ERRORS as e:
            return HealthCheckResult(
                component="memory",
                status=HealthStatus.UNHEALTHY,
                message=f"检查失败: {str(e)}",
                latency_ms=(time.perf_counter() - t0) * 1000,
            )

    # ========== 检查执行 ==========

    async def run_check(self, name: str) -> HealthCheckResult | None:
        """运行单个检查"""
        check_fn = self._checks.get(name)
        if not check_fn:
            return None

        try:
            # 支持异步和同步检查
            if asyncio.iscoroutinefunction(check_fn):
                result = await check_fn()
            else:
                result = check_fn()

            self._last_results[name] = result
            self._metrics_history[name].append(result)

            # 检查是否需要告警
            self._evaluate_alert(result)

            # 自动驱动闭环：对所有结果调用闭环方法，使其自动处理非健康结果
            # （执行已注册的修复处理器、强制后置条件复查、写接收单），并在健康时解除未决 incident。
            # 后置条件复查复用 `_run_postcondition_check`，绝不在此递归调用 run_check。
            await self.run_remediation_closed_loop(result)

            return cast("HealthCheckResult | None", result)

        except RECOVERABLE_ERRORS as e:
            logger.error("[HealthMonitor] 检查失败 %s: %s", name, e)
            return None

    async def run_all_checks(self) -> dict[str, HealthCheckResult]:
        """运行所有检查"""
        results = {}

        for name in self._checks:
            result = await self.run_check(name)
            if result:
                results[name] = result

        return results

    # ========== 闭环自愈（remediation closed loop） ==========

    def register_remediation(
        self, component: str, action_id: str, handler: RemediationHandler
    ) -> None:
        """注册组件修复处理器。

        仅接受调用方显式注册的 (component, action_id)。处理器的输入只能是结构化的
        HealthCheckResult，同步或异步均可；绝不根据健康结果文本派生或执行任意内容。
        """
        self._remediation_handlers[component] = (action_id, handler)
        logger.info(
            "[HealthMonitor] 注册修复处理器: component=%s action_id=%s", component, action_id
        )

    def unregister_remediation(self, component: str) -> None:
        """注销组件修复处理器。"""
        self._remediation_handlers.pop(component, None)

    def has_remediation(self, component: str) -> bool:
        """是否存在该组件的修复处理器（精确组件匹配）。"""
        return component in self._remediation_handlers

    def configure_event_store(self, event_store: Any | None) -> None:
        """设置闭环接收单使用的事件存储（运行时接线用）。

        指向数据根下的专用持久化 EventStore。传入 None 表示禁用持久化证据
        （fail-safe：绝不产生 recovered 声明）。
        """
        self._event_store = event_store

    def _store_durable(self) -> bool:
        """事件存储是否为持久化（durable）证据。

        仅 SQLITE 模式视为 durable；MEMORY / JSON_FILE 或未注入事件存储一律视为非 durable。
        通过存储内部模式判定，不依赖 EventStore 上的任何公开 durable 属性。
        """
        store = self._event_store
        if store is None:
            return False
        return getattr(store, "_mode", None) == EventStoreMode.SQLITE

    @staticmethod
    def _stream_id_for(component: str, incident_id: str) -> str:
        return f"health-closed-loop:{component}:{incident_id}"

    def _emit_receipt(
        self,
        incident_id: str,
        component: str,
        event_type: str,
        *,
        status: str | None = None,
        reason_code: str | None = None,
        action_id: str | None = None,
    ) -> bool:
        """写入一条安全的结构化接收单（receipt）。

        payload 仅含固定字段（incident_id / component / stage / status / reason_code /
        durable / action_id / stream_id），绝不写入 result.details、异常文本、handler 输出、
        命令、URL、token 等任意字符串。存储失败不影响健康检查，且不抛出。

        事件存储是闭环证据的外部边界：append 的任何失败（无论异常类型）都必须被吞掉并
        转换为 fail-safe 结果，绝不向调用方抛出，也绝不把异常文本写进日志或接收单 ——
        这保证外部存储的原始异常细节（可能含密钥/URL 等）不会泄漏。
        """
        store = self._event_store
        if store is None:
            return False
        stream_id = self._stream_id_for(component, incident_id)
        durable = self._store_durable()
        payload: dict[str, Any] = {
            "incident_id": incident_id,
            "component": component,
            "stage": event_type,
            "status": status,
            "reason_code": reason_code,
            "durable": durable,
            "action_id": action_id,
            "stream_id": stream_id,
        }
        try:
            event = NeuroEvent(
                event_type=event_type,
                payload=payload,
                priority=EventPriority.LOW,
                metadata=EventMetadata(source="health_monitor", domain="health"),
            )
            store.append(event, stream_id=stream_id)
            return True
        # 存储边界 fail-safe：任何 append 失败都不得使健康检查崩溃或泄漏原始细节
        except Exception:  # noqa: BLE001 - 事件存储边界，任何失败都必须安全降级
            # 仅记录固定组件名，绝不记录异常文本 / 类型 / 消息，防止原始细节泄漏
            logger.error("[HealthMonitor] 事件存储写入失败 (component=%s)", component)
            return False

    def _get_or_create_incident(self, component: str) -> str:
        existing = self._open_incidents.get(component)
        if existing is not None:
            return existing
        incident_id = f"inc-{uuid.uuid4().hex[:12]}"
        self._open_incidents[component] = incident_id
        return incident_id

    def _store_unavailable_outcome(
        self,
        component: str,
        incident_id: str,
        action_id: str | None,
        stream_id: str,
        *,
        handler_invoked: bool,
    ) -> RemediationOutcome:
        """事件存储缺失 / 写接收单失败时的 fail-safe 结果：绝不报告恢复。

        仅返回结构化字段与固定原因码，绝不携带原始存储异常文本。
        """
        return RemediationOutcome(
            component=component,
            status=STATUS_EVIDENCE_UNAVAILABLE,
            incident_id=incident_id,
            action_id=action_id,
            reason_code=REASON_EVENT_STORE_UNAVAILABLE,
            handler_invoked=handler_invoked,
            recovered=False,
            durable_receipts=self._store_durable(),
            stream_id=stream_id,
        )

    async def _run_postcondition_check(self, component: str) -> HealthCheckResult | None:
        """强制后置条件复查：重跑该组件的健康检查，确认是否已恢复 HEALTHY。"""
        check_fn = self._checks.get(component)
        if check_fn is None:
            return None
        try:
            if asyncio.iscoroutinefunction(check_fn):
                return await check_fn()
            return cast("HealthCheckResult | None", check_fn())
        except RECOVERABLE_ERRORS:
            logger.error("[HealthMonitor] 后置条件复查失败 (component=%s)", component)
            return None

    async def run_remediation_closed_loop(self, result: HealthCheckResult) -> RemediationOutcome:
        """对一次非健康检查结果执行安全闭环自愈。

        流程：非健康 -> 自动化前置门（事件存储必须可用且能写接收单，否则 fail safe，
        不调用 handler、不报告恢复）-> 仅调用预先注册的组件修复处理器 -> 强制后置条件复查 ->
        仅在复查 HEALTHY 时报告恢复，否则报告恢复失败。同一未决 incident 至多执行一次
        handler；观测到健康会解除未决 incident，使后续新 incident 可再次尝试。

        任何 handler / 事件存储错误都不会使健康检查崩溃，且绝不凭空声称已恢复。
        """
        component = result.component

        # 健康结果：解除未决 incident，允许后续新 incident 再次尝试
        if result.status == HealthStatus.HEALTHY:
            self._open_incidents.pop(component, None)
            return RemediationOutcome(
                component=component,
                status="healthy",
                incident_id=None,
                action_id=None,
                reason_code=None,
                handler_invoked=False,
                recovered=True,
                durable_receipts=self._store_durable(),
                stream_id=None,
            )

        entry = self._remediation_handlers.get(component)
        incident_id = self._get_or_create_incident(component)
        stream_id = self._stream_id_for(component, incident_id)

        # 未注册 / 未知组件：绝不调用任何 handler
        if entry is None:
            self._emit_receipt(
                incident_id, component, INCIDENT_REPORTED, status="incident_reported"
            )
            self._emit_receipt(
                incident_id,
                component,
                REMEDIATION_SKIPPED,
                status="remediation_skipped",
                reason_code=REASON_NOT_REGISTERED,
            )
            self._open_incidents.pop(component, None)
            return RemediationOutcome(
                component=component,
                status="remediation_skipped",
                incident_id=incident_id,
                action_id=None,
                reason_code=REASON_NOT_REGISTERED,
                handler_invoked=False,
                recovered=False,
                durable_receipts=self._store_durable(),
                stream_id=stream_id,
            )

        action_id, handler = entry

        # 至少一次：同一未决 incident 不重复执行 handler
        if incident_id in self._remediated_incidents:
            return RemediationOutcome(
                component=component,
                status="already_attempted",
                incident_id=incident_id,
                action_id=action_id,
                reason_code=None,
                handler_invoked=False,
                recovered=False,
                durable_receipts=self._store_durable(),
                stream_id=stream_id,
            )

        # 自动化前置门（fail safe before automation）：
        # 事件存储缺失或写接收单失败 -> 不调用 handler、不报告恢复
        if not self._emit_receipt(
            incident_id,
            component,
            INCIDENT_REPORTED,
            status="incident_reported",
            action_id=action_id,
        ):
            # 尚未自动化，不标记为已修复，允许后续存储恢复后重试
            self._open_incidents.pop(component, None)
            return self._store_unavailable_outcome(
                component, incident_id, action_id, stream_id, handler_invoked=False
            )

        self._remediated_incidents.add(incident_id)

        # 调用 handler（同步或异步），仅传入结构化结果
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler(result)
            else:
                handler(result)
        except RECOVERABLE_ERRORS:
            logger.error("[HealthMonitor] 修复处理器失败 (component=%s)", component)
            self._emit_receipt(
                incident_id,
                component,
                REMEDIATION_FAILED,
                status="remediation_failed",
                reason_code=REASON_REMEDIATION_FAILED,
                action_id=action_id,
            )
            # incident 保持未决（至少一次），且绝不声称恢复
            return RemediationOutcome(
                component=component,
                status="remediation_failed",
                incident_id=incident_id,
                action_id=action_id,
                reason_code=REASON_REMEDIATION_FAILED,
                handler_invoked=True,
                recovered=False,
                durable_receipts=self._store_durable(),
                stream_id=stream_id,
            )

        if not self._emit_receipt(
            incident_id,
            component,
            REMEDIATION_REPORTED,
            status="remediation_reported",
            action_id=action_id,
        ):
            # 无法写接收单 -> fail safe（handler 已执行，但绝不报告恢复）
            return self._store_unavailable_outcome(
                component, incident_id, action_id, stream_id, handler_invoked=True
            )

        # 强制后置条件复查：仅当复查 HEALTHY 才报告恢复
        post = await self._run_postcondition_check(component)
        if post is not None and post.status == HealthStatus.HEALTHY:
            if not self._emit_receipt(
                incident_id,
                component,
                RECOVERY_REPORTED,
                status="recovered",
                action_id=action_id,
            ):
                # 无法写恢复接收单 -> fail safe，绝不报告恢复
                return self._store_unavailable_outcome(
                    component, incident_id, action_id, stream_id, handler_invoked=True
                )
            self._open_incidents.pop(component, None)
            return RemediationOutcome(
                component=component,
                status="recovered",
                incident_id=incident_id,
                action_id=action_id,
                reason_code=None,
                handler_invoked=True,
                recovered=True,
                durable_receipts=self._store_durable(),
                stream_id=stream_id,
            )

        if not self._emit_receipt(
            incident_id,
            component,
            RECOVERY_FAILED,
            status="recovery_failed",
            reason_code=REASON_POSTCONDITION_UNHEALTHY,
            action_id=action_id,
        ):
            return self._store_unavailable_outcome(
                component, incident_id, action_id, stream_id, handler_invoked=True
            )
        # incident 保持未决（至少一次），且绝不声称恢复
        return RemediationOutcome(
            component=component,
            status="recovery_failed",
            incident_id=incident_id,
            action_id=action_id,
            reason_code=REASON_POSTCONDITION_UNHEALTHY,
            handler_invoked=True,
            recovered=False,
            durable_receipts=self._store_durable(),
            stream_id=stream_id,
        )

    def _evaluate_alert(self, result: HealthCheckResult):
        """评估是否需要告警"""
        if result.status == HealthStatus.HEALTHY:
            # 检查是否恢复
            self._resolve_alert_if_exists(result.component)
            return

        # 生成告警
        level = (
            AlertLevel.WARNING if result.status == HealthStatus.DEGRADED else AlertLevel.CRITICAL
        )

        alert_id = f"alert-{result.component}-{int(time.time())}"

        alert = Alert(
            alert_id=alert_id,
            level=level,
            component=result.component,
            message=result.message,
            created_at=datetime.now(),
            metadata={
                "latency_ms": result.latency_ms,
                "details": result.details,
            },
        )

        self._alerts.append(alert)
        self._active_alerts[result.component] = alert

        # 触发告警回调
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except RECOVERABLE_ERRORS as e:
                logger.error("[HealthMonitor] 告警回调失败: %s", e)

        logger.warning(
            "[HealthMonitor] 告警: [%s] %s - %s", level.value, result.component, result.message
        )

    def _resolve_alert_if_exists(self, component: str):
        """解决告警"""
        if component in self._active_alerts:
            alert = self._active_alerts[component]
            alert.resolved_at = datetime.now()
            del self._active_alerts[component]

            logger.info("[HealthMonitor] 告警已解决: %s", component)

    # ========== 监控循环 ==========

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
    except Exception:  # noqa: BLE001 - 持久化存储边界，任何失败都必须 fail-safe
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
