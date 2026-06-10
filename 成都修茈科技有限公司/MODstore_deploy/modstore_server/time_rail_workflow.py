"""时间轨 workflow 图加载 + 节点 runtime 状态聚合（供 Agent / 仪表盘 API）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
) -> Dict[str, Any]:
    return {
        "node_id": node_id,
        "last_run": last_run,
        "ok": ok,
        "guard_active": bool(guard_active),
        "source": source or "",
        "detail": dict(detail or {}),
    }


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
            last_run=_iso_or_none(guard.get("set_at")),
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

    if rt_state.get("last_bump_at"):
        bump_ok = guard is None
        derived["RT"] = _node_status_shell(
            "RT",
            last_run=_iso_or_none(rt_state.get("last_bump_at")),
            ok=bump_ok,
            guard_active=guard is not None,
            source="release_train.json",
            detail={
                "current": rt_state.get("current"),
                "last_bump_day": rt_state.get("last_bump_day"),
                "day_index": rt_state.get("day_index"),
            },
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

    digest = _latest_digest_row()
    if digest is not None:
        created = _iso_or_none(getattr(digest, "created_at", None))
        day = str(getattr(digest, "day", "") or "")
        derived["P"] = _node_status_shell(
            "P",
            last_run=created,
            ok=bool(getattr(digest, "delivered", False)),
            source="daily_digest_records",
            detail={"digest_id": getattr(digest, "id", None), "day": day},
        )
        derived["ASM"] = _node_status_shell(
            "ASM",
            last_run=created,
            ok=bool(getattr(digest, "body_html", "") or getattr(digest, "body_text", "")),
            source="daily_digest_records",
            detail={"digest_id": getattr(digest, "id", None), "day": day},
        )
        derived["M"] = _node_status_shell(
            "M",
            last_run=created,
            ok=bool(getattr(digest, "meeting_minutes_html", "")),
            source="daily_digest_records",
            detail={"digest_id": getattr(digest, "id", None), "day": day},
        )
        derived["V"] = _node_status_shell(
            "V",
            last_run=created,
            ok=bool(
                getattr(digest, "vibe_prep_updates_md", "")
                or getattr(digest, "vibe_prep_patches_md", "")
            ),
            source="daily_digest_records",
            detail={"release_kind": getattr(digest, "release_kind", "")},
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
                        detail={"mode": ex.get("mode")},
                    )
            except Exception:
                pass

    return derived


def collect_node_runtime_status(
    *,
    node_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """聚合全部（或指定）节点的 runtime 状态。"""
    from modstore_server.time_rail_runtime import all_node_records

    graph = load_workflow_graph()
    all_ids = [str(n.get("id")) for n in (graph.get("nodes") or []) if n.get("id")]
    if node_ids:
        wanted = {str(x).strip() for x in node_ids if str(x).strip()}
        ids = list(wanted)
    else:
        ids = all_ids

    persisted = all_node_records()
    derived = _derive_from_sources()

    guard_global = bool(derived.get("DRFAIL", {}).get("guard_active"))
    nodes: Dict[str, Dict[str, Any]] = {}
    for nid in ids:
        row = persisted.get(nid) or derived.get(nid)
        if row:
            nodes[nid] = {
                "node_id": nid,
                "last_run": row.get("last_run"),
                "ok": row.get("ok"),
                "guard_active": bool(row.get("guard_active")) or (
                    guard_global and nid in ("RT", "DRFAIL", "DRPROBE")
                ),
                "source": row.get("source") or "",
                "detail": row.get("detail") if isinstance(row.get("detail"), dict) else {},
            }
        else:
            nodes[nid] = _node_status_shell(nid)

    return {
        "version": graph.get("version"),
        "graph_schema": graph.get("schema"),
        "graph_path": str(graph_json_path()),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "backup_guard_active": guard_global,
        "nodes": nodes,
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
]
