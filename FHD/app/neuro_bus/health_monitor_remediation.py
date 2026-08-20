"""Safe remediation closed-loop and alert evaluation mixin."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from app.neuro_bus.event_store import EventStoreMode
from app.neuro_bus.events.base import EventMetadata, EventPriority, NeuroEvent
from app.neuro_bus.health_monitor_types import (
    INCIDENT_REPORTED,
    REASON_EVENT_STORE_UNAVAILABLE,
    REASON_NOT_REGISTERED,
    REASON_POSTCONDITION_UNHEALTHY,
    REASON_REMEDIATION_FAILED,
    RECOVERY_FAILED,
    RECOVERY_REPORTED,
    REMEDIATION_FAILED,
    REMEDIATION_REPORTED,
    REMEDIATION_SKIPPED,
    STATUS_EVIDENCE_UNAVAILABLE,
    Alert,
    AlertLevel,
    HealthCheckResult,
    HealthStatus,
    RemediationHandler,
    RemediationOutcome,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger("app.neuro_bus.health_monitor")


class HealthRemediationMixin:
    if TYPE_CHECKING:
        _event_store: Any | None
        _remediation_handlers: dict[str, tuple[str, RemediationHandler]]
        _open_incidents: dict[str, str]
        _remediated_incidents: set[str]
        _checks: dict[str, Callable[[], HealthCheckResult]]
        _alerts: deque
        _active_alerts: dict[str, Alert]
        _alert_callbacks: list[Callable[[Alert], None]]

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
        except RECOVERABLE_ERRORS:  # noqa: BLE001 - 事件存储边界，任何失败都必须安全降级
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
                return cast("HealthCheckResult | None", await check_fn())
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
