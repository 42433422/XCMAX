"""六线事件轨路由器 — 与时间轨（release_train 日更）互补。

时间轨：定时 digest → Vibe 清单 → Phase A/B/C → P3–P9（见 digest_daily_line_chain）。
事件轨：运营/伙伴/交叉/采集器事件 → 本模块 → incident_bus 派发 或 写入日更 backlog。

SSOT：``FHD/config/six_line_event_routes.json``（经 MODSTORE_REPO_ROOT 解析）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

_BACKLOG_NAME = "six_line_digest_backlog.jsonl"

# 事件轨 backlog 合并进 Vibe 补丁清单时的默认主责（按 dispatch_line）
_DISPATCH_LINE_DEFAULT_EMPLOYEE: Dict[str, str] = {
    "P-W": "workbench-ux-stylist",
    "P-S": "fhd-core-maintainer",
    "P-App": "mobile-android-release-officer",
    "S-R": "retention-officer",
}


def _repo_root() -> Path:
    env = (os.environ.get("MODSTORE_REPO_ROOT") or "").strip()
    if env:
        return Path(env).resolve()
    p = Path(__file__).resolve()
    for depth in (3, 2, 4):
        if depth <= len(p.parents):
            cand = p.parents[depth - 1]
            if (cand / "FHD" / "config").is_dir():
                return cand
    return p.parents[2]


def _routes_path() -> Path:
    override = (os.environ.get("XCAGI_SIX_LINE_EVENT_ROUTES") or "").strip()
    if override:
        return Path(override).resolve()
    return _repo_root() / "FHD" / "config" / "six_line_event_routes.json"


def _backlog_path() -> Path:
    runtime = (os.environ.get("MODSTORE_RUNTIME_DIR") or "").strip()
    if runtime:
        base = Path(runtime).expanduser()
    else:
        root = _repo_root()
        if (root / "MODstore_deploy").is_dir():
            base = root / "MODstore_deploy" / "var" / "runtime"
        else:
            base = root / "成都修茈科技有限公司" / "MODstore_deploy" / "var" / "runtime"
    base.mkdir(parents=True, exist_ok=True)
    return base / _BACKLOG_NAME


@lru_cache(maxsize=1)
def load_event_routes() -> Dict[str, Any]:
    path = _routes_path()
    if not path.is_file():
        logger.warning("six_line_event_routes missing: %s", path)
        return {"operations_line": [], "cross_line": [], "incident_defaults": []}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def reload_event_routes() -> Dict[str, Any]:
    load_event_routes.cache_clear()
    return load_event_routes()


def _match_status(rule_status_in: List[str], status: str) -> bool:
    allowed = [str(s).strip().lower() for s in (rule_status_in or []) if str(s).strip()]
    if not allowed:
        return True
    return (status or "").strip().lower() in allowed


def _find_operations_route(step_id: str, status: str) -> Optional[Dict[str, Any]]:
    cfg = load_event_routes()
    sid = (step_id or "").strip().upper()
    st = (status or "").strip().lower()
    for row in cfg.get("operations_line") or []:
        if str(row.get("step_id") or "").strip().upper() != sid:
            continue
        if not _match_status(list(row.get("status_in") or []), st):
            continue
        return row
    return None


def _find_cross_line_route(from_step: str, to_step: str) -> Optional[Dict[str, Any]]:
    cfg = load_event_routes()
    fs = (from_step or "").strip().upper()
    ts = (to_step or "").strip().upper()
    for row in cfg.get("cross_line") or []:
        if (
            str(row.get("from_step") or "").strip().upper() == fs
            and str(row.get("to_step") or "").strip().upper() == ts
        ):
            return row
    return None


def append_digest_backlog(entry: Dict[str, Any]) -> str:
    """追加一行到日更 backlog；08:00 Vibe 预备可合并（见 EVENT_DRIVEN_SIX_LINE.md）。"""
    path = _backlog_path()
    row = {
        **entry,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(path)


def read_digest_backlog_entries() -> List[Dict[str, Any]]:
    """读取待合并的 backlog 行（无效 JSON 行跳过）。"""
    path = _backlog_path()
    if not path.is_file():
        return []
    entries: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("six_line_event_router: skip invalid backlog line")
            continue
        if isinstance(row, dict):
            entries.append(row)
    return entries


def _archive_consumed_backlog(entries: Sequence[Dict[str, Any]]) -> None:
    if not entries:
        return
    path = _backlog_path()
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    archive = path.parent / f"six_line_digest_backlog.processed.{day}.jsonl"
    with archive.open("a", encoding="utf-8") as f:
        for row in entries:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    path.write_text("", encoding="utf-8")


def format_backlog_entries_as_vibe_sections(entries: Sequence[Dict[str, Any]]) -> str:
    """将 backlog 格式化为 Vibe 补丁清单的 ``## [employee_id]`` 段落。"""
    sections: List[str] = []
    for row in entries:
        line = str(row.get("dispatch_line") or "P-S").strip()
        eid = str(
            row.get("employee_id")
            or _DISPATCH_LINE_DEFAULT_EMPLOYEE.get(line)
            or "task-router-officer"
        ).strip()
        pri = str(row.get("priority") or "P2").strip().upper()
        if pri not in ("P0", "P1", "P2", "P3"):
            pri = "P2"
        brief = str(row.get("task_brief") or row.get("summary") or "").strip()[:2000]
        if not brief:
            continue
        route = str(row.get("route_id") or row.get("trigger") or "event").strip()
        sections.append(f"## [{eid}]\n- **{pri}** [事件轨·{route}] {brief}")
    return "\n\n".join(sections).strip()


