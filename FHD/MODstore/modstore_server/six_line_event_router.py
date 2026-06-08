"""六线事件轨路由（MODstore · 与 FHD SSOT 同构）。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from modstore_server.incident_bus import enqueue as incident_enqueue

_BACKLOG_NAME = "six_line_digest_backlog.jsonl"


def _routes_config_path() -> Path | None:
    env = (os.environ.get("XCMAX_MONOREPO_ROOT") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser() / "FHD" / "config" / "six_line_event_routes.json")
    fhd = Path(__file__).resolve().parents[2]
    candidates.append(fhd.parent / "config" / "six_line_event_routes.json")
    candidates.append(fhd / "config" / "six_line_event_routes.json")
    for p in candidates:
        if p.is_file():
            return p
    return None


def load_config() -> dict[str, Any]:
    path = _routes_config_path()
    if not path:
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _backlog_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    d = root / "data" / "six_line"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_backlog(entry: dict[str, Any]) -> None:
    path = _backlog_dir() / _BACKLOG_NAME
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _match_route(cfg: dict[str, Any], step_id: str, status: str, event_type: str | None) -> dict[str, Any] | None:
    for key in ("operations_line", "cross_line", "incident_defaults"):
        for raw in cfg.get(key) or []:
            if not isinstance(raw, dict):
                continue
            sid = raw.get("step_id") or raw.get("line_step")
            if sid and step_id and sid != step_id:
                continue
            status_in = raw.get("status_in") or []
            if status_in and status not in status_in:
                continue
            et = raw.get("event_type")
            if event_type and et and et != event_type and raw.get("also_incident") != event_type:
                if not (step_id and sid == step_id):
                    continue
            if event_type and not et and not raw.get("also_incident") and key == "incident_defaults":
                if raw.get("event_type") != event_type:
                    continue
            return raw
    if event_type:
        for raw in cfg.get("incident_defaults") or []:
            if raw.get("event_type") == event_type:
                return raw
    return None


def dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    step_id = str(payload.get("step_id") or "").strip()
    status = str(payload.get("status") or "progress").strip()
    event_type = payload.get("event_type")
    if event_type is not None:
        event_type = str(event_type).strip() or None

    route = _match_route(cfg, step_id, status, event_type)
    if not route:
        return {"ok": True, "matched": False, "action": "unrouted"}

    action = str(route.get("action") or "incident")
    results: list[dict[str, Any]] = []
    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}

    if action == "digest_backlog":
        entry = {
            "route_id": route.get("id"),
            "step_id": step_id or route.get("line_step"),
            "dispatch_line": route.get("dispatch_line"),
            "list_kind": route.get("list_kind") or "patches",
            "priority": route.get("priority"),
            "event_type": event_type or route.get("event_type"),
            "payload": body,
        }
        append_backlog(entry)
        results.append({"sink": "digest_backlog"})

    if action == "incident" or route.get("also_incident"):
        inc = {
            "route_id": route.get("id"),
            "event_type": event_type or route.get("event_type") or route.get("also_incident"),
            "priority": route.get("priority"),
            "step_id": step_id,
            "six_line": route.get("six_line"),
            "payload": body,
        }
        incident_enqueue(inc)
        results.append({"sink": "incident_bus"})

    return {
        "ok": True,
        "matched": True,
        "route_id": route.get("id"),
        "action": action,
        "priority": route.get("priority"),
        "results": results,
    }


def status_snapshot() -> dict[str, Any]:
    cfg = load_config()
    bl = _backlog_dir() / _BACKLOG_NAME
    backlog_n = 0
    if bl.is_file():
        backlog_n = sum(1 for ln in bl.read_text(encoding="utf-8").splitlines() if ln.strip())
    from modstore_server.incident_bus import pending_count

    return {
        "operations_routes": len(cfg.get("operations_line") or []),
        "cross_line_routes": len(cfg.get("cross_line") or []),
        "incident_defaults": len(cfg.get("incident_defaults") or []),
        "digest_backlog_pending": backlog_n,
        "incident_pending": pending_count(),
        "version": cfg.get("version"),
    }
