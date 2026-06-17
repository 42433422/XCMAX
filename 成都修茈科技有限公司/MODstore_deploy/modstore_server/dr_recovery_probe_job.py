"""DR 恢复探针：备份失败后每 30 分钟重试，最多 8 次。

对齐时间轨 DRPROBE 节点：守卫生效期间周期性调用 ``run_daily_backup_job``，
成功则 ``clear_backup_guard`` 并派发 ``backup.dr_guard.cleared``；
超限则 ``backup.dr_guard.escalated`` + ``log.anomaly`` 升级告警。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return (os.environ.get("MODSTORE_DR_PROBE_ENABLED", "1") or "").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _max_retries() -> int:
    try:
        return max(1, int(os.environ.get("MODSTORE_DR_PROBE_MAX_RETRIES", "8")))
    except ValueError:
        return 8


def _record_dr_probe_runtime(result: Dict[str, Any]) -> None:
    if result.get("skipped"):
        return
    try:
        from modstore_server.time_rail_runtime import record_node_run

        record_node_run(
            "DRPROBE",
            ok=bool(result.get("ok")) or bool(result.get("recovered")),
            source="dr_recovery_probe_job",
            meta={
                "probe_retry_count": result.get("probe_retry_count"),
                "escalated": result.get("escalated"),
                "recovered": result.get("recovered"),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("dr recovery probe: time_rail runtime record failed")


def run_dr_recovery_probe() -> Dict[str, Any]:
    """执行一次 DR 恢复探针（由 workflow_scheduler 每 30min 调度）。"""
    if not _enabled():
        return {"ok": True, "skipped": True, "reason": "MODSTORE_DR_PROBE_ENABLED=0"}

    from modstore_server.release_train import (
        active_backup_guard,
        load_state,
        record_backup_guard_probe_attempt,
    )

    guard = active_backup_guard()
    if not guard:
        # 兼容历史/离线场景：若当天没有命中，但 state 内确有守卫，则仍按该守卫继续处理
        # 避免因用例/环境日历日差异导致探针永远不触发。
        state = load_state()
        fallback_guard = state.get("backup_guard")
        if isinstance(fallback_guard, dict):
            guard = active_backup_guard(day=fallback_guard.get("day"), state=state)
    if not guard:
        return {"ok": True, "skipped": True, "reason": "no_active_guard"}

    retry = int(guard.get("probe_retry_count") or 0)
    max_retries = _max_retries()
    if retry >= max_retries:
        if guard.get("probe_escalated"):
            return {
                "ok": True,
                "skipped": True,
                "reason": "already_escalated",
                "probe_retry_count": retry,
                "max_retries": max_retries,
            }
        result = _escalate(guard, retry, max_retries)
        _record_dr_probe_runtime(result)
        return result

    from modstore_server.daily_backup_job import run_daily_backup_job

    out = run_daily_backup_job(from_probe=True)
    if out.get("ok"):
        from modstore_server.backup_event_subscriber import emit_backup_event

        emit_backup_event(
            "backup.dr_guard.cleared",
            {
                "reason": "dr_recovery_probe",
                "probe_retry_count": retry,
                "stamp": out.get("stamp"),
                "backup_dir": out.get("backup_dir"),
            },
        )
        logger.info(
            "dr recovery probe succeeded after %d retries stamp=%s",
            retry,
            out.get("stamp"),
        )
        result = {
            "ok": True,
            "recovered": True,
            "probe_retry_count": retry,
            "backup": out,
        }
        _record_dr_probe_runtime(result)
        return result

    probe_meta = record_backup_guard_probe_attempt(success=False)
    new_retry = int(probe_meta.get("probe_retry_count") or retry + 1)
    logger.warning(
        "dr recovery probe failed attempt=%d/%d stamp=%s",
        new_retry,
        max_retries,
        out.get("stamp"),
    )
    if new_retry >= max_retries:
        result = _escalate(guard, new_retry, max_retries, backup_out=out)
        result["backup"] = out
        _record_dr_probe_runtime(result)
        return result

    result = {
        "ok": False,
        "recovered": False,
        "probe_retry_count": new_retry,
        "max_retries": max_retries,
        "backup": out,
    }
    _record_dr_probe_runtime(result)
    return result


def _escalate(
    guard: Dict[str, Any],
    retry: int,
    max_retries: int,
    *,
    backup_out: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    from modstore_server.backup_event_subscriber import emit_backup_event
    from modstore_server.release_train import mark_backup_guard_probe_escalated

    mark_backup_guard_probe_escalated()
    payload = {
        "reason": guard.get("reason") or "backup_failed",
        "retry_count": retry,
        "max_retries": max_retries,
        "guard_day": guard.get("day"),
        "backup": backup_out,
    }
    emit_backup_event("backup.dr_guard.escalated", payload)
    try:
        from modstore_server.incident_bus import publish

        publish(
            "log.anomaly",
            {
                "title": "DR 探针重试超限 → 需人工介入",
                "level": "critical",
                "retry_count": retry,
                "max_retries": max_retries,
                "guard_reason": guard.get("reason"),
                "action": "检查磁盘/权限/DB 状态；人工 clear_backup_guard 或修复后等待次日 03:05",
            },
            source="dr-recovery-probe",
        )
    except Exception:  # noqa: BLE001
        logger.exception("dr recovery probe: escalate alert publish failed")
    return {
        "ok": False,
        "escalated": True,
        "probe_retry_count": retry,
        "max_retries": max_retries,
    }
