"""Phase A/B release-train line dispatch and strategic escalation."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence, Tuple

from modstore_server.digest_line_executor import (
    _read_execute_meta,
    persist_line_execute_on_digest_record,
)
from modstore_server.digest_vibe_line_dispatch import DISPATCH_APP, DISPATCH_PS
from modstore_server.digest_vibe_work_units import DISPATCH_PW, DISPATCH_SR

logger = logging.getLogger(__name__)


PHASE_A_LINES: Tuple[Tuple[str, Sequence[str]], ...] = (
    (DISPATCH_PS, ("patches",)),
    (DISPATCH_APP, ("patches",)),
)

# P-S / P-App 补丁在 08:15 Phase A 已派发；Phase B 仅消费更新类清单（P-App 补丁不再重复）。
PHASE_B_LINES_WITH_APP: Tuple[Tuple[str, Sequence[str]], ...] = (
    (DISPATCH_PW, ("updates",)),
    (DISPATCH_APP, ("updates",)),
    (DISPATCH_SR, ("updates", "patches")),
)

PHASE_B_LINES_NO_APP: Tuple[Tuple[str, Sequence[str]], ...] = (
    (DISPATCH_PW, ("updates",)),
    (DISPATCH_SR, ("updates", "patches")),
)


def _env_bool(name: str, default: str = "1") -> bool:
    raw = (os.environ.get(name, default) or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _merge_phase_block(
    meta: Dict[str, Any], block_key: str, payload: Dict[str, Any]
) -> Dict[str, Any]:
    out = dict(meta or {})
    out[block_key] = payload
    out[f"{block_key}_at"] = payload.get("completed_at") or datetime.now(timezone.utc).isoformat()
    return out


def trigger_strategic_layer_dispatch(
    record_id: int,
    *,
    release_kind: str,
    release_train: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """daily-digest 完成后触发战略层集成（可关闭，默认开启）。

    触发条件（任一）：
    - 任一 phase 失败 → propose "review_digest_failure" 决策（require_human 边界）
    - installer/major 日 → propose "review_release_train" 决策（require_council 边界）
    - daily 成功 → 仅 report_only，不提案决策

    shadow 模式跳过（避免影子测试污染决策账本）。

    Returns:
        ``{"ok": True/False, "skipped": True/False, "reason": str, "decision_id": str, ...}``
    """
    if not _env_bool("MODSTORE_STRATEGIC_LAYER_INTEGRATION_ENABLED", "1"):
        return {"ok": True, "skipped": True, "reason": "strategic_layer integration disabled"}

    if result.get("shadow"):
        return {"ok": True, "skipped": True, "reason": "shadow mode"}

    try:
        from modstore_server.strategic_layer import (
            DecisionProposer,
            DecisionType,
            StrategicDecisionLedger,
        )
    except ImportError as exc:
        logger.warning("strategic_layer import failed: %s", exc)
        return {"ok": False, "error": f"import failed: {exc}"}

    overall_ok = bool(result.get("ok"))
    failed_phases = [
        name
        for name in ("phase_b", "phase_c_pipeline", "phase_c")
        if not (result.get(name) or {}).get("ok", True)
    ]

    if not overall_ok:
        action = "review_digest_failure"
        title = (
            f"daily-digest#{record_id} 失败 review "
            f"(phases: {','.join(failed_phases) or 'unknown'})"
        )
        decision_type = DecisionType.OPERATIONAL
        rationale = (
            f"auto-proposed by digest_daily_line_chain record_id={record_id} "
            f"release_kind={release_kind}; failed_phases={failed_phases}"
        )
    elif release_kind in ("installer", "major"):
        action = "review_release_train"
        title = f"{release_kind} release {release_train} 战略层复盘"
        decision_type = DecisionType.STRATEGIC
        rationale = (
            f"auto-proposed by digest_daily_line_chain record_id={record_id} "
            f"release_kind={release_kind} release_train={release_train}"
        )
    else:
        return {"ok": True, "skipped": True, "reason": "daily ok, no strategic action"}

    try:
        ledger = StrategicDecisionLedger()
        record = ledger.propose(
            title=title,
            action=action,
            proposer=DecisionProposer(
                actor="digest-daily-line-chain",
                rationale=rationale,
                payload={
                    "record_id": int(record_id),
                    "release_kind": release_kind,
                    "release_train": release_train,
                    "failed_phases": failed_phases,
                },
            ),
            decision_type=decision_type,
            scope="release_train",
            scope_ref=str(release_train or ""),
            execution_plan={
                "record_id": int(record_id),
                "release_kind": release_kind,
                "failed_phases": failed_phases,
            },
        )
        logger.info(
            "strategic_layer dispatch record_id=%s decision_id=%s status=%s autonomy=%s",
            record_id,
            record.decision_id,
            record.status.value,
            record.autonomy_action,
        )
        return {
            "ok": True,
            "skipped": False,
            "decision_id": record.decision_id,
            "status": record.status.value,
            "autonomy_action": record.autonomy_action,
            "action": action,
            "title": title,
        }
    except Exception as exc:
        logger.exception("strategic_layer dispatch failed record_id=%s", record_id)
        return {"ok": False, "error": str(exc)}


def wait_for_phase_a(record_id: int, *, required: bool = True) -> Dict[str, Any]:
    """08:25 前确认 08:15 Phase A（P-S + P-App 补丁）已完成或跳过。"""
    if not _env_bool("MODSTORE_RELEASE_TRAIN_WAIT_PHASE_A", "1"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_RELEASE_TRAIN_WAIT_PHASE_A=0"}

    meta = _read_execute_meta(int(record_id))
    runs = meta.get("runs") or {}
    ps_run = runs.get(DISPATCH_PS) or {}
    app_run = runs.get(DISPATCH_APP) or {}
    phase_a_block = meta.get("phase_a") if isinstance(meta.get("phase_a"), dict) else {}

    lines_ok = True
    missing: List[str] = []
    for line in (DISPATCH_PS, DISPATCH_APP):
        lr = (phase_a_block.get("line_results") or {}).get(line) or runs.get(line) or {}
        if not lr.get("ok"):
            lines_ok = False
            missing.append(line)

    if lines_ok:
        return {
            "ok": True,
            "phase_a": phase_a_block or {"runs": {DISPATCH_PS: ps_run, DISPATCH_APP: app_run}},
            "ps_run": ps_run,
            "app_run": app_run,
        }
    if not required:
        return {
            "ok": True,
            "skipped": True,
            "reason": "phase_a not complete (optional)",
            "missing_lines": missing,
        }
    return {
        "ok": False,
        "error": "phase_a_not_complete",
        "hint": "run daily_vibe_line_execute_job (08:15) before release_train orchestrator",
        "missing_lines": missing,
        "ps_run": ps_run or None,
        "app_run": app_run or None,
        "phase_a": phase_a_block or None,
    }


def execute_phase_a_line_chain(
    record_id: int,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """08:15 Phase A：P-S 软件补丁 + P-App 移动发布补丁派发。"""
    if not _env_bool("MODSTORE_DAILY_VIBE_EXECUTE_ENABLED", "1"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_DAILY_VIBE_EXECUTE_ENABLED=0"}

    from modstore_server.digest_line_executor import execute_digest_line_work_units

    started_at = datetime.now(timezone.utc).isoformat()
    line_results: Dict[str, Any] = {}
    all_ok = True

    for line, kinds in PHASE_A_LINES:
        out = execute_digest_line_work_units(
            int(record_id),
            dispatch_line=line,
            list_kinds=list(kinds),
            phase="A",
            mode="auto",
            force=force,
            dry_run=dry_run,
        )
        line_results[line] = out
        if not out.get("ok"):
            all_ok = False

    completed_at = datetime.now(timezone.utc).isoformat()
    block: Dict[str, Any] = {
        "ok": all_ok,
        "phase": "A",
        "record_id": int(record_id),
        "lines": [line for line, _ in PHASE_A_LINES],
        "line_results": line_results,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    block["employee_chain"] = sorted(
        {
            u.get("employee_id")
            for lr in line_results.values()
            for u in (lr.get("units") or [])
            if u.get("employee_id")
        }
        | {e for lr in line_results.values() for e in (lr.get("planned_employees") or [])}
    )

    meta = _read_execute_meta(int(record_id))
    persist_line_execute_on_digest_record(
        int(record_id), _merge_phase_block(meta, "phase_a", block)
    )

    logger.info(
        "phase_a line chain record_id=%s ok=%s employees=%s lines=%s",
        record_id,
        all_ok,
        block["employee_chain"],
        block["lines"],
    )
    return block


def execute_phase_b_line_chain(
    record_id: int,
    *,
    shadow: bool = False,
    force: bool = False,
    include_app: bool = True,
) -> Dict[str, Any]:
    """08:25 Phase B：P-W 更新 + （可选）P-App 更新 + S-R。

    默认包含 P-App，用于独立链路联调；release orchestrator 可按需禁用。
    """
    if not _env_bool("MODSTORE_RELEASE_TRAIN_PHASE_B_ENABLED", "1"):
        return {"ok": True, "skipped": True, "reason": "MODSTORE_RELEASE_TRAIN_PHASE_B_ENABLED=0"}

    phase_a_gate = wait_for_phase_a(
        int(record_id), required=_env_bool("MODSTORE_RELEASE_TRAIN_REQUIRE_PHASE_A", "1")
    )
    if not phase_a_gate.get("ok"):
        return phase_a_gate

    from modstore_server.digest_line_executor import execute_digest_line_work_units

    started_at = datetime.now(timezone.utc).isoformat()
    line_results: Dict[str, Any] = {}
    all_ok = True

    phase_b_lines = PHASE_B_LINES_WITH_APP if include_app else PHASE_B_LINES_NO_APP
    for line, kinds in phase_b_lines:
        out = execute_digest_line_work_units(
            int(record_id),
            dispatch_line=line,
            list_kinds=list(kinds),
            phase="B",
            mode="shadow" if shadow else "auto",
            force=force,
            dry_run=shadow,
        )
        line_results[line] = out
        if not out.get("ok"):
            all_ok = False

    completed_at = datetime.now(timezone.utc).isoformat()
    block: Dict[str, Any] = {
        "ok": all_ok,
        "phase": "B",
        "shadow": shadow,
        "record_id": int(record_id),
        "lines": list(line_results.keys()),
        "skipped_ps": True,
        "skipped_app_patches": True,
        "ps_note": "P-S patches executed in Phase A (08:15)",
        "app_note": "P-App patches executed in Phase A (08:15); Phase B runs P-App updates only",
        "phase_a_gate": phase_a_gate,
        "line_results": line_results,
        "started_at": started_at,
        "completed_at": completed_at,
    }

    employees = sorted(
        {
            u.get("employee_id")
            for lr in line_results.values()
            for u in (lr.get("units") or [])
            if u.get("employee_id")
        }
        | {e for lr in line_results.values() for e in (lr.get("planned_employees") or [])}
    )
    block["employee_chain"] = employees

    meta = _read_execute_meta(int(record_id))
    persist_line_execute_on_digest_record(
        int(record_id), _merge_phase_block(meta, "phase_b", block)
    )

    logger.info(
        "phase_b line chain record_id=%s shadow=%s ok=%s employees=%s",
        record_id,
        shadow,
        all_ok,
        employees,
    )
    return block
