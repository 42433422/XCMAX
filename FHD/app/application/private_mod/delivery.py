"""客户私有 Mod 的交付状态与私有更新辅助。

私有 Mod 不进入公共员工商店。桌面端只通过当前账号已绑定的 Mod 权益，
访问 MODstore 的账号私有同步接口并拉取最新源码包。
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import quote

from app.infrastructure.mods.catalog_client import catalog_download_to, catalog_get_json
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

TRACKS: dict[str, dict[str, str]] = {
    "business": {"label": "业务模块", "delivered_label": "已交付"},
    "employees": {"label": "AI 员工", "delivered_label": "已上岗"},
}

STAGES: tuple[str, ...] = ("production", "testing", "rework", "acceptance", "delivered")
STAGE_LABELS: dict[str, str] = {
    "production": "制作中",
    "testing": "测试中",
    "rework": "返工中",
    "acceptance": "验收中",
    "delivered": "已交付",
}

_STATE_LOCK = RLock()
_VERSION_TOKEN = re.compile(r"\d+|[A-Za-z]+")


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


def _default_track() -> dict[str, Any]:
    return {"status": "production", "timeline": [], "updated_at": _now_iso()}


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
    for track in TRACKS:
        current = tracks.setdefault(track, _default_track())
        if not isinstance(current, dict):
            tracks[track] = _default_track()
        else:
            current.setdefault("status", "production")
            current.setdefault("timeline", [])
            current.setdefault("updated_at", _now_iso())
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
            for track in TRACKS:
                row = incoming_tracks.get(track) if isinstance(incoming_tracks, dict) else None
                if not isinstance(row, dict):
                    continue
                project["tracks"][track] = {
                    "status": str(row.get("status") or "production"),
                    "timeline": list(row.get("timeline") or [])[-30:],
                    "updated_at": str(row.get("updated_at") or ""),
                }
            if incoming.get("updated_at"):
                project["updated_at"] = str(incoming["updated_at"])
            projects[mod_id] = project
        _write_state(state)


def set_track_status(
    scope_key: str,
    mod_id: str,
    track: str,
    status: str,
    *,
    note: str = "",
    name: str = "",
    version: str = "",
) -> dict[str, Any]:
    if track not in TRACKS:
        raise ValueError(f"未知交付轨道: {track}")
    if status not in STAGES:
        raise ValueError(f"未知交付阶段: {status}")
    with _STATE_LOCK:
        state = _read_state()
        accounts = state.setdefault("accounts", {})
        scope = accounts.setdefault(scope_key, {})
        project = _ensure_project(scope, mod_id, name=name, version=version)
        row = project["tracks"][track]
        if row.get("status") != status:
            row["status"] = status
            row["updated_at"] = _now_iso()
            timeline = list(row.get("timeline") or [])
            event = {"status": status, "at": row["updated_at"]}
            if str(note or "").strip():
                event["note"] = str(note).strip()[:500]
            row["timeline"] = [*timeline, event][-30:]
        project["updated_at"] = _now_iso()
        _write_state(state)
        return json.loads(json.dumps(project, ensure_ascii=False))


def overall_status(project: dict[str, Any]) -> str:
    tracks = project.get("tracks") if isinstance(project.get("tracks"), dict) else {}
    statuses = [str((tracks.get(k) or {}).get("status") or "production") for k in TRACKS]
    if all(status == "delivered" for status in statuses):
        return "delivered"
    if any(status == "rework" for status in statuses):
        return "rework"
    if any(status == "acceptance" for status in statuses):
        return "acceptance"
    if any(status == "testing" for status in statuses):
        return "testing"
    if any(status == "delivered" for status in statuses):
        return "partial"
    return "production"


def stage_label(track: str, status: str) -> str:
    if track == "employees" and status == "delivered":
        return TRACKS[track]["delivered_label"]
    return STAGE_LABELS.get(status, status)


def version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """比较常见的 semver/内部版本，不依赖额外包。"""
    raw = str(value or "").strip().lstrip("vV")
    tokens: list[tuple[int, int | str]] = []
    for token in _VERSION_TOKEN.findall(raw):
        if token.isdigit():
            tokens.append((0, int(token)))
        else:
            tokens.append((1, token.lower()))
    return tuple(tokens) or ((0, 0),)


def is_newer_version(remote: str, local: str) -> bool:
    return bool(str(remote or "").strip()) and version_key(remote) > version_key(local)


def _auth_header(token: str) -> str:
    raw = str(token or "").strip()
    return raw if raw.lower().startswith("bearer ") else f"Bearer {raw}"


async def fetch_private_mod_library(market_token: str) -> list[dict[str, Any]]:
    token = str(market_token or "").strip()
    if not token:
        return []
    payload = await catalog_get_json(
        "/v1/mod-sync/mods",
        headers={"Authorization": _auth_header(token)},
    )
    raw = payload.get("data")
    if not isinstance(raw, list):
        raw = payload.get("mods")
    return [dict(row) for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def _library_row_by_id(rows: list[dict[str, Any]], mod_id: str) -> dict[str, Any] | None:
    target = str(mod_id or "").strip()
    for row in rows:
        if str(row.get("id") or "").strip() == target:
            return row
    return None


async def update_private_mod_from_library(
    mod_id: str,
    market_token: str,
    *,
    expected_version: str = "",
) -> dict[str, Any]:
    """从账号私有 Mod 库下载并安装最新 Mod。"""
    mid = str(mod_id or "").strip()
    if not mid or "/" in mid or "\\" in mid:
        raise ValueError("非法客户 Mod id")
    rows = await fetch_private_mod_library(market_token)
    remote = _library_row_by_id(rows, mid)
    if not remote:
        raise LookupError("当前账号没有该客户 Mod 的私有版本")
    remote_version = str(remote.get("version") or "").strip()
    if not remote_version:
        raise ValueError("私有 Mod 版本信息缺失")
    if expected_version and expected_version != remote_version:
        raise ValueError("私有 Mod 版本已变化，请刷新后重试")

    from app.infrastructure.mods.mod_manager import get_mod_manager

    manager = get_mod_manager()
    local = next(
        (m for m in manager.scan_mods(use_cache=False) if str(m.id or "").strip() == mid),
        None,
    )
    local_version = str(local.version or "") if local else ""
    if local and not is_newer_version(remote_version, local_version):
        return {
            "success": True,
            "updated": False,
            "mod_id": mid,
            "current_version": local_version,
            "latest_version": remote_version,
            "message": "当前已是私有 Mod 最新版本",
        }

    token = str(market_token or "").strip()
    if not token:
        raise PermissionError("缺少市场登录凭证，无法更新客户私有 Mod")
    tmp = tempfile.NamedTemporaryFile(prefix="xcagi-private-mod-", suffix=".zip", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        await catalog_download_to(
            f"/v1/mod-sync/export-zip/{quote(mid, safe='')}",
            tmp_path,
            headers={"Authorization": _auth_header(token)},
        )
        from app.infrastructure.mods.package import ModPackage

        with tempfile.TemporaryDirectory(prefix="xcagi-private-mod-check-") as check_dir:
            _, manifest = ModPackage.extract_package(str(tmp_path), check_dir, verify_signature=False)
        manifest_id = str(manifest.get("id") or "").strip()
        manifest_version = str(manifest.get("version") or "").strip()
        if manifest_id != mid:
            raise ValueError("私有 Mod 包身份校验失败")
        if manifest_version and manifest_version != remote_version:
            raise ValueError("私有 Mod 包版本与私有目录不一致")

        verify_signature = os.environ.get("XCAGI_REQUIRE_SIGNED_MODS", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        ok, message, metadata = manager.install_mod_package(
            str(tmp_path), verify_signature=verify_signature, activate=True
        )
        if not ok:
            raise RuntimeError(message)
        try:
            from app.infrastructure.mods.mod_manager import ensure_mod_api_ready

            ensure_mod_api_ready(mid)
        except RECOVERABLE_ERRORS:
            logger.warning("私有 Mod %s API 路由刷新失败", mid, exc_info=True)
        return {
            "success": True,
            "updated": True,
            "mod_id": mid,
            "previous_version": local_version,
            "current_version": str(getattr(metadata, "version", "") or remote_version),
            "latest_version": remote_version,
            "message": message,
        }
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass


__all__ = [
    "STAGES",
    "STAGE_LABELS",
    "TRACKS",
    "account_projects",
    "account_scope",
    "apply_account_state",
    "export_account_state",
    "fetch_private_mod_library",
    "is_newer_version",
    "overall_status",
    "project_state",
    "set_track_status",
    "stage_label",
    "update_private_mod_from_library",
    "version_key",
]
