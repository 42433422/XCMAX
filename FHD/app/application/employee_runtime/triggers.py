# -*- coding: utf-8 -*-
"""员工 NeuroBus 触发器：manifest.triggers → 动态 subscribe → EmployeeAgent.run。

在 ``refresh_employee_pack_runtime`` / 启动预热时扫描已安装员工包，
对声明了 ``on_error`` / ``on_quality_fail`` / ``on_coverage_miss`` 的包
订阅对应标准事件（见 ``app.domain.employee.events``），事件到达时调用
:class:`EmployeeAgent` 执行 remediation 任务。

过滤规则：仅当 event.payload.employee_id 为空（全局）或等于本员工 id 时触发，
避免所有 on_error 员工对无关失败事件集体响应。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.application.employee_runtime.loader import list_installed_pack_records
from app.domain.employee.events import (
    EVENT_COVERAGE_MISSED,
    EVENT_QUALITY_FAILED,
    EVENT_TASK_FAILED,
)
from app.domain.employee.trigger_binding import TriggerBinding
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# employee_id -> list[(event_type, subscription)]

_ACTIVE_SUBSCRIPTIONS: dict[str, list[tuple[str, Any]]] = {}


def _event_matches_employee(event: Any, employee_id: str) -> bool:
    payload = getattr(event, "payload", None) or {}
    if not isinstance(payload, dict):
        return True
    target = str(payload.get("employee_id") or payload.get("target_employee") or "").strip()
    if not target:
        return True
    return target == employee_id


def _make_handler(employee_id: str, binding: TriggerBinding):
    async def _async_handler(event: Any) -> None:
        if not _event_matches_employee(event, employee_id):
            return
        payload = dict(getattr(event, "payload", None) or {})
        payload.setdefault("trigger_event", getattr(event, "event_type", ""))
        payload.setdefault("employee_id", employee_id)
        task = str(
            payload.get("task")
            or payload.get("message")
            or f"事件触发 remediation：{getattr(event, 'event_type', '')}"
        )
        try:
            from app.application.employee_runtime.agent import EmployeeAgent
            from app.application.employee_runtime.metrics import record_employee_trigger

            record_employee_trigger(employee_id, getattr(event, "event_type", ""))
            result = await asyncio.to_thread(
                EmployeeAgent(employee_id).run,
                task,
                payload,
                user_id=int(payload.get("user_id") or 0),
                workspace_root=payload.get("workspace_root"),
                session_id=payload.get("session_id"),
            )
            logger.info(
                "employee trigger handled emp=%s event=%s success=%s",
                employee_id,
                getattr(event, "event_type", ""),
                result.get("success"),
            )
        except RECOVERABLE_ERRORS:
            logger.exception(
                "employee trigger failed emp=%s event=%s",
                employee_id,
                getattr(event, "event_type", ""),
            )

    def _sync_handler(event: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_async_handler(event))
        except RuntimeError:
            asyncio.run(_async_handler(event))

    return _sync_handler


def _unsubscribe_employee(bus: Any, employee_id: str) -> None:
    for _event_type, sub in _ACTIVE_SUBSCRIPTIONS.pop(employee_id, []):
        try:
            bus.unsubscribe(sub)
        except RECOVERABLE_ERRORS:
            logger.debug("unsubscribe failed emp=%s", employee_id, exc_info=True)


def refresh_employee_triggers(pack_id: str | None = None) -> dict[str, Any]:
    """扫描已安装员工包并（重新）注册 NeuroBus 触发订阅。"""
    try:
        from app.neuro_bus.bus import get_neuro_bus

        bus = get_neuro_bus()
    except RECOVERABLE_ERRORS as exc:
        logger.debug("refresh_employee_triggers: NeuroBus unavailable: %s", exc)
        return {"registered": [], "error": str(exc)[:200]}

    pid_filter = str(pack_id or "").strip()
    registered: list[dict[str, Any]] = []

    for pack in list_installed_pack_records():
        manifest = pack.get("manifest") or {}
        eid = str(pack.get("pack_id") or manifest.get("id") or "").strip()
        if not eid:
            continue
        if pid_filter and eid != pid_filter:
            continue

        _unsubscribe_employee(bus, eid)
        binding = TriggerBinding.from_manifest(eid, manifest)
        if not binding.active:
            continue

        subs: list[tuple[str, Any]] = []
        for event_type in binding.event_types:
            handler = _make_handler(eid, binding)
            sub = bus.subscribe(
                event_type,
                handler,
                priority=5,
                is_async=False,
                filter_fn=lambda ev, emp=eid: _event_matches_employee(ev, emp),
            )
            subs.append((event_type, sub))
            registered.append({"employee_id": eid, "event_type": event_type})

        if subs:
            _ACTIVE_SUBSCRIPTIONS[eid] = subs
            logger.info(
                "employee triggers registered emp=%s events=%s",
                eid,
                [e for e, _ in subs],
            )

    return {
        "registered": registered,
        "active_employees": list(_ACTIVE_SUBSCRIPTIONS.keys()),
        "event_types": sorted(
            {e for subs in _ACTIVE_SUBSCRIPTIONS.values() for e, _ in subs}
        ),
    }


def publish_employee_task_failed(
    employee_id: str,
    *,
    task: str = "",
    message: str = "",
    extra: dict[str, Any] | None = None,
) -> bool:
    """辅助：发布员工任务失败事件（供 executor / 外部调用）。"""
    try:
        from app.neuro_bus.bus import get_neuro_bus
        from app.neuro_bus.events.base import NeuroEvent

        payload = dict(extra or {})
        payload.update(
            {
                "employee_id": employee_id,
                "task": task,
                "message": message,
            }
        )
        return bool(get_neuro_bus().publish(NeuroEvent(EVENT_TASK_FAILED, payload)))
    except RECOVERABLE_ERRORS:
        logger.debug("publish_employee_task_failed skipped", exc_info=True)
        return False


__all__ = [
    "EVENT_COVERAGE_MISSED",
    "EVENT_QUALITY_FAILED",
    "EVENT_TASK_FAILED",
    "publish_employee_task_failed",
    "refresh_employee_triggers",
]
