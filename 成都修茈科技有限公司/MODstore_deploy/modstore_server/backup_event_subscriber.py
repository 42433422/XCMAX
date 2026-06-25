"""备份事件订阅者：把 incident_bus 上的 backup.* 事件翻译成下游可消费的副作用。

目的：解耦 BK→R 硬边，让下游（03:15 归档、08:00 摘要、08:15 Phase A）可以
**异步**消费 backup 事件，无需阻塞等待备份同步完成。

事件类型：
- ``backup.completed``           —— 定时备份成功（最常见）
- ``backup.failed``              —— 定时备份失败（DRFAIL 降级）
- ``backup.ondemand_completed``  —— 按需快照成功（交叉升级/回滚触发）
- ``backup.ondemand_failed``     —— 按需快照失败
- ``backup.dr_guard.cleared``    —— DR 守卫自动解除（探针恢复成功）
- ``backup.dr_guard.escalated``  —— DR 守卫升级告警（重试超限）

调用方式：
- 在 ``app_factory`` 启动时调用 ``register_backup_event_subscribers()`` 一次性注册；
- 也可在测试中显式调用 ``dispatch_backup_event(event_type, payload)`` 模拟事件。

设计：best-effort，下游副作用（发布 retention-janitor kick、提前启动 R 等）
失败不应回滚事件；事件本身已写入 IncidentEvent（10 分钟去重窗），副作用失败
只记日志，不重新触发。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

_BACKUP_EVENT_TYPES = frozenset(
    {
        "backup.completed",
        "backup.failed",
        "backup.ondemand_completed",
        "backup.ondemand_failed",
        "backup.dr_guard.cleared",
        "backup.dr_guard.escalated",
    }
)


def _kick_retention_janitor() -> Dict[str, Any]:
    """备份成功后提前启动 03:15 归档（解耦 BK→R 硬边）。

    03:15 归档原本是 CronTrigger 03:15 定时触发，备份完 03:05 后归档要再等 10 分钟。
    启用事件信号后，备份完成事件触发时可立即启动归档任务，前置 10 分钟时间窗口。
    """
    try:
        from modstore_server.file_retention_janitor import run_retention_janitor

        out = run_retention_janitor()
        logger.info(
            "backup event subscriber: retention janitor kicked ok=%s status=%s",
            out.get("ok"),
            out.get("status"),
        )
        return {"ok": True, "result": out}
    except Exception as exc:  # noqa: BLE001
        logger.exception("backup event subscriber: kick retention janitor failed")
        return {"ok": False, "error": str(exc)[:300]}


def _publish_digest_prewarm() -> Dict[str, Any]:
    """备份成功时发出 digest pre-warm 信号，08:00 摘要任务可提前准备上下文。"""
    try:
        from modstore_server.incident_bus import publish

        published = publish(
            "schedule.tick",
            {
                "kind": "backup_completed_prewarm",
                "at": datetime.now(timezone.utc).isoformat(),
                "hint": "digest 08:00 可提前准备上下文（备份链已就绪）",
            },
            source="backup-event-subscriber",
        )
        return {"ok": True, "published": bool(published)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("backup event subscriber: publish digest prewarm failed")
        return {"ok": False, "error": str(exc)[:300]}


def _handle_completed(payload: Dict[str, Any]) -> Dict[str, Any]:
    """backup.completed / backup.ondemand_completed 通用处理。"""
    out: Dict[str, Any] = {"handlers": []}
    trigger = str(payload.get("trigger") or "scheduled")
    is_ondemand = trigger != "scheduled"

    if not is_ondemand:
        # 定时备份完成 → 提前启动归档（解耦 BK→R 硬边）
        out["handlers"].append({"name": "retention_janitor_kick", **_kick_retention_janitor()})
        out["handlers"].append({"name": "digest_prewarm", **_publish_digest_prewarm()})
    else:
        # 按需快照完成（交叉升级/回滚触发）→ 记录审计点
        logger.info(
            "backup event subscriber: ondemand backup completed reason=%s trigger=%s stamp=%s",
            payload.get("reason"),
            trigger,
            payload.get("stamp"),
        )
        out["handlers"].append({"name": "ondemand_audit_log", "ok": True})
    return out


def _handle_failed(payload: Dict[str, Any]) -> Dict[str, Any]:
    """backup.failed / backup.ondemand_failed 通用处理。

    根据 trigger 字段区分场景，避免告警标题误导：
    - ``auto_rollback`` 触发 → "盲回滚警告"
    - 其他触发（manual / O7_feedback / cross_upgrade 等）→ 通用告警
    """
    is_ondemand = str(payload.get("trigger") or "scheduled") != "scheduled"
    if is_ondemand:
        trigger = str(payload.get("trigger") or "")
        is_auto_rollback = "auto_rollback" in trigger
        title = (
            "按需快照失败 · auto_rollback 盲回滚警告"
            if is_auto_rollback
            else f"按需快照失败 · 触发来源={trigger} · 灾备异常"
        )
        action = (
            "下游应检查磁盘/权限；考虑暂停回滚或人工介入"
            if is_auto_rollback
            else "下游应检查磁盘/权限/源库状态；可能需人工介入"
        )
        try:
            from modstore_server.incident_bus import publish

            publish(
                "log.anomaly",
                {
                    "title": title,
                    "level": "warning",
                    "reason": payload.get("reason"),
                    "trigger": trigger,
                    "stamp": payload.get("stamp"),
                    "db_error": (payload.get("db") or {}).get("error"),
                    "rt_error": (payload.get("release_train") or {}).get("error"),
                    "action": action,
                },
                source="backup-event-subscriber",
            )
        except Exception:  # noqa: BLE001
            logger.exception("backup event subscriber: ondemand failed alert failed")
    return {"ok": True, "handlers": ["log_anomaly_published"]}


def _handle_dr_guard_cleared(payload: Dict[str, Any]) -> Dict[str, Any]:
    """DR 守卫自动解除 → 通知调度器日更可恢复。"""
    try:
        from modstore_server.incident_bus import publish

        publish(
            "schedule.tick",
            {
                "kind": "dr_guard_cleared",
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": payload.get("reason") or "auto_recovery",
            },
            source="backup-event-subscriber",
        )
    except Exception:
        logger.exception("backup event subscriber: dr_guard.cleared publish failed")
    return {"ok": True}


def _handle_dr_guard_escalated(payload: Dict[str, Any]) -> Dict[str, Any]:
    """DR 守卫升级告警 → 推送升级到工作台/邮件（已有 incident_bus.log.anomaly 路径，
    此处作为可观测点记录事件链）。"""
    logger.warning(
        "backup event subscriber: dr_guard escalated retry=%s max=%s reason=%s",
        payload.get("retry_count"),
        payload.get("max_retries"),
        payload.get("reason"),
    )
    return {"ok": True}


def emit_backup_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """写入 incident 审计并立即执行 backup.* 副作用（不依赖 catalog 员工包）。"""
    dispatch_result = dispatch_backup_event(event_type, payload)
    published = False
    try:
        from modstore_server.incident_bus import publish

        published = bool(
            publish(
                event_type,
                payload if isinstance(payload, dict) else {},
                source=str(payload.get("source") or "backup-pipeline"),
            )
        )
    except Exception:  # noqa: BLE001
        logger.exception("emit_backup_event: incident publish failed event_type=%s", event_type)
    return {"dispatch": dispatch_result, "published": published}


def dispatch_backup_event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """派发 backup.* 事件到对应 handler。

    测试或外部调用方都可以用。incident_bus.publish 写完 IncidentEvent 后，
    不需要再走 _dispatch_incident（避免双发员工任务），由本函数直接执行副作用。

    幂等性：v2.5 起 ondemand 路径会同时发 ``backup.ondemand_completed`` 和
    ``backup.completed``（后者为了让只订通用事件的下游也能被唤起）——同一份
    payload 走两遍 handler 会造成 audit log 等副作用双触发。这里按 trigger
    字段去重：若 ``backup.completed`` 的 trigger 已是 ondemand，跳过第二次派发。
    """
    if event_type not in _BACKUP_EVENT_TYPES:
        return {"ok": False, "skipped": True, "reason": f"unknown event_type={event_type}"}

    # 桥接事件去重：backup.ondemand_completed 已处理过的 payload 不再走 backup.completed
    if event_type == "backup.completed" and str(payload.get("trigger") or "") != "scheduled":
        return {
            "ok": True,
            "skipped": True,
            "reason": "backup.completed with ondemand trigger already handled by backup.ondemand_completed",
        }

    try:
        if event_type in ("backup.completed", "backup.ondemand_completed"):
            return {"ok": True, "handler": "completed", **_handle_completed(payload)}
        if event_type in ("backup.failed", "backup.ondemand_failed"):
            return {"ok": True, "handler": "failed", **_handle_failed(payload)}
        if event_type == "backup.dr_guard.cleared":
            return {"ok": True, "handler": "dr_guard_cleared", **_handle_dr_guard_cleared(payload)}
        if event_type == "backup.dr_guard.escalated":
            return {
                "ok": True,
                "handler": "dr_guard_escalated",
                **_handle_dr_guard_escalated(payload),
            }
        return {"ok": False, "skipped": True, "reason": "unhandled"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("dispatch_backup_event failed event_type=%s", event_type)
        return {"ok": False, "error": str(exc)[:300]}


def register_backup_event_subscribers() -> int:
    """注册 backup.* 事件订阅者到 incident_bus。

    实现方式：把每个 backup.* 事件类型映射到一个 stub 员工触发绑定，
    该绑定在派发时调用 ``dispatch_backup_event`` 执行副作用。

    Returns 注册数量。
    """
    try:
        from modstore_server.models import EmployeeTriggerBinding, get_session_factory
    except Exception:  # noqa: BLE001
        logger.exception("register_backup_event_subscribers: import models failed")
        return 0

    n = 0
    sf = get_session_factory()
    with sf() as session:
        for ev_type in _BACKUP_EVENT_TYPES:
            row = (
                session.query(EmployeeTriggerBinding)
                .filter(EmployeeTriggerBinding.employee_id == "backup-event-subscriber")
                .filter(EmployeeTriggerBinding.event_type == ev_type)
                .first()
            )
            if row:
                row.is_active = True
                row.priority = 0  # 最高优先级，让备份事件先于其他员工任务派发
            else:
                session.add(
                    EmployeeTriggerBinding(
                        employee_id="backup-event-subscriber",
                        event_type=ev_type,
                        is_active=True,
                        priority=0,
                    )
                )
            n += 1
        session.commit()
    logger.info("backup event subscribers registered: %d", n)
    return n