def _drop_stale_time_rail_entries(entries: Sequence[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    time_rail_entries = [
        row
        for row in entries
        if str(row.get("route_id") or "") == "time_rail_missing_evidence"
        and str(row.get("node_id") or "").strip()
    ]
    if not time_rail_entries:
        return list(entries), 0
    try:
        from modstore_server.time_rail_workflow import collect_node_runtime_status

        status = collect_node_runtime_status()
    except Exception:
        logger.exception("six_line_event_router: time rail stale backlog check failed")
        return list(entries), 0

    nodes = status.get("nodes") if isinstance(status, dict) else {}
    if not isinstance(nodes, dict):
        return list(entries), 0

    kept: List[Dict[str, Any]] = []
    skipped = 0
    for row in entries:
        if str(row.get("route_id") or "") != "time_rail_missing_evidence":
            kept.append(dict(row))
            continue
        node_id = str(row.get("node_id") or "").strip()
        node = nodes.get(node_id) if node_id else None
        if not isinstance(node, dict):
            kept.append(dict(row))
            continue
        proof_status = str(node.get("proof_status") or "")
        if proof_status == "maintenance_queued":
            kept.append(dict(row))
            continue
        if bool(node.get("observed")) or proof_status in (
            "proved_ok",
            "proved_failed",
            "guard_active",
            "decision_true",
            "decision_false",
            "shadow_observed",
            "planned",
            "decision_not_taken",
        ):
            skipped += 1
            continue
        kept.append(dict(row))
    return kept, skipped


def merge_event_backlog_into_vibe_patches(
    patches_markdown: str,
    *,
    consume: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    """M2：把事件轨 backlog 合并进 Vibe 补丁 Markdown；可选消费（归档并清空 backlog）。"""
    raw_entries = read_digest_backlog_entries()
    if not raw_entries:
        return patches_markdown, {"merged_count": 0, "backlog_path": str(_backlog_path())}

    entries, skipped_stale = _drop_stale_time_rail_entries(raw_entries)
    block = format_backlog_entries_as_vibe_sections(entries)
    if not block:
        meta = {
            "merged_count": 0,
            "skipped_empty_brief": len(entries),
            "skipped_stale_time_rail": skipped_stale,
            "backlog_path": str(_backlog_path()),
            "consumed": False,
        }
        if consume and skipped_stale and skipped_stale >= len(raw_entries):
            _archive_consumed_backlog(raw_entries)
            meta["consumed"] = True
        return patches_markdown, meta

    base = (patches_markdown or "").strip()
    if not base:
        merged = "# Vibe 预备 · 补丁清单\n\n" + block + "\n"
    elif base.startswith("#"):
        merged = base.rstrip() + "\n\n" + block + "\n"
    else:
        merged = base + "\n\n" + block + "\n"

    meta: Dict[str, Any] = {
        "merged_count": len(entries),
        "skipped_stale_time_rail": skipped_stale,
        "backlog_path": str(_backlog_path()),
        "consumed": False,
    }
    if consume:
        _archive_consumed_backlog(raw_entries)
        meta["consumed"] = True
    return merged, meta


def _publish_incident(event_type: str, payload: Dict[str, Any], *, source: str) -> bool:
    from modstore_server.incident_bus import publish

    return bool(
        publish(
            event_type,
            payload,
            source=source,
            fingerprint=payload.get("fingerprint"),
        )
    )


def _execute_route(
    rule: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    source: str,
    trigger: str,
) -> Dict[str, Any]:
    action = str(rule.get("action") or "incident").strip().lower()
    six_line = str(rule.get("six_line") or "")
    line_step = str(rule.get("line_step") or "")
    priority = str(rule.get("priority") or "P2")
    out: Dict[str, Any] = {
        "route_id": rule.get("id"),
        "trigger": trigger,
        "six_line": six_line,
        "line_step": line_step,
        "action": action,
        "published": False,
        "backlog": False,
    }
    enriched = {
        **payload,
        "six_line": six_line,
        "line_step": line_step,
        "priority": priority,
        "route_id": rule.get("id"),
        "trigger": trigger,
    }
    summary = str(payload.get("summary") or payload.get("stage") or rule.get("id") or trigger)
    enriched.setdefault("summary", summary[:500])

    if action in ("digest_backlog", "digest_defer"):
        backlog_entry = {
            "six_line": six_line,
            "line_step": line_step,
            "dispatch_line": str(rule.get("dispatch_line") or "P-S"),
            "list_kind": str(rule.get("list_kind") or "patches"),
            "priority": priority,
            "task_brief": summary[:2000],
            "source": source,
            "trigger": trigger,
            "route_id": rule.get("id"),
            "payload": {k: v for k, v in payload.items() if k not in ("fingerprint",)},
        }
        path = append_digest_backlog(backlog_entry)
        out["backlog"] = True
        out["backlog_path"] = path

    also = str(rule.get("also_incident") or "").strip()
    event_type = str(rule.get("event_type") or also or "ops.intake.task.queued").strip()
    if action == "incident" or also:
        out["published"] = _publish_incident(event_type, enriched, source=source)
        out["event_type"] = event_type

    return out


def handle_operations_line_event(body: Dict[str, Any]) -> Dict[str, Any]:
    """FHD operations_line_bridge → POST /api/admin/production-line/event。"""
    step_id = str(body.get("step_id") or "")
    status = str(body.get("status") or "progress")
    payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
    rule = _find_operations_route(step_id, status)
    if not rule:
        logger.info("six_line_event_router: no route for ops step=%s status=%s", step_id, status)
        return {"routed": False, "step_id": step_id, "status": status}
    result = _execute_route(
        rule,
        {**payload, "step_id": step_id, "status": status},
        source="operations-line-bridge",
        trigger="operations_line",
    )
    return {"routed": True, **result}


def handle_cross_line_trigger(
    *, from_step: str, to_step: str, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """ProductionLineOrchestrator cross_line_trigger 回调。"""
    rule = _find_cross_line_route(from_step, to_step)
    payload = dict(context or {})
    payload["from_step"] = from_step
    payload["to_step"] = to_step
    if not rule:
        logger.info("six_line_event_router: no cross_line route %s→%s", from_step, to_step)
        return {"routed": False, "from_step": from_step, "to_step": to_step}
    result = _execute_route(
        rule,
        payload,
        source=f"cross-line:{from_step}",
        trigger="cross_line",
    )
    return {"routed": True, **result}


def route_incident_type(event_type: str, payload: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    """在 incident_bus.publish 之前可选 enrichment（默认规则表）。"""
    cfg = load_event_routes()
    for row in cfg.get("incident_defaults") or []:
        if str(row.get("event_type") or "") != event_type:
            continue
        return _execute_route(row, payload, source=source, trigger="incident_defaults")
    return {"routed": False, "event_type": event_type}


def get_event_rail_status() -> Dict[str, Any]:
    cfg = load_event_routes()
    backlog = _backlog_path()
    backlog_count = 0
    if backlog.is_file():
        try:
            backlog_count = sum(1 for _ in backlog.open(encoding="utf-8"))
        except OSError:
            pass
    return {
        "routes_path": str(_routes_path()),
        "routes_loaded": bool(cfg.get("operations_line")),
        "operations_routes": len(cfg.get("operations_line") or []),
        "cross_line_routes": len(cfg.get("cross_line") or []),
        "incident_defaults": len(cfg.get("incident_defaults") or []),
        "digest_backlog_path": str(backlog),
        "digest_backlog_pending": backlog_count,
        "rails": cfg.get("rails"),
    }


def install_orchestrator_hooks() -> None:
    """注册 cross_line 回调到全局 ProductionLineOrchestrator。"""
    from modstore_server.production_line_orchestrator import get_production_line_orchestrator

    orch = get_production_line_orchestrator()

    def _on_cross_line(**kwargs: Any) -> Dict[str, Any]:
        return handle_cross_line_trigger(
            from_step=str(kwargs.get("from_step") or ""),
            to_step=str(kwargs.get("to_step") or ""),
            context=kwargs,
        )

    orch.register_callback("cross_line_trigger", _on_cross_line)
    logger.info("six_line_event_router: orchestrator cross_line hook installed")
