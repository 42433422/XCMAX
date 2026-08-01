"""客户私有 Mod 的流程定义与账号隔离状态存储。"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# 与 customer_delivery.json delivery_model.tracks 对齐；business 为历史别名
TRACKS: dict[str, dict[str, str]] = {
    "modules": {
        "label": "业务模块",
        "delivered_label": "已交付",
        "legacy_ids": ["business"],
    },
    "employees": {"label": "AI 员工", "delivered_label": "已上岗", "legacy_ids": []},
}
TRACK_ALIAS = {"business": "modules"}

STAGES: tuple[str, ...] = ("production", "testing", "rework", "acceptance", "delivered")
HAPPY_PATH: tuple[str, ...] = ("production", "testing", "acceptance", "delivered")
STAGE_LABELS: dict[str, str] = {
    "production": "制作中",
    "testing": "测试中",
    "rework": "返工中",
    "acceptance": "验收中",
    "delivered": "已交付",
}
STAGE_GOALS: dict[str, str] = {
    "production": "完成开发与自测，进入可测状态",
    "testing": "用例通过；不通过则返工",
    "rework": "修复问题后重回测试",
    "acceptance": "生产/客户验收通过后交付",
    "delivered": "节点交付完成，流程结束",
}
# 阶段是流程：只允许下列跃迁，禁止跨阶段跳跃
STAGE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "production": ("testing",),
    "testing": ("acceptance", "rework"),
    "rework": ("testing",),
    "acceptance": ("delivered", "rework"),
    "delivered": (),
}


def allowed_next_stages(current: str) -> list[str]:
    cur = str(current or "production").strip() or "production"
    return list(STAGE_TRANSITIONS.get(cur, ()))


def assert_stage_transition(current: str, target: str) -> None:
    cur = str(current or "production").strip() or "production"
    nxt = str(target or "").strip()
    if cur == nxt:
        return
    allowed = STAGE_TRANSITIONS.get(cur, ())
    if nxt not in allowed:
        cur_label = STAGE_LABELS.get(cur, cur)
        nxt_label = STAGE_LABELS.get(nxt, nxt)
        allow_txt = "、".join(STAGE_LABELS.get(x, x) for x in allowed) or "无（已结束）"
        raise ValueError(
            f"阶段不可从「{cur_label}」直接切换到「{nxt_label}」。下一步只能：{allow_txt}"
        )


def stage_goal(status: str) -> str:
    return STAGE_GOALS.get(str(status or "").strip(), "")


def load_stage_flow_from_ssot() -> dict[str, Any]:
    """优先读 customer_delivery.json 的 stage_flow；失败则用内置常量。"""
    try:
        from app.mod_sdk.customer_delivery import delivery_model

        model = delivery_model() or {}
        flow = model.get("stage_flow")
        if isinstance(flow, dict) and flow:
            return flow
    except RECOVERABLE_ERRORS:
        pass
    return {
        key: {"label": STAGE_LABELS[key], "goal": STAGE_GOALS[key], "next": list(vals)}
        for key, vals in STAGE_TRANSITIONS.items()
    }

_STATE_LOCK = RLock()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _state_path() -> Path:
    from app.desktop_runtime.paths import get_desktop_data_dir

    root = get_desktop_data_dir() / "data" / "private_mod_delivery"
    root.mkdir(parents=True, exist_ok=True)
    return root / "state.json"


def _read_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {"schema_version": 1, "accounts": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("私有 Mod 交付状态文件不可读，将使用空状态: %s", path)
        return {"schema_version": 1, "accounts": {}}
    if not isinstance(raw, dict):
        return {"schema_version": 1, "accounts": {}}
    accounts = raw.get("accounts")
    if not isinstance(accounts, dict):
        raw["accounts"] = {}
    raw.setdefault("schema_version", 1)
    return raw


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def account_scope(market_user_id: int | None = None, username: str = "") -> str:
    """返回本地状态隔离键，不把账号身份直接暴露给前端。"""
    if market_user_id is not None:
        try:
            uid = int(market_user_id)
            if uid > 0:
                return f"market:{uid}"
        except (TypeError, ValueError):
            pass
    name = str(username or "").strip().lower()
    return f"local:{name}" if name else "local:default"


def merge_orphan_local_delivery_into_market(
    market_scope: str,
    mod_ids: set[str] | list[str] | tuple[str, ...] | None = None,
) -> None:
    """把误写入 ``local:default`` 的定制进度合并进 ``market:{id}``（定制线通道修复）。"""
    target = str(market_scope or "").strip()
    if not target.startswith("market:"):
        return
    wanted = {str(x).strip() for x in (mod_ids or []) if str(x).strip()}
    with _STATE_LOCK:
        state = _read_state()
        accounts = state.setdefault("accounts", {})
        orphan = accounts.get("local:default")
        if not isinstance(orphan, dict):
            return
        orphan_projects = orphan.get("projects")
        if not isinstance(orphan_projects, dict) or not orphan_projects:
            return
        scope = accounts.setdefault(target, {})
        if not isinstance(scope.get("projects"), dict):
            scope["projects"] = {}
        changed = False
        for raw_id, incoming in list(orphan_projects.items()):
            mid = str(raw_id or "").strip()
            if not mid or (wanted and mid not in wanted):
                continue
            if not isinstance(incoming, dict):
                continue
            if mid.endswith("-industry"):
                orphan_projects.pop(mid, None)
                changed = True
                continue
            existing = scope["projects"].get(mid)
            if not isinstance(existing, dict):
                scope["projects"][mid] = json.loads(json.dumps(incoming, ensure_ascii=False))
                changed = True
            else:
                src_tracks = incoming.get("tracks") if isinstance(incoming.get("tracks"), dict) else {}
                dst_tracks = existing.setdefault("tracks", {})
                if not isinstance(dst_tracks, dict):
                    existing["tracks"] = {}
                    dst_tracks = existing["tracks"]
                existing["tracks"] = _migrate_tracks(dst_tracks)
                dst_tracks = existing["tracks"]
                for track, src_row in src_tracks.items():
                    track_id = normalize_track(str(track))
                    if track_id not in TRACKS or not isinstance(src_row, dict):
                        continue
                    dst_row = dst_tracks.setdefault(track_id, _default_track())
                    src_nodes = src_row.get("nodes") if isinstance(src_row.get("nodes"), dict) else {}
                    dst_nodes = dst_row.setdefault("nodes", {})
                    if not isinstance(dst_nodes, dict):
                        dst_row["nodes"] = {}
                        dst_nodes = dst_row["nodes"]
                    for nid, nrow in src_nodes.items():
                        node_id = str(nid or "").strip()
                        if not node_id or not isinstance(nrow, dict):
                            continue
                        cur = dst_nodes.get(node_id) if isinstance(dst_nodes.get(node_id), dict) else None
                        if cur is None or str(cur.get("status") or "production") == "production":
                            dst_nodes[node_id] = json.loads(json.dumps(nrow, ensure_ascii=False))
                            changed = True
                    dst_row["status"] = _rollup_track_status(dst_row)
                existing["tracks"] = _migrate_tracks(existing.get("tracks") or {})
            orphan_projects.pop(mid, None)
            changed = True
        if changed:
            if not orphan_projects:
                accounts.pop("local:default", None)
            _write_state(state)


def normalize_track(track: str) -> str:
    tid = str(track or "").strip()
    return TRACK_ALIAS.get(tid, tid)


def _default_node() -> dict[str, Any]:
    return {"status": "production", "timeline": [], "updated_at": _now_iso()}


def _default_track() -> dict[str, Any]:
    return {
        "status": "production",
        "timeline": [],
        "nodes": {},
        "updated_at": _now_iso(),
    }


def _rollup_track_status(track_row: dict[str, Any]) -> str:
    nodes = track_row.get("nodes") if isinstance(track_row.get("nodes"), dict) else {}
    if not nodes:
        return str(track_row.get("status") or "production")
    statuses = [str((row or {}).get("status") or "production") for row in nodes.values() if isinstance(row, dict)]
    if not statuses:
        return str(track_row.get("status") or "production")
    if all(s == "delivered" for s in statuses):
        return "delivered"
    if any(s == "rework" for s in statuses):
        return "rework"
    if any(s == "acceptance" for s in statuses):
        return "acceptance"
    if any(s == "testing" for s in statuses):
        return "testing"
    if any(s == "delivered" for s in statuses):
        return "partial"
    return "production"


def _migrate_tracks(tracks: dict[str, Any]) -> dict[str, Any]:
    """把历史 business 轨迁到 modules，并保证 nodes 容器存在。"""
    if not isinstance(tracks, dict):
        return {}
    if "business" in tracks and "modules" not in tracks:
        tracks["modules"] = tracks.pop("business")
    elif "business" in tracks and "modules" in tracks:
        legacy = tracks.pop("business")
        current = tracks["modules"]
        if isinstance(legacy, dict) and isinstance(current, dict):
            legacy_nodes = legacy.get("nodes") if isinstance(legacy.get("nodes"), dict) else {}
            current_nodes = current.setdefault("nodes", {})
            if isinstance(current_nodes, dict):
                for nid, nrow in legacy_nodes.items():
                    current_nodes.setdefault(nid, nrow)
    for track in TRACKS:
        row = tracks.setdefault(track, _default_track())
        if not isinstance(row, dict):
            tracks[track] = _default_track()
            continue
        row.setdefault("status", "production")
        row.setdefault("timeline", [])
        nodes = row.setdefault("nodes", {})
        if not isinstance(nodes, dict):
            row["nodes"] = {}
        row.setdefault("updated_at", _now_iso())
        row["status"] = _rollup_track_status(row)
    return tracks


def _ensure_project(
    scope: dict[str, Any],
    mod_id: str,
    *,
    name: str = "",
    version: str = "",
) -> dict[str, Any]:
    projects = scope.setdefault("projects", {})
    project = projects.setdefault(mod_id, {})
    project.setdefault("mod_id", mod_id)
    if name:
        project["name"] = name
    else:
        project.setdefault("name", mod_id)
    if version:
        project["last_seen_version"] = version
    tracks = project.setdefault("tracks", {})
    if not isinstance(tracks, dict):
        tracks = {}
        project["tracks"] = tracks
    project["tracks"] = _migrate_tracks(tracks)
    project.setdefault("updated_at", _now_iso())
    return project


def project_state(
    scope_key: str,
    mod_id: str,
    *,
    name: str = "",
    version: str = "",
) -> dict[str, Any]:
    with _STATE_LOCK:
        state = _read_state()
        accounts = state.setdefault("accounts", {})
        scope = accounts.setdefault(scope_key, {})
        project = _ensure_project(scope, mod_id, name=name, version=version)
        _write_state(state)
        return json.loads(json.dumps(project, ensure_ascii=False))


def account_projects(
    scope_key: str,
    mod_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    *,
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """读取某个账号的私有 Mod 项目状态，不为只读查询写入默认项目。"""
    targets = {
        str(mod_id or "").strip()
        for mod_id in (mod_ids or [])
        if str(mod_id or "").strip()
    }
    with _STATE_LOCK:
        state = _read_state()
        scope = state.get("accounts", {}).get(scope_key, {})
        stored = scope.get("projects", {}) if isinstance(scope, dict) else {}
        if not targets and isinstance(stored, dict):
            targets = {str(mod_id).strip() for mod_id in stored if str(mod_id).strip()}
        result: list[dict[str, Any]] = []
        for mod_id in sorted(targets):
            project = stored.get(mod_id) if isinstance(stored, dict) else None
            if isinstance(project, dict):
                result.append(json.loads(json.dumps(project, ensure_ascii=False)))
                continue
            result.append(
                {
                    "mod_id": mod_id,
                    "name": str((names or {}).get(mod_id) or mod_id),
                    "tracks": {track: _default_track() for track in TRACKS},
                    "updated_at": "",
                }
            )
        return result


def export_account_state(scope_key: str) -> dict[str, Any]:
    """导出账号完整交付快照，供 XCmax 同步链路传给管理端。"""
    with _STATE_LOCK:
        state = _read_state()
        scope = state.get("accounts", {}).get(scope_key, {})
        projects = scope.get("projects", {}) if isinstance(scope, dict) else {}
        return {
            "schema_version": 1,
            "projects": json.loads(json.dumps(projects, ensure_ascii=False))
            if isinstance(projects, dict)
            else {},
        }


def apply_account_state(scope_key: str, snapshot: dict[str, Any]) -> None:
    """应用远端同步来的账号交付快照，不再次产生同步事件。"""
    raw_projects = snapshot.get("projects") if isinstance(snapshot, dict) else {}
    if not isinstance(raw_projects, dict):
        return
    with _STATE_LOCK:
        state = _read_state()
        accounts = state.setdefault("accounts", {})
        scope = accounts.setdefault(scope_key, {})
        projects = scope.setdefault("projects", {})
        if not isinstance(projects, dict):
            projects = {}
            scope["projects"] = projects
        for raw_id, incoming in raw_projects.items():
            mod_id = str(raw_id or "").strip()
            if not mod_id or "/" in mod_id or "\\" in mod_id or not isinstance(incoming, dict):
                continue
            project = _ensure_project(
                scope,
                mod_id,
                name=str(incoming.get("name") or mod_id),
                version=str(incoming.get("last_seen_version") or ""),
            )
            incoming_tracks = incoming.get("tracks")
            if isinstance(incoming_tracks, dict):
                incoming_tracks = _migrate_tracks(dict(incoming_tracks))
            for track in TRACKS:
                row = incoming_tracks.get(track) if isinstance(incoming_tracks, dict) else None
                if not isinstance(row, dict):
                    continue
                nodes_in = row.get("nodes") if isinstance(row.get("nodes"), dict) else {}
                nodes_out: dict[str, Any] = {}
                for nid, nrow in nodes_in.items():
                    node_id = str(nid or "").strip()
                    if not node_id or not isinstance(nrow, dict):
                        continue
                    nodes_out[node_id] = {
                        "status": str(nrow.get("status") or "production"),
                        "timeline": list(nrow.get("timeline") or [])[-30:],
                        "updated_at": str(nrow.get("updated_at") or ""),
                    }
                project["tracks"][track] = {
                    "status": str(row.get("status") or "production"),
                    "timeline": list(row.get("timeline") or [])[-30:],
                    "nodes": nodes_out,
                    "updated_at": str(row.get("updated_at") or ""),
                }
                project["tracks"][track]["status"] = _rollup_track_status(project["tracks"][track])
            if incoming.get("updated_at"):
                project["updated_at"] = str(incoming["updated_at"])
            projects[mod_id] = project
        _write_state(state)


__all__ = [
    "HAPPY_PATH",
    "STAGES",
    "STAGE_GOALS",
    "STAGE_LABELS",
    "STAGE_TRANSITIONS",
    "TRACKS",
    "account_projects",
    "account_scope",
    "allowed_next_stages",
    "apply_account_state",
    "assert_stage_transition",
    "export_account_state",
    "load_stage_flow_from_ssot",
    "merge_orphan_local_delivery_into_market",
    "normalize_track",
    "project_state",
    "stage_goal",
]
