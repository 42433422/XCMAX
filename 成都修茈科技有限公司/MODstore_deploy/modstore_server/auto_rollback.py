"""ROLLBACK — 灰度/即时门禁失败时的自动回滚闭环。

对齐时间轨 docs/xcagi-dashboard/emp-wf-radial-graph.js 的 ROLLBACK 节点：
FASTGATE（即时推送门禁）或 CANARY（灰度发布）校验不过时，统一触发：

1. ``rollback_release_train`` 回退上一稳定版（含历史快照，可审计、可再回退）；
2. 发告警（``incident_bus.publish`` → ``log.anomaly``）；
3. 落 ``OpsStagedChange(status="pending")`` 复盘待审（人工确认根因 + 是否重推）。

开关：
- ``MODSTORE_AUTO_ROLLBACK_ENABLED``（默认 1）：设 0 仅记录不回滚。
- ``MODSTORE_AUTO_ROLLBACK_STAGE_REVIEW``（默认 1）：设 0 不落 OpsStagedChange。
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: str = "1") -> bool:
    return (os.environ.get(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def _publish_alert(
    gate: str,
    release_train: str,
    release_kind: str,
    reason: str,
    failed_step: Optional[str],
    rollback: Dict[str, Any],
) -> Dict[str, Any]:
    try:
        from modstore_server.incident_bus import publish

        published = publish(
            "log.anomaly",
            {
                "title": f"{gate} 门禁不过 → 自动回滚",
                "gate": gate,
                "release_train": release_train,
                "release_kind": release_kind,
                "failed_step": failed_step,
                "reason": str(reason)[:500],
                "rolled_back_from": rollback.get("before"),
                "rolled_back_to": rollback.get("after"),
                "rollback_ok": bool(rollback.get("ok")),
            },
            source=f"auto-rollback:{gate.lower()}",
        )
        return {"ok": True, "published": bool(published)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_rollback: alert publish failed gate=%s", gate)
        return {"ok": False, "error": str(exc)[:300]}


def _stage_postmortem(
    gate: str,
    release_train: str,
    release_kind: str,
    reason: str,
    failed_step: Optional[str],
    rollback: Dict[str, Any],
) -> Dict[str, Any]:
    if not _env_bool("MODSTORE_AUTO_ROLLBACK_STAGE_REVIEW", "1"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_AUTO_ROLLBACK_STAGE_REVIEW=0"}
    try:
        from modstore_server.models import OpsStagedChange, get_session_factory

        summary = (
            f"[auto-rollback · {gate}] release_kind={release_kind} "
            f"release_train={release_train} failed_step={failed_step or '-'}\n"
            f"reason: {str(reason)[:1000]}\n"
            f"rolled_back: {rollback.get('before')} -> {rollback.get('after')} "
            f"(ok={rollback.get('ok')})\n"
            "待人工复盘：确认门禁失败根因，决定是否修复后重新推送。"
        )
        sf = get_session_factory()
        with sf() as session:
            row = OpsStagedChange(
                branch=f"auto-rollback/{gate.lower()}",
                base_commit="",
                head_commit="",
                files_changed_count=0,
                diff_summary=summary[:8000],
                created_by_employee_id="deploy-release-officer",
                status="pending",
            )
            session.add(row)
            session.flush()
            staged_id = int(row.id)
            session.commit()
        return {"ok": True, "staged_id": staged_id}
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_rollback: stage postmortem failed gate=%s", gate)
        return {"ok": False, "error": str(exc)[:300]}


def auto_rollback_on_gate_failure(
    *,
    gate: str,
    release_train: str = "",
    release_kind: str = "",
    reason: str = "",
    failed_step: Optional[str] = None,
) -> Dict[str, Any]:
    """门禁失败统一回滚闭环。

    ``gate`` 取 ``FASTGATE`` / ``CANARY``。返回 {ok, rollback, alert, staged_change, ...}。
    ``ok`` 反映回退是否成功（关闭开关时为 True+skipped）。
    """
    at = datetime.now(timezone.utc).isoformat()
    out: Dict[str, Any] = {
        "gate": gate,
        "release_train": release_train,
        "release_kind": release_kind,
        "reason": str(reason)[:500],
        "failed_step": failed_step,
        "at": at,
    }
    if not _env_bool("MODSTORE_AUTO_ROLLBACK_ENABLED", "1"):
        out.update({"ok": True, "skipped": True, "reason_skip": "MODSTORE_AUTO_ROLLBACK_ENABLED=0"})
        return out

    try:
        from modstore_server.release_train import rollback_release_train

        rollback = rollback_release_train(reason=f"auto_rollback:{gate}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_rollback: rollback_release_train failed gate=%s", gate)
        rollback = {"ok": False, "error": str(exc)[:300]}
    out["rollback"] = rollback
    out["alert"] = _publish_alert(gate, release_train, release_kind, reason, failed_step, rollback)
    out["staged_change"] = _stage_postmortem(
        gate, release_train, release_kind, reason, failed_step, rollback
    )
    out["ok"] = bool(rollback.get("ok"))
    logger.warning(
        "auto_rollback gate=%s kind=%s failed_step=%s rollback_ok=%s reason=%s",
        gate,
        release_kind,
        failed_step,
        out["ok"],
        str(reason)[:200],
    )
    return out
