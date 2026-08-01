"""客户私有 Mod 的节点推进、流程汇总与前端投影。"""

from __future__ import annotations

import json
from typing import Any

from app.application.private_mod_delivery_state import (
    _STATE_LOCK,
    HAPPY_PATH,
    STAGE_LABELS,
    STAGE_TRANSITIONS,
    STAGES,
    TRACKS,
    _default_node,
    _ensure_project,
    _migrate_tracks,
    _now_iso,
    _read_state,
    _rollup_track_status,
    _write_state,
    allowed_next_stages,
    assert_stage_transition,
    normalize_track,
    stage_goal,
)


def set_track_status(
    scope_key: str,
    mod_id: str,
    track: str,
    status: str,
    *,
    note: str = "",
    name: str = "",
    version: str = "",
    node_id: str = "",
) -> dict[str, Any]:
    track = normalize_track(track)
    if track not in TRACKS:
        raise ValueError(f"未知交付轨道: {track}")
    if status not in STAGES:
        raise ValueError(f"未知交付阶段: {status}")
    nid = str(node_id or "").strip()
    if nid:
        return set_node_status(
            scope_key,
            mod_id,
            track,
            nid,
            status,
            note=note,
            name=name,
            version=version,
        )
    with _STATE_LOCK:
        state = _read_state()
        accounts = state.setdefault("accounts", {})
        scope = accounts.setdefault(scope_key, {})
        project = _ensure_project(scope, mod_id, name=name, version=version)
        row = project["tracks"][track]
        current = str(row.get("status") or "production")
        assert_stage_transition(current, status)
        if row.get("status") != status:
            row["status"] = status
            row["updated_at"] = _now_iso()
            timeline = list(row.get("timeline") or [])
            event = {"status": status, "at": row["updated_at"]}
            if str(note or "").strip():
                event["note"] = str(note).strip()[:500]
            row["timeline"] = [*timeline, event][-30:]
            # 整轨推进只同步「当前可跃迁到目标」的节点，禁止强行改写其它节点
            nodes = row.get("nodes") if isinstance(row.get("nodes"), dict) else {}
            for node in nodes.values():
                if not isinstance(node, dict):
                    continue
                node_cur = str(node.get("status") or "production")
                if node_cur == status:
                    continue
                if status in STAGE_TRANSITIONS.get(node_cur, ()):
                    node["status"] = status
                    node["updated_at"] = row["updated_at"]
        project["updated_at"] = _now_iso()
        _write_state(state)
        return json.loads(json.dumps(project, ensure_ascii=False))


def set_node_status(
    scope_key: str,
    mod_id: str,
    track: str,
    node_id: str,
    status: str,
    *,
    note: str = "",
    name: str = "",
    version: str = "",
) -> dict[str, Any]:
    track = normalize_track(track)
    nid = str(node_id or "").strip()
    if track not in TRACKS:
        raise ValueError(f"未知交付轨道: {track}")
    if not nid:
        raise ValueError("缺少 node_id")
    if status not in STAGES:
        raise ValueError(f"未知交付阶段: {status}")
    with _STATE_LOCK:
        state = _read_state()
        accounts = state.setdefault("accounts", {})
        scope = accounts.setdefault(scope_key, {})
        project = _ensure_project(scope, mod_id, name=name, version=version)
        track_row = project["tracks"][track]
        nodes = track_row.setdefault("nodes", {})
        if not isinstance(nodes, dict):
            nodes = {}
            track_row["nodes"] = nodes
        node = nodes.setdefault(nid, _default_node())
        if not isinstance(node, dict):
            node = _default_node()
            nodes[nid] = node
        current = str(node.get("status") or "production")
        assert_stage_transition(current, status)
        if node.get("status") != status:
            node["status"] = status
            node["updated_at"] = _now_iso()
            timeline = list(node.get("timeline") or [])
            event = {"status": status, "at": node["updated_at"]}
            if str(note or "").strip():
                event["note"] = str(note).strip()[:500]
            node["timeline"] = [*timeline, event][-30:]
        track_row["status"] = _rollup_track_status(track_row)
        track_row["updated_at"] = _now_iso()
        project["updated_at"] = _now_iso()
        _write_state(state)
        return json.loads(json.dumps(project, ensure_ascii=False))


def attach_track_nodes(
    project: dict[str, Any],
    declared: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """把 SSOT/manifest 声明的节点与本地进度合并，供生产员工面板渲染。"""
    tracks = project.get("tracks") if isinstance(project.get("tracks"), dict) else {}
    tracks = _migrate_tracks(dict(tracks))
    out: dict[str, list[dict[str, Any]]] = {"modules": [], "employees": []}
    for track in TRACKS:
        track_row = tracks.get(track) if isinstance(tracks.get(track), dict) else {}
        node_state = track_row.get("nodes") if isinstance(track_row.get("nodes"), dict) else {}
        declared_nodes = declared.get(track) if isinstance(declared.get(track), list) else []
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in declared_nodes:
            if not isinstance(item, dict):
                continue
            nid = str(item.get("id") or "").strip()
            label = str(item.get("label") or nid).strip()
            if not nid or nid in seen:
                continue
            seen.add(nid)
            state = node_state.get(nid) if isinstance(node_state.get(nid), dict) else {}
            status = str(state.get("status") or "production")
            next_stages = allowed_next_stages(status)
            timeline = list(state.get("timeline") or [])[-30:]
            merged.append(
                {
                    "id": nid,
                    "label": label,
                    "summary": str(item.get("summary") or "").strip(),
                    "status": status,
                    "status_label": stage_label(track, status),
                    "goal": stage_goal(status),
                    "next_stages": next_stages,
                    "next_stage_labels": {s: stage_label(track, s) for s in next_stages},
                    "happy_path": list(HAPPY_PATH),
                    "timeline": timeline,
                    "updated_at": str(state.get("updated_at") or ""),
                }
            )
        out[track] = merged
    return out


def overall_status(project: dict[str, Any]) -> str:
    tracks = project.get("tracks") if isinstance(project.get("tracks"), dict) else {}
    tracks = _migrate_tracks(dict(tracks))
    statuses = [str((tracks.get(k) or {}).get("status") or "production") for k in TRACKS]
    if all(status == "delivered" for status in statuses):
        return "delivered"
    if any(status == "rework" for status in statuses):
        return "rework"
    if any(status == "acceptance" for status in statuses):
        return "acceptance"
    if any(status == "testing" for status in statuses):
        return "testing"
    if any(status in {"delivered", "partial"} for status in statuses):
        return "partial"
    return "production"


def stage_label(track: str, status: str) -> str:
    track = normalize_track(track)
    if status == "partial":
        return "部分完成"
    if track == "employees" and status == "delivered":
        return TRACKS[track]["delivered_label"]
    return STAGE_LABELS.get(status, status)


__all__ = [
    "attach_track_nodes",
    "overall_status",
    "set_node_status",
    "set_track_status",
    "stage_label",
]
