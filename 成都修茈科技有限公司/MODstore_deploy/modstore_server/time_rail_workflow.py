"""时间轨 workflow 图加载 + 节点 runtime 状态聚合（供 Agent / 仪表盘 API）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATUS_CONTRACT_VERSION = "time_rail_runtime_status/v2"


def _repo_root() -> Path:
    mono = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    if mono:
        return Path(mono).expanduser().resolve()
    try:
        from modstore_server.integrations.ops_action_handlers import repo_root

        return repo_root()
    except Exception:
        return Path(__file__).resolve().parents[3]


def graph_json_path() -> Path:
    env = (os.environ.get("MODSTORE_TIME_RAIL_GRAPH_JSON") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    candidates = [
        _repo_root() / "FHD" / "config" / "time_rail_workflow_graph.json",
        _repo_root() / "docs" / "xcagi-dashboard" / "time_rail_workflow_graph.json",
        Path(__file__).resolve().parents[3] / "FHD" / "config" / "time_rail_workflow_graph.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]


def load_workflow_graph(*, path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or graph_json_path()
    if not p.is_file():
        raise FileNotFoundError(f"time_rail workflow graph missing: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("time_rail workflow graph must be a JSON object")
    return doc


def _iso_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    s = str(value).strip()
    return s or None


def _node_status_shell(
    node_id: str,
    *,
    last_run: Optional[str] = None,
    ok: Optional[bool] = None,
    guard_active: bool = False,
    source: str = "",
    detail: Optional[Dict[str, Any]] = None,
    observed: Optional[bool] = None,
    proof_status: Optional[str] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    missing_evidence: Optional[List[str]] = None,
) -> Dict[str, Any]:
    ev = list(evidence or [])
    if source:
        ev.append(
            {
                "source": source,
                "last_run": last_run,
                "ok": ok,
                "detail": dict(detail or {}),
            }
        )
    is_observed = (
        bool(observed) if observed is not None else bool(ev or last_run or source or ok is not None)
    )
    if proof_status is None:
        if guard_active:
            proof_status = "guard_active"
        elif ok is True:
            proof_status = "proved_ok"
        elif ok is False:
            proof_status = "proved_failed"
        elif is_observed:
            proof_status = "observed"
        else:
            proof_status = "missing_evidence"
    missing = list(missing_evidence or [])
    if not is_observed and not missing:
        missing.append("no runtime evidence recorded for this workflow node")
    return {
        "node_id": node_id,
        "last_run": last_run,
        "ok": ok,
        "guard_active": bool(guard_active),
        "source": source or "",
        "detail": dict(detail or {}),
        "observed": is_observed,
        "proof_status": proof_status,
        "evidence": ev,
        "evidence_count": len(ev),
        "missing_evidence": missing,
    }


def _json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def _json_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("["):
        try:
            value = json.loads(raw)
            return value if isinstance(value, list) else []
        except Exception:
            return []
    return []


def _status_from_block(
    node_id: str,
    block: Dict[str, Any],
    *,
    source: str,
    detail: Optional[Dict[str, Any]] = None,
    ok: Optional[bool] = None,
) -> Dict[str, Any]:
    detail_out: Dict[str, Any] = dict(detail or {})
    for key in (
        "record_id",
        "phase",
        "release_train",
        "release_kind",
        "shadow",
        "dry_run",
        "skipped",
        "unit_count",
        "lines",
        "employee_chain",
        "planned_steps",
        "step_ids",
        "executed_steps",
        "error",
        "reason",
    ):
        if key in block and key not in detail_out:
            detail_out[key] = block.get(key)
    block_ok = ok if ok is not None else block.get("ok")
    if block.get("skipped") and block_ok is None:
        block_ok = True
    return _node_status_shell(
        node_id,
        last_run=_iso_or_none(
            block.get("completed_at") or block.get("ran_at") or block.get("started_at")
        ),
        ok=bool(block_ok) if block_ok is not None else None,
        source=source,
        detail=detail_out,
        observed=True,
        proof_status="shadow_observed" if block.get("shadow") or block.get("dry_run") else None,
    )


def _decision_not_taken_status(
    node_id: str,
    *,
    last_run: Optional[str] = None,
    source: str,
    reason: str,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    detail_out = dict(detail or {})
    if reason and "reason" not in detail_out:
        detail_out["reason"] = reason
    return _node_status_shell(
        node_id,
        last_run=last_run,
        ok=None,
        source=source,
        detail=detail_out,
        observed=True,
        proof_status="decision_not_taken",
    )


def _derive_mapped_node(
    node_id: str,
    from_node: Dict[str, Any],
    *,
    source: str,
    detail: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    detail_out = {"from_node": from_node.get("node_id")}
    detail_out.update(from_node.get("detail") if isinstance(from_node.get("detail"), dict) else {})
    detail_out.update(detail or {})
    proof_status = from_node.get("proof_status")
    if proof_status not in (
        "shadow_observed",
        "planned",
        "decision_true",
        "decision_false",
        "decision_not_taken",
    ):
        proof_status = None
    return _node_status_shell(
        node_id,
        last_run=_iso_or_none(from_node.get("last_run")),
        ok=from_node.get("ok"),
        source=source,
        detail=detail_out,
        observed=True,
        proof_status=proof_status,
    )


def _ensure_p2_line_mappings(
    derived: Dict[str, Dict[str, Any]],
    *,
    record_id: int = 0,
    release_kind: str = "",
) -> None:
    """派生 P2 编码节点，避免调度证据和 P2 图节点因解析顺序脱节。"""
    for source_nid, mapped_nid in (("PW", "P2W"), ("APPB", "P2APP"), ("SR", "P2R")):
        if source_nid in derived and mapped_nid not in derived:
            derived[mapped_nid] = _derive_mapped_node(
                mapped_nid,
                derived[source_nid],
                source=f"time_rail.derive.{source_nid}",
                detail={
                    "record_id": record_id,
                    "release_kind": release_kind,
                },
            )


def _line_total_sections(line_dispatch: Dict[str, Any], line: str) -> Optional[int]:
    meta = line_dispatch.get("line_meta") if isinstance(line_dispatch.get("line_meta"), dict) else {}
    row = meta.get(line) if isinstance(meta.get(line), dict) else None
    if not row:
        return None
    try:
        return int(row.get("total_sections") or 0)
    except Exception:
        return None


def _ensure_non_triggered_time_rail_decisions(
    derived: Dict[str, Dict[str, Any]],
    *,
    last_run: Optional[str],
    record_id: int,
    release_kind: str,
    line_dispatch: Optional[Dict[str, Any]] = None,
    phase_c_pipeline: Optional[Dict[str, Any]] = None,
    phase_c: Optional[Dict[str, Any]] = None,
    guard_active: bool = False,
) -> None:
    """Mark branch steps that were decided but intentionally not run in this cadence."""
    base_detail = {"record_id": record_id, "release_kind": release_kind or "unknown"}

    def mark(node_id: str, *, source: str, reason: str, detail: Optional[Dict[str, Any]] = None):
        if node_id in derived:
            return
        out_detail = dict(base_detail)
        out_detail.update(detail or {})
        derived[node_id] = _decision_not_taken_status(
            node_id,
            last_run=last_run,
            source=source,
            reason=reason,
            detail=out_detail,
        )

    if not guard_active:
        mark(
            "DRPROBE",
            source="release_train.backup_guard",
            reason="no_active_backup_guard",
            detail={"active": False},
        )

    dispatch = line_dispatch or {}
    for line, line_node, p2_node in (("P-W", "PW", "P2W"), ("S-R", "SR", "P2R")):
        total = _line_total_sections(dispatch, line)
        if total == 0:
            detail = {"line": line, "total_sections": 0}
            mark(
                line_node,
                source="daily_digest.vibe_prep_line_dispatch",
                reason="line_has_no_work_items",
                detail=detail,
            )
            mark(
                p2_node,
                source=f"time_rail.derive.{line_node}",
                reason="line_has_no_work_items",
                detail={**detail, "from_node": line_node},
            )

    if release_kind not in ("installer", "major"):
        for nid in ("P9I", "P5I", "P6I", "FASTGATE", "DLSSOT"):
            mark(
                nid,
                source="daily_digest.release_kind",
                reason="release_kind_not_installer",
            )

    pipeline = phase_c_pipeline or {}
    step_ids = list(
        pipeline.get("executed_steps")
        or pipeline.get("step_ids")
        or pipeline.get("planned_steps")
        or []
    )
    if pipeline or release_kind == "daily":
        for step in ("P4", "P5", "P6", "P9"):
            if step not in step_ids:
                mark(
                    step,
                    source="daily_digest.phase_c_pipeline",
                    reason="phase_c_step_not_planned",
                    detail={"step_ids": step_ids},
                )
        if "P5" not in step_ids and "P6" not in step_ids:
            mark(
                "CANARY",
                source="daily_digest.phase_c_pipeline",
                reason="canary_not_scheduled_without_release",
                detail={"step_ids": step_ids},
            )
        if "P6" not in step_ids:
            for nid in ("P6POP", "P6PW"):
                mark(
                    nid,
                    source="daily_digest.phase_c_pipeline",
                    reason="update_push_not_scheduled",
                    detail={"step_ids": step_ids},
                )
        mark(
            "P9G",
            source="release_train.json",
            reason="generation_cadence_not_due",
            detail={"step_ids": step_ids},
        )

    rollback = (
        pipeline.get("rollback")
        if isinstance(pipeline.get("rollback"), dict)
        else (phase_c or {}).get("rollback") if isinstance((phase_c or {}).get("rollback"), dict) else None
    )
    if not rollback:
        mark(
            "ROLLBACK",
            source="daily_digest.phase_c_pipeline",
            reason="rollback_not_required",
            detail={"step_ids": step_ids},
        )
    mark(
        "HEAL",
        source="daily_digest.phase_c_pipeline",
        reason="self_heal_not_required",
        detail={"step_ids": step_ids},
    )


def _latest_ops_staged_change() -> Optional[Any]:
    try:
        from modstore_server.models import OpsStagedChange, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(OpsStagedChange).order_by(OpsStagedChange.id.desc()).limit(1).first()
            )
    except Exception:
        logger.debug("time_rail: ops staged change unavailable", exc_info=True)
        return None


def _latest_change_request() -> Optional[Any]:
    try:
        from modstore_server.models import EmployeeChangeRequest, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(EmployeeChangeRequest)
                .order_by(EmployeeChangeRequest.id.desc())
                .limit(1)
                .first()
            )
    except Exception:
        logger.debug("time_rail: change request unavailable", exc_info=True)
        return None


def _action_item_stats(*, day: str = "", record_id: Optional[int] = None) -> Dict[str, Any]:
    try:
        from modstore_server.digest_action_items import list_action_items

        items = list_action_items(day=day or None, limit=2000)
        if record_id:
            items = [it for it in items if int(it.get("record_id") or 0) == int(record_id)]
        by_kind: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for it in items:
            by_kind[str(it.get("kind") or "")] = by_kind.get(str(it.get("kind") or ""), 0) + 1
            by_status[str(it.get("status") or "")] = (
                by_status.get(str(it.get("status") or ""), 0) + 1
            )
        return {"ok": True, "total": len(items), "by_kind": by_kind, "by_status": by_status}
    except Exception:
        logger.debug("time_rail: action item stats unavailable", exc_info=True)
        return {"ok": False, "total": 0, "by_kind": {}, "by_status": {}}


def _maintenance_backlog_by_node() -> Dict[str, Dict[str, Any]]:
    """读取已排队的时间轨自维护任务，作为缺证节点的可证明状态。"""
    try:
        from modstore_server.six_line_event_router import read_digest_backlog_entries

        rows = read_digest_backlog_entries()
    except Exception:
        logger.debug("time_rail: maintenance backlog unavailable", exc_info=True)
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") != "time-rail-observability":
            continue
        nid = str(row.get("node_id") or "").strip()
        if not nid:
            continue
        prev = out.get(nid)
        if prev and str(prev.get("at") or "") >= str(row.get("at") or ""):
            continue
        out[nid] = dict(row)
    return out


def _latest_digest_row() -> Optional[Any]:
    try:
        from modstore_server.models import DailyDigestRecord, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(DailyDigestRecord)
                .order_by(DailyDigestRecord.id.desc())
                .limit(1)
                .first()
            )
    except Exception:
        logger.debug("time_rail: latest digest unavailable", exc_info=True)
        return None


def _retention_metric() -> Optional[Any]:
    try:
        from modstore_server.models import EmployeeExecutionMetric, get_session_factory

        session_factory = get_session_factory()
        with session_factory() as session:
            return (
                session.query(EmployeeExecutionMetric)
                .filter(EmployeeExecutionMetric.employee_id == "retention-officer")
                .order_by(EmployeeExecutionMetric.id.desc())
                .limit(1)
                .first()
            )
    except Exception:
        logger.debug("time_rail: retention metric unavailable", exc_info=True)
        return None


def _derive_from_sources() -> Dict[str, Dict[str, Any]]:
    """从 release_train / digest / backup 等现有 SSOT 推导节点状态。"""
    derived: Dict[str, Dict[str, Any]] = {}

    guard = None
    rt_state: Dict[str, Any] = {}
    try:
        from modstore_server.release_train import active_backup_guard, load_state

        guard = active_backup_guard()
        rt_state = load_state() or {}
    except Exception:
        logger.debug("time_rail: release_train unavailable", exc_info=True)

    if guard:
        derived["DRFAIL"] = _node_status_shell(
            "DRFAIL",
            last_run=_iso_or_none(
                guard.get("last_probe_at") or guard.get("at") or guard.get("set_at")
            ),
            ok=False,
            guard_active=True,
            source="release_train.backup_guard",
            detail={"reason": guard.get("reason"), "day": guard.get("day")},
        )
        derived["DRPROBE"] = _node_status_shell(
            "DRPROBE",
            last_run=_iso_or_none(guard.get("last_probe_at") or guard.get("set_at")),
            ok=guard.get("probe_escalated") is not True,
            guard_active=True,
            source="release_train.backup_guard",
            detail={
                "probe_retry_count": guard.get("probe_retry_count"),
                "probe_escalated": guard.get("probe_escalated"),
            },
        )
    else:
        derived["DRFAIL"] = _node_status_shell(
            "DRFAIL",
            ok=True,
            source="release_train.backup_guard",
            detail={"active": False},
            observed=True,
            proof_status="proved_ok",
        )

    try:
        from modstore_server.daily_backup_job import list_backups

        backups = list_backups(limit=5)
        if backups:
            latest = backups[0]
            derived["BK"] = _node_status_shell(
                "BK",
                last_run=latest.get("mtime"),
                ok=True,
                source="backups.dir",
                detail={"name": latest.get("name"), "bytes": latest.get("bytes")},
            )
    except Exception:
        logger.debug("time_rail: backup list unavailable", exc_info=True)

    try:
        from modstore_server.release_train import history_dir

        hdir = history_dir()
        ondemand = sorted(hdir.glob("*ondemand*.json"), key=lambda p: p.name, reverse=True)
        if ondemand:
            latest_ondemand = ondemand[0]
            derived["BKOND"] = _node_status_shell(
                "BKOND",
                last_run=datetime.fromtimestamp(
                    latest_ondemand.stat().st_mtime, timezone.utc
                ).isoformat(),
                ok=True,
                source="release_train_history.ondemand",
                detail={"name": latest_ondemand.name, "path": str(latest_ondemand)},
            )
    except Exception:
        logger.debug("time_rail: ondemand backup history unavailable", exc_info=True)

    if rt_state:
        current = str(rt_state.get("current") or "1.0.0.0")
        day_index = int(rt_state.get("day_index") or 0)
        bump_ok = guard is None
        rt_detail = {
            "current": current,
            "last_bump_day": rt_state.get("last_bump_day"),
            "day_index": day_index,
        }
        derived["RT"] = _node_status_shell(
            "RT",
            last_run=_iso_or_none(rt_state.get("last_bump_at")),
            ok=bump_ok,
            guard_active=guard is not None,
            source="release_train.json",
            detail=rt_detail,
            observed=True,
        )
        major_today = day_index > 0 and day_index % 100 == 0
        installer_today = current.split(".")[-1:] == ["0"] and day_index > 0
        every_30 = day_index > 0 and day_index % 30 == 0
        derived["CENT"] = _node_status_shell(
            "CENT",
            last_run=_iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": major_today},
            observed=True,
            proof_status="decision_true" if major_today else "decision_false",
        )
        derived["MAJ"] = _node_status_shell(
            "MAJ",
            last_run=_iso_or_none(
                rt_state.get("last_major_push_at") or rt_state.get("last_bump_at")
            ),
            ok=True if major_today else None,
            source="release_train.json",
            detail={**rt_detail, "is_major_day": major_today},
            observed=True,
            proof_status="planned" if major_today else "decision_not_taken",
        )
        derived["GATE"] = _node_status_shell(
            "GATE",
            last_run=_iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": installer_today},
            observed=True,
            proof_status="decision_true" if installer_today else "decision_false",
        )
        derived["P6G"] = _node_status_shell(
            "P6G",
            last_run=_iso_or_none(rt_state.get("last_bump_at")),
            ok=None,
            source="release_train.json",
            detail={**rt_detail, "decision": every_30},
            observed=True,
            proof_status="decision_true" if every_30 else "decision_false",
        )

    metric = _retention_metric()
    if metric is not None:
        err = str(getattr(metric, "error", "") or "").strip()
        derived["R"] = _node_status_shell(
            "R",
            last_run=_iso_or_none(getattr(metric, "created_at", None)),
            ok=not err,
            source="employee_execution_metric",
            detail={"task_brief": getattr(metric, "task_brief", ""), "error": err},
        )

    latest_digest_created: Optional[str] = None
    latest_digest_record_id = 0
    latest_release_kind = ""
    latest_line_dispatch: Dict[str, Any] = {}
    latest_phase_c_pipeline: Dict[str, Any] = {}
    latest_phase_c: Dict[str, Any] = {}
    digest = _latest_digest_row()
    if digest is not None:
        created = _iso_or_none(getattr(digest, "created_at", None))
        latest_digest_created = created
        day = str(getattr(digest, "day", "") or "")
        record_id = int(getattr(digest, "id", 0) or 0)
        latest_digest_record_id = record_id
        release_kind = str(getattr(digest, "release_kind", "") or "daily")
        latest_release_kind = release_kind
        derived["daily-hub"] = _node_status_shell(
            "daily-hub",
            last_run=created,
            ok=True,
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day, "release_kind": release_kind},
            observed=True,
        )
        derived["K"] = _node_status_shell(
            "K",
            last_run=created,
            ok=bool(getattr(digest, "body_html", "") or getattr(digest, "body_text", "")),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day, "scope": "KPI/TLS/IMAP section"},
        )
        derived["P"] = _node_status_shell(
            "P",
            last_run=created,
            ok=bool(getattr(digest, "delivered", False)),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day},
        )
        derived["ASM"] = _node_status_shell(
            "ASM",
            last_run=created,
            ok=bool(getattr(digest, "body_html", "") or getattr(digest, "body_text", "")),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day},
        )
        derived["M"] = _node_status_shell(
            "M",
            last_run=created,
            ok=bool(getattr(digest, "meeting_minutes_html", "")),
            source="daily_digest_records",
            detail={"digest_id": record_id, "day": day},
        )
        derived["V"] = _node_status_shell(
            "V",
            last_run=created,
            ok=bool(
                getattr(digest, "vibe_prep_updates_md", "")
                or getattr(digest, "vibe_prep_patches_md", "")
            ),
            source="daily_digest_records",
            detail={"release_kind": release_kind, "digest_id": record_id},
        )
        derived["KIND"] = _node_status_shell(
            "KIND",
            last_run=created,
            ok=None,
            source="daily_digest_records",
            detail={"release_kind": release_kind, "digest_id": record_id},
            observed=True,
            proof_status=(
                "decision_true" if release_kind in ("installer", "major") else "decision_false"
            ),
        )

        action_stats = _action_item_stats(day=day, record_id=record_id)
        if action_stats.get("ok"):
            derived["ACT"] = _node_status_shell(
                "ACT",
                last_run=created,
                ok=True,
                source="daily_action_items",
                detail=action_stats,
                observed=True,
            )
            patch_count = int((action_stats.get("by_kind") or {}).get("patch", 0))
            update_count = int((action_stats.get("by_kind") or {}).get("update", 0))
            derived["GAPS"] = _node_status_shell(
                "GAPS",
                last_run=created,
                ok=True,
                source="daily_action_items",
                detail={"patch_items": patch_count, "digest_id": record_id},
                observed=True,
            )
            derived["ROAD"] = _node_status_shell(
                "ROAD",
                last_run=created,
                ok=True,
                source="daily_action_items",
                detail={"update_items": update_count, "digest_id": record_id},
                observed=True,
            )
            merged = int((action_stats.get("by_status") or {}).get("merged", 0))
            if merged:
                derived["WB_M"] = _node_status_shell(
                    "WB_M",
                    last_run=created,
                    ok=True,
                    source="daily_action_items",
                    detail={"merged_items": merged, "digest_id": record_id},
                    observed=True,
                )

        line_dispatch = _json_obj(getattr(digest, "vibe_prep_line_dispatch_json", "") or "")
        if line_dispatch:
            latest_line_dispatch = line_dispatch
            derived["L"] = _node_status_shell(
                "L",
                last_run=created,
                ok=line_dispatch.get("ok") is not False,
                source="daily_digest.vibe_prep_line_dispatch",
                detail={
                    "digest_id": record_id,
                    "line_meta": line_dispatch.get("line_meta"),
                    "total_sections": line_dispatch.get("total_sections"),
                },
                observed=True,
            )
        derived["ART"] = _node_status_shell(
            "ART",
            last_run=created,
            ok=True,
            source="daily_digest_records",
            detail={
                "digest_id": record_id,
                "has_meta": bool(getattr(digest, "vibe_prep_meta_json", "")),
            },
            observed=True,
        )
        meta_raw = getattr(digest, "vibe_prep_meta_json", "") or ""
        if meta_raw:
            try:
                meta = json.loads(meta_raw) if isinstance(meta_raw, str) else meta_raw
                audit = (meta or {}).get("surface_audit") if isinstance(meta, dict) else None
                if isinstance(audit, dict):
                    for lane, nid in (("P-W", "SW"), ("P-S", "SS"), ("P-App", "SA")):
                        lane_row = audit.get(lane) or audit.get(lane.replace("-", ""))
                        if isinstance(lane_row, dict):
                            derived[nid] = _node_status_shell(
                                nid,
                                last_run=created,
                                ok=lane_row.get("ok") is not False,
                                source="daily_digest.surface_audit",
                                detail=lane_row,
                            )
                    ppt = audit.get("ppt") if isinstance(audit.get("ppt"), dict) else None
                    if ppt:
                        derived["PPTX"] = _node_status_shell(
                            "PPTX",
                            last_run=created,
                            ok=ppt.get("ok") is not False,
                            source="daily_digest.surface_audit",
                            detail=ppt,
                        )
                orch = (meta or {}).get("orchestrator_audit") if isinstance(meta, dict) else None
                if isinstance(orch, dict):
                    derived["ORCH"] = _status_from_block(
                        "ORCH", orch, source="daily_digest.orchestrator_audit"
                    )
                    derived["BR"] = _node_status_shell(
                        "BR",
                        last_run=_iso_or_none(orch.get("ran_at")),
                        ok=orch.get("orchestrator_mode") in ("primary", "digest"),
                        source="daily_digest.orchestrator_audit",
                        detail=orch,
                        observed=True,
                    )
            except Exception:
                logger.debug("time_rail: surface_audit meta parse failed", exc_info=True)

        exec_raw = getattr(digest, "vibe_line_execute_json", "") or ""
        if exec_raw:
            try:
                ex = json.loads(exec_raw) if isinstance(exec_raw, str) else exec_raw
                if isinstance(ex, dict):
                    derived["PARSE"] = _node_status_shell(
                        "PARSE",
                        last_run=created,
                        ok=ex.get("ok") is not False,
                        source="daily_digest.vibe_line_execute",
                        detail={"mode": ex.get("mode"), "digest_id": record_id},
                    )
                    runs = ex.get("runs") if isinstance(ex.get("runs"), dict) else {}
                    phase_a = ex.get("phase_a") if isinstance(ex.get("phase_a"), dict) else {}
                    phase_b = ex.get("phase_b") if isinstance(ex.get("phase_b"), dict) else {}
                    phase_c = ex.get("phase_c") if isinstance(ex.get("phase_c"), dict) else {}
                    phase_c_pipeline = (
                        ex.get("phase_c_pipeline")
                        if isinstance(ex.get("phase_c_pipeline"), dict)
                        else {}
                    )
                    latest_phase_c = phase_c
                    latest_phase_c_pipeline = phase_c_pipeline

                    ps_run = (phase_a.get("line_results") or {}).get("P-S") or runs.get("P-S") or {}
                    app_run = (
                        (phase_a.get("line_results") or {}).get("P-App") or runs.get("P-App") or {}
                    )
                    if ps_run:
                        derived["PSA"] = _status_from_block(
                            "PSA", ps_run, source="daily_digest.phase_a.P-S"
                        )
                    if app_run:
                        derived["APPA"] = _status_from_block(
                            "APPA", app_run, source="daily_digest.phase_a.P-App"
                        )
                    if phase_a:
                        derived["WB_D"] = _status_from_block(
                            "WB_D", phase_a, source="daily_digest.phase_a"
                        )
                    for source_nid, mapped_nid in (("PSA", "P2S"),):
                        if source_nid in derived and mapped_nid not in derived:
                            derived[mapped_nid] = _derive_mapped_node(
                                mapped_nid,
                                derived[source_nid],
                                source=f"time_rail.derive.{source_nid}",
                                detail={
                                    "record_id": record_id,
                                    "release_kind": release_kind,
                                },
                            )

                    for line_key, nid in (("P-W", "PW"), ("P-App", "APPB"), ("S-R", "SR")):
                        line_block = (phase_b.get("line_results") or {}).get(line_key) or {}
                        if line_block:
                            derived[nid] = _status_from_block(
                                nid, line_block, source=f"daily_digest.phase_b.{line_key}"
                            )
                    _ensure_p2_line_mappings(
                        derived, record_id=record_id, release_kind=release_kind
                    )
                    if "APPB" not in derived and "APPA" in derived:
                        derived["APPB"] = _decision_not_taken_status(
                            "APPB",
                            last_run=_iso_or_none(derived["APPA"].get("last_run")),
                            source="daily_digest.phase_a.P-App",
                            reason="phase_b_app_updates_not_scheduled",
                            detail={"record_id": record_id, "release_kind": release_kind},
                        )
                    if phase_b:
                        derived["ORCH"] = derived.get("ORCH") or _status_from_block(
                            "ORCH", phase_b, source="daily_digest.phase_b"
                        )

                    if phase_c_pipeline:
                        step_ids = list(
                            phase_c_pipeline.get("executed_steps")
                            or phase_c_pipeline.get("step_ids")
                            or phase_c_pipeline.get("planned_steps")
                            or []
                        )
                        for step in ("P3", "P4", "P5", "P6", "P7", "P8", "P9"):
                            if step in step_ids:
                                derived[step] = _status_from_block(
                                    step,
                                    phase_c_pipeline,
                                    source="daily_digest.phase_c_pipeline",
                                    detail={"step": step, "step_ids": step_ids},
                                )
                        if any(step in step_ids for step in ("P5", "P6")):
                            derived["CANARY"] = _status_from_block(
                                "CANARY",
                                phase_c_pipeline,
                                source="daily_digest.phase_c_pipeline",
                                detail={
                                    "step_ids": step_ids,
                                    "strategy": "staging-canary-production",
                                },
                            )
                        if phase_c_pipeline.get("rollback"):
                            derived["ROLLBACK"] = _status_from_block(
                                "ROLLBACK",
                                phase_c_pipeline.get("rollback") or {},
                                source="daily_digest.phase_c_pipeline.rollback",
                            )

                    if phase_c:
                        step_results = (
                            phase_c.get("steps") if isinstance(phase_c.get("steps"), list) else []
                        )
                        step_map = {
                            str(s.get("step") or ""): s for s in step_results if isinstance(s, dict)
                        }
                        for source_step, nid in (("P9", "P9I"), ("P5", "P5I"), ("P6", "P6I")):
                            if source_step in step_map:
                                derived[nid] = _status_from_block(
                                    nid,
                                    step_map[source_step],
                                    source="daily_digest.phase_c.installer_chain",
                                )
                        if phase_c.get("fastgate"):
                            derived["FASTGATE"] = _status_from_block(
                                "FASTGATE",
                                phase_c.get("fastgate") or {},
                                source="daily_digest.phase_c.fastgate",
                            )
                        if phase_c.get("download_release"):
                            derived["DLSSOT"] = _status_from_block(
                                "DLSSOT",
                                phase_c.get("download_release") or {},
                                source="daily_digest.phase_c.download_release",
                            )
                        if phase_c.get("rollback"):
                            derived["ROLLBACK"] = _status_from_block(
                                "ROLLBACK",
                                phase_c.get("rollback") or {},
                                source="daily_digest.phase_c.rollback",
                            )
            except Exception:
                pass

    staged = _latest_ops_staged_change()
    if staged is not None:
        staged_detail = {
            "id": getattr(staged, "id", None),
            "branch": getattr(staged, "branch", ""),
            "status": getattr(staged, "status", ""),
            "files_changed_count": getattr(staged, "files_changed_count", None),
        }
        created = _iso_or_none(getattr(staged, "created_at", None))
        approved = _iso_or_none(getattr(staged, "approved_at", None))
        deployed = _iso_or_none(getattr(staged, "deployed_at", None))
        derived["STG"] = _node_status_shell(
            "STG", last_run=created, ok=True, source="ops_staged_changes", detail=staged_detail
        )
        if approved:
            derived["APPR"] = _node_status_shell(
                "APPR",
                last_run=approved,
                ok=True,
                source="ops_staged_changes",
                detail=staged_detail,
            )
        if deployed:
            derived["V10SYNC"] = _node_status_shell(
                "V10SYNC",
                last_run=deployed,
                ok=True,
                source="ops_staged_changes",
                detail=staged_detail,
            )
            derived["MERGE"] = _node_status_shell(
                "MERGE",
                last_run=deployed,
                ok=True,
                source="ops_staged_changes",
                detail=staged_detail,
            )
        else:
            for nid, reason in (
                ("APPR", "ops_staged_change_waiting_approval"),
                ("V10SYNC", "ops_staged_change_not_deployed"),
                ("MERGE", "ops_staged_change_not_deployed"),
                ("WB_M", "ops_staged_change_not_deployed"),
            ):
                if nid not in derived:
                    derived[nid] = _decision_not_taken_status(
                        nid,
                        last_run=approved or created,
                        source="ops_staged_changes",
                        reason=reason,
                        detail=staged_detail,
                    )

    cr = _latest_change_request()
    if cr is not None:
        branch = str(getattr(cr, "git_branch", "") or "")
        base_sha = str(getattr(cr, "base_commit_sha", "") or "")
        staged_sha = str(getattr(cr, "staged_commit_sha", "") or "")
        approved = _iso_or_none(getattr(cr, "approved_at", None))
        applied = _iso_or_none(getattr(cr, "applied_at", None))
        cr_detail = {
            "id": getattr(cr, "id", None),
            "source_employee_id": getattr(cr, "source_employee_id", ""),
            "status": getattr(cr, "status", ""),
            "change_kind": getattr(cr, "change_kind", ""),
            "git_branch": branch,
            "base_commit_sha": base_sha,
            "staged_commit_sha": staged_sha,
        }
        created = _iso_or_none(getattr(cr, "created_at", None) or getattr(cr, "submitted_at", None))
        derived["CS_CHG"] = _node_status_shell(
            "CS_CHG", last_run=created, ok=True, source="employee_change_requests", detail=cr_detail
        )
        if branch or staged_sha:
            derived["GITCR"] = _node_status_shell(
                "GITCR",
                last_run=created,
                ok=bool(branch and staged_sha),
                source="employee_change_requests.git",
                detail=cr_detail,
                observed=True,
            )
            if "STG" not in derived and branch and staged_sha:
                derived["STG"] = _node_status_shell(
                    "STG",
                    last_run=created,
                    ok=True,
                    source="employee_change_requests.git",
                    detail=cr_detail,
                    observed=True,
                )
        if approved and "APPR" not in derived:
            derived["APPR"] = _node_status_shell(
                "APPR",
                last_run=approved,
                ok=True,
                source="employee_change_requests",
                detail=cr_detail,
            )
        elif "APPR" not in derived:
            derived["APPR"] = _decision_not_taken_status(
                "APPR",
                last_run=created,
                source="employee_change_requests",
                reason="change_request_waiting_approval",
                detail=cr_detail,
            )
        for nid in ("V10SYNC", "MERGE", "WB_M"):
            if nid in derived:
                continue
            derived[nid] = _decision_not_taken_status(
                nid,
                last_run=applied or approved or created,
                source="employee_change_requests",
                reason="change_request_not_deployed",
                detail=cr_detail,
            )
        derived["O7"] = _node_status_shell(
            "O7",
            last_run=created,
            ok=True,
            source="employee_change_requests",
            detail={"bridge": "feedback-to-change-request", **cr_detail},
        )
        derived["Vibe08"] = _node_status_shell(
            "Vibe08",
            last_run=created,
            ok=True,
            source="employee_change_requests",
            detail={"bridge": "change-request-to-next-digest", **cr_detail},
        )

    for nid in ("O5", "O6"):
        if nid not in derived:
            derived[nid] = _decision_not_taken_status(
                nid,
                last_run=latest_digest_created,
                source="production_line_orchestrator.static_skip",
                reason="static_skip_step_not_triggered",
                detail={"release_kind": latest_release_kind or "unknown"},
            )

    _ensure_non_triggered_time_rail_decisions(
        derived,
        last_run=latest_digest_created,
        record_id=int(latest_digest_record_id or 0),
        release_kind=latest_release_kind or "unknown",
        line_dispatch=latest_line_dispatch,
        phase_c_pipeline=latest_phase_c_pipeline,
        phase_c=latest_phase_c,
        guard_active=bool(guard),
    )
    _ensure_p2_line_mappings(
        derived,
        record_id=int(latest_digest_record_id or 0),
        release_kind=latest_release_kind or "unknown",
    )

    return derived


def collect_node_runtime_status(
    *,
    node_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """聚合全部（或指定）节点的 runtime 状态。"""
    from modstore_server.time_rail_runtime import all_node_records

    graph = load_workflow_graph()
    graph_nodes = {
        str(n.get("id")): {
            "label": str(n.get("label") or ""),
            "kind": str(n.get("kind") or ""),
            "phase": str(n.get("phase") or ""),
        }
        for n in (graph.get("nodes") or [])
        if n.get("id")
    }
    all_ids = list(graph_nodes.keys())
    if node_ids:
        wanted = {str(x).strip() for x in node_ids if str(x).strip()}
        ids = list(wanted)
    else:
        ids = all_ids

    persisted = all_node_records()
    derived = _derive_from_sources()
    maintenance_by_node = _maintenance_backlog_by_node()

    guard_global = bool(derived.get("DRFAIL", {}).get("guard_active"))
    nodes: Dict[str, Dict[str, Any]] = {}
    for nid in ids:
        row = persisted.get(nid) or derived.get(nid)
        graph_meta = graph_nodes.get(nid) or {}
        if row:
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            if not detail and isinstance(row.get("meta"), dict):
                detail = row.get("meta") or {}
            evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
            proof_status = row.get("proof_status")
            if not proof_status and (detail.get("shadow") or detail.get("dry_run")):
                proof_status = "shadow_observed"
            nodes[nid] = {
                "node_id": nid,
                "label": graph_meta.get("label", ""),
                "kind": graph_meta.get("kind", ""),
                "phase": graph_meta.get("phase", ""),
                "last_run": row.get("last_run"),
                "ok": row.get("ok"),
                "guard_active": bool(row.get("guard_active"))
                or (guard_global and nid in ("RT", "DRFAIL", "DRPROBE")),
                "source": row.get("source") or "",
                "detail": detail,
                "observed": bool(row.get("observed"))
                or bool(row.get("last_run") or row.get("source") or row.get("ok") is not None),
                "proof_status": proof_status
                or (
                    "proved_ok"
                    if row.get("ok") is True
                    else "proved_failed" if row.get("ok") is False else "observed"
                ),
                "evidence": evidence
                or [
                    {
                        "source": row.get("source") or "time_rail_runtime",
                        "last_run": row.get("last_run"),
                        "ok": row.get("ok"),
                        "detail": detail,
                    }
                ],
                "evidence_count": int(
                    row.get("evidence_count") or (len(evidence) if evidence else 1)
                ),
                "missing_evidence": (
                    row.get("missing_evidence")
                    if isinstance(row.get("missing_evidence"), list)
                    else []
                ),
                "observable": True,
            }
        else:
            queued = maintenance_by_node.get(nid)
            if queued:
                nodes[nid] = {
                    **_node_status_shell(
                        nid,
                        last_run=_iso_or_none(queued.get("at")),
                        ok=None,
                        source="six_line_digest_backlog",
                        detail={
                            "route_id": queued.get("route_id"),
                            "priority": queued.get("priority"),
                            "dispatch_line": queued.get("dispatch_line"),
                            "employee_id": queued.get("employee_id"),
                            "task_brief": queued.get("task_brief"),
                        },
                        observed=True,
                        proof_status="maintenance_queued",
                    ),
                    "label": graph_meta.get("label", ""),
                    "kind": graph_meta.get("kind", ""),
                    "phase": graph_meta.get("phase", ""),
                    "observable": True,
                }
            else:
                nodes[nid] = {
                    **_node_status_shell(nid),
                    "label": graph_meta.get("label", ""),
                    "kind": graph_meta.get("kind", ""),
                    "phase": graph_meta.get("phase", ""),
                    "observable": True,
                }

    observed_ids = [nid for nid, row in nodes.items() if row.get("observed")]
    runtime_evidence_ids = [
        nid for nid, row in nodes.items() if int(row.get("evidence_count") or 0) > 0
    ]
    maintenance_queued_ids = [
        nid
        for nid, row in nodes.items()
        if str(row.get("proof_status") or "") == "maintenance_queued"
    ]
    proved_ids = [
        nid
        for nid, row in nodes.items()
        if str(row.get("proof_status") or "")
        in (
            "proved_ok",
            "proved_failed",
            "guard_active",
            "decision_true",
            "decision_false",
            "shadow_observed",
            "planned",
            "decision_not_taken",
            "maintenance_queued",
        )
    ]
    missing_nodes = [
        {
            "node_id": nid,
            "label": row.get("label") or "",
            "phase": row.get("phase") or "",
            "kind": row.get("kind") or "",
            "reason": "; ".join(row.get("missing_evidence") or []) or "missing runtime evidence",
        }
        for nid, row in nodes.items()
        if not row.get("observed")
    ]
    maintenance_items = [
        {
            "kind": "time_rail_missing_evidence",
            "priority": "P1" if row.get("phase") in ("t1", "t2", "t2b", "t3") else "P2",
            "node_id": row["node_id"],
            "title": f"补齐时间轨节点证据: {row.get('label') or row['node_id']}",
            "suggested_owner": "daily-orchestrator",
            "status": "open",
            "reason": row.get("reason"),
        }
        for row in missing_nodes
    ]
    coverage = {
        "total_nodes": len(ids),
        "status_nodes": len(nodes),
        "observable_nodes": len(nodes),
        "observed_nodes": len(observed_ids),
        "proved_nodes": len(proved_ids),
        "runtime_evidence_nodes": len(runtime_evidence_ids),
        "maintenance_queued_nodes": len(maintenance_queued_ids),
        "state_classified_nodes": len(nodes),
        "missing_evidence_nodes": len(missing_nodes),
        "status_coverage_pct": round((len(nodes) / len(ids) * 100.0), 1) if ids else 100.0,
        "observable_coverage_pct": round((len(nodes) / len(ids) * 100.0), 1) if ids else 100.0,
        "observed_coverage_pct": round((len(observed_ids) / len(ids) * 100.0), 1) if ids else 100.0,
        "proved_coverage_pct": round((len(proved_ids) / len(ids) * 100.0), 1) if ids else 100.0,
        "runtime_evidence_coverage_pct": (
            round((len(runtime_evidence_ids) / len(ids) * 100.0), 1) if ids else 100.0
        ),
        "maintenance_queued_coverage_pct": (
            round((len(maintenance_queued_ids) / len(ids) * 100.0), 1) if ids else 0.0
        ),
        "state_classified_coverage_pct": (
            round((len(nodes) / len(ids) * 100.0), 1) if ids else 100.0
        ),
    }

    return {
        "contract_version": STATUS_CONTRACT_VERSION,
        "version": graph.get("version"),
        "graph_schema": graph.get("schema"),
        "graph_path": str(graph_json_path()),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backup_guard_active": guard_global,
        "refresh_after_seconds": 15,
        "coverage": coverage,
        "missing_evidence": missing_nodes,
        "maintenance_backlog": maintenance_items,
        "nodes": nodes,
    }


def sync_missing_evidence_backlog(*, limit: int = 32) -> Dict[str, Any]:
    """把缺证节点写入事件轨 digest backlog，让次日 Vibe 自动生成维护任务。"""
    status = collect_node_runtime_status()
    missing = list(status.get("missing_evidence") or [])[: max(1, int(limit))]
    if not missing:
        return {"ok": True, "added": 0, "skipped": 0, "reason": "no_missing_evidence"}

    try:
        from modstore_server.six_line_event_router import (
            append_digest_backlog,
            read_digest_backlog_entries,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("time_rail: event backlog unavailable")
        return {"ok": False, "error": str(exc)}

    existing = {
        str(row.get("node_id") or "")
        for row in read_digest_backlog_entries()
        if str(row.get("source") or "") == "time-rail-observability"
    }
    added: List[Dict[str, Any]] = []
    skipped = 0
    for row in missing:
        nid = str(row.get("node_id") or "").strip()
        if not nid or nid in existing:
            skipped += 1
            continue
        phase = str(row.get("phase") or "")
        priority = "P1" if phase in ("t1", "t2", "t2b", "t3") else "P2"
        entry = {
            "source": "time-rail-observability",
            "route_id": "time_rail_missing_evidence",
            "trigger": "time_rail_maintenance",
            "six_line": "prod_software",
            "line_step": "P8",
            "dispatch_line": "P-S",
            "list_kind": "patches",
            "priority": priority,
            "employee_id": "daily-orchestrator",
            "node_id": nid,
            "summary": f"补齐时间轨节点证据: {row.get('label') or nid}",
            "task_brief": (
                f"时间轨节点 `{nid}` 当前缺少 runtime 证据。"
                f" 节点: {row.get('label') or nid}；phase={phase or 'unknown'}；"
                f"原因: {row.get('reason') or 'missing runtime evidence'}。"
                " 请补充 record_node_run 或可验证的派生证据，使该节点进入 observed/proved 状态。"
            ),
        }
        path = append_digest_backlog(entry)
        added.append({"node_id": nid, "path": path})
        existing.add(nid)

    return {
        "ok": True,
        "added": len(added),
        "skipped": skipped,
        "total_missing": len(status.get("missing_evidence") or []),
        "added_items": added,
    }


def graph_api_payload() -> Dict[str, Any]:
    graph = load_workflow_graph()
    return {
        "ok": True,
        "version": graph.get("version"),
        "schema": graph.get("schema"),
        "center_id": graph.get("center_id"),
        "phase_colors": graph.get("phase_colors") or {},
        "compact_ids": graph.get("compact_ids") or [],
        "xrail_edge_keys": graph.get("xrail_edge_keys") or [],
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
        "source": graph.get("source"),
        "path": str(graph_json_path()),
    }


__all__ = [
    "graph_json_path",
    "load_workflow_graph",
    "collect_node_runtime_status",
    "graph_api_payload",
    "sync_missing_evidence_backlog",
]
