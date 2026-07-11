from __future__ import annotations

import os
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.desktop_runtime import (
    build_sqlite_to_postgres_sync_plan,
    ensure_desktop_dirs,
    is_desktop_mode,
    is_valid_remote_database_url,
    load_database_storage_catalog,
    load_deployment_catalog,
    load_or_create_deployment_profile,
    load_or_create_profile,
    mode_by_id,
    redact_database_url,
    resolve_effective_mode_id,
    resolve_storage_mode,
    save_deployment_profile,
    save_profile,
)
from app.desktop_runtime.model_downloader import ModelAsset, download_model, load_manifest
from app.desktop_runtime.support_bundle import build_support_bundle_zip
from app.infrastructure.auth.dependencies import get_logged_in_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

router = APIRouter(prefix="/api/desktop", tags=["desktop-runtime"])


class DownloadModelRequest(BaseModel):
    name: str
    version: str
    url: str
    sha256: str
    size: int | None = None


class DeploymentSettingsUpdate(BaseModel):
    mode: str
    postgresUrl: str | None = None
    postgres_url: str | None = None


@router.get("/status")
def desktop_status(request: Request):
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    db_url = os.environ.get("DATABASE_URL", "")
    prof_path, profile = load_or_create_profile(dirs["root"])
    storage_mode = resolve_storage_mode(db_url, profile)
    app = request.app
    mods_full = bool(getattr(app.state, "mods_full_load_done", False))
    mods_bg = bool(getattr(app.state, "mods_background_load_scheduled", False))
    routes_ready = not bool(getattr(app.state, "deferred_routes_pending", False))
    timing: dict = {}
    try:
        from app.fastapi_app.startup_timing import startup_timing_snapshot

        timing = startup_timing_snapshot()
    except RECOVERABLE_ERRORS:
        timing = {}
    db_recovery = _resolve_db_recovery_status()
    last_backup = _resolve_last_backup(dirs)
    return {
        "desktopMode": is_desktop_mode(),
        "dataDir": str(dirs["root"]),
        "database": str(dirs["data"] / "xcagi.db"),
        "modsDir": str(dirs["mods"]),
        "modelsDir": str(dirs["models"]),
        "webModeCompatible": True,
        "storageMode": storage_mode,
        "databaseUrlRedacted": redact_database_url(db_url),
        "profilePath": str(prof_path),
        "modsRoutesLoaded": bool(getattr(app.state, "mods_routes_loaded", False)),
        "modsFullLoadDone": mods_full,
        "modsBackgroundLoadScheduled": mods_bg,
        "appRoutesReady": routes_ready,
        "readyForUi": routes_ready,
        "modsReady": mods_full or not mods_bg,
        "startupTiming": timing,
        "dbRecovery": db_recovery,
        "lastBackup": last_backup,
    }


@router.get("/deployment")
def desktop_deployment_status() -> dict[str, Any]:
    """Return the active desktop deployment profile and migration plan."""
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    catalog = load_deployment_catalog()
    database_storage_catalog = load_database_storage_catalog()
    deployment_path, deployment_profile = load_or_create_deployment_profile(dirs["root"], catalog)
    db_profile_path, db_profile = load_or_create_profile(dirs["root"])
    db_url = os.environ.get("DATABASE_URL", "")
    storage_mode = resolve_storage_mode(db_url, db_profile)
    current_mode_id = resolve_effective_mode_id(
        catalog, deployment_profile, storage_mode=storage_mode
    )
    current_mode = mode_by_id(catalog, current_mode_id) or {}
    remote = db_profile.get("remote") if isinstance(db_profile.get("remote"), dict) else {}
    postgres_url = str(remote.get("database_url") or "").strip()
    sqlite_path = str(dirs["data"] / "xcagi.db")
    sync_plan = build_sqlite_to_postgres_sync_plan(
        database_storage_catalog,
        sqlite_path=sqlite_path,
        postgres_url=postgres_url or "<postgres-url>",
        data_root=str(dirs["root"]),
    )
    return {
        "success": True,
        "desktopMode": is_desktop_mode(),
        "catalog": catalog,
        "databaseStorageCatalog": database_storage_catalog,
        "modes": catalog.get("modes") or [],
        "currentMode": current_mode_id,
        "currentModeDetail": current_mode,
        "deploymentProfilePath": str(deployment_path),
        "databaseProfilePath": str(db_profile_path),
        "database": {
            "storageMode": storage_mode,
            "sqlitePath": sqlite_path,
            "databaseUrlRedacted": redact_database_url(db_url),
            "postgresUrlRedacted": redact_database_url(postgres_url),
        },
        "effective": {
            "mode": current_mode_id,
            "networkScope": current_mode.get("networkScope"),
            "aiMode": current_mode.get("aiMode"),
            "databaseMode": current_mode.get("databaseMode"),
            "mobileConnection": current_mode.get("mobileConnection"),
            "performanceProfile": current_mode.get("performanceProfile"),
            "allowsOutbound": current_mode.get("allowsOutbound"),
            "requiresPostgresql": current_mode.get("requiresPostgresql"),
        },
        "syncPlan": sync_plan,
        "restartRequired": False,
    }


@router.put("/deployment")
def update_desktop_deployment_settings(
    request: DeploymentSettingsUpdate,
) -> dict[str, Any]:
    """Persist the requested deployment mode and report restart requirements."""
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    catalog = load_deployment_catalog()
    database_storage_catalog = load_database_storage_catalog()
    mode_id = str(request.mode or "").strip()
    mode = mode_by_id(catalog, mode_id)
    if not mode:
        raise HTTPException(status_code=400, detail=f"未知部署模式: {mode_id}")

    _db_profile_path, db_profile = load_or_create_profile(dirs["root"])
    remote = db_profile.get("remote") if isinstance(db_profile.get("remote"), dict) else {}
    requested_pg_url = str(request.postgresUrl or request.postgres_url or "").strip()
    existing_pg_url = str(remote.get("database_url") or "").strip()
    postgres_url = requested_pg_url or existing_pg_url

    requires_postgresql = bool(mode.get("requiresPostgresql"))
    if requires_postgresql:
        if not is_valid_remote_database_url(postgres_url):
            raise HTTPException(
                status_code=400,
                detail="性能模式需要填写 postgresql/postgresql+psycopg 数据库连接地址",
            )
        save_profile(
            dirs["root"],
            {
                "version": 1,
                "mode": "remote",
                "remote": {"enabled": True, "database_url": postgres_url},
            },
        )
    else:
        save_profile(
            dirs["root"],
            {
                "version": 1,
                "mode": "local",
                "remote": {"enabled": False, "database_url": existing_pg_url},
            },
        )

    deployment_path, deployment_profile = save_deployment_profile(dirs["root"], mode_id, catalog)
    sqlite_path = str(dirs["data"] / "xcagi.db")
    sync_plan = build_sqlite_to_postgres_sync_plan(
        database_storage_catalog,
        sqlite_path=sqlite_path,
        postgres_url=postgres_url or "<postgres-url>",
        data_root=str(dirs["root"]),
    )
    restart_required = requires_postgresql or os.environ.get("DATABASE_URL", "").startswith(
        "postgres"
    )
    return {
        "success": True,
        "mode": deployment_profile["mode"],
        "modeDetail": mode,
        "deploymentProfilePath": str(deployment_path),
        "databaseProfilePath": str(dirs["root"] / "config" / "database.json"),
        "database": {
            "storageMode": "remote_postgresql" if requires_postgresql else "local_sqlite",
            "sqlitePath": sqlite_path,
            "postgresUrlRedacted": redact_database_url(postgres_url),
        },
        "syncPlan": sync_plan if requires_postgresql else None,
        "restartRequired": restart_required,
    }


def _resolve_db_recovery_status() -> dict[str, str | None]:
    """解析启动自检 + 自动恢复的状态，供前端/Electron 感知。

    `XCAGI_DESKTOP_DB_RECOVERY` 由 `configure_desktop_environment` 在启动时设置：
    - 未设置：未进入桌面模式或库健康（ok）
    - "corrupt_no_backup"：库损坏且无可用备份（严重，需提示用户）
    - "restored:{filename}"：库损坏但已从备份恢复（警告，需提示用户）
    """
    raw = (os.environ.get("XCAGI_DESKTOP_DB_RECOVERY") or "").strip()
    if not raw:
        return {"action": "ok", "detail": None}
    if raw.startswith("restored:"):
        return {"action": "restored", "detail": raw.split(":", 1)[1]}
    return {"action": raw, "detail": None}


def _resolve_last_backup(dirs: dict) -> dict[str, str | int | None]:
    """返回最近一次备份信息（路径/文件名/时间/大小），无备份时各字段为 None。"""
    try:
        from app.desktop_runtime.backup_scheduler import get_last_backup_info

        return get_last_backup_info(dirs["root"])
    except RECOVERABLE_ERRORS:
        return {"path": None, "filename": None, "timestamp": None, "size": None}


@router.get("/models")
def list_models(_user=Depends(get_logged_in_user)):
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    root = dirs["models"]
    models = []
    for path in root.glob("*/*"):
        if path.is_dir():
            models.append({"name": path.parent.name, "version": path.name, "path": str(path)})
    return {"models": models}


@router.post("/models/download")
def download_model_asset(request: DownloadModelRequest, _user=Depends(get_logged_in_user)):
    if not is_desktop_mode():
        raise HTTPException(status_code=409, detail="模型下载仅在桌面模式下可写入 userData")
    asset = ModelAsset(**request.model_dump())
    target = download_model(asset, data_dir=os.environ.get("XCAGI_DATA_DIR"))
    return {"success": True, "path": str(target)}


@router.post("/models/install-manifest")
def install_manifest(path: str, _user=Depends(get_logged_in_user)):
    if not is_desktop_mode():
        raise HTTPException(status_code=409, detail="模型下载仅在桌面模式下可写入 userData")
    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    raw_path = os.fspath(path)
    try:
        if not raw_path or chr(0) in raw_path:
            raise ValueError("empty or NUL-containing path")
        data_root = os.path.realpath(os.path.abspath(os.fspath(dirs["root"])))
        data_root_prefix = data_root if data_root.endswith(os.sep) else data_root + os.sep
        candidate_lexical = os.path.normpath(
            raw_path if os.path.isabs(raw_path) else os.path.join(data_root, raw_path)
        )
        if candidate_lexical != data_root and not candidate_lexical.startswith(data_root_prefix):
            raise ValueError("path escapes desktop data root")
        candidate_real = os.path.realpath(candidate_lexical)
        if candidate_real != data_root and not candidate_real.startswith(data_root_prefix):
            raise ValueError("resolved path escapes desktop data root")
        manifest_path = Path(candidate_real)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="manifest path must stay within desktop data directory",
        ) from None
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="manifest not found")
    targets = [
        str(target)
        for target in (
            download_model(asset, data_dir=os.environ.get("XCAGI_DATA_DIR"))
            for asset in load_manifest(manifest_path)
        )
    ]
    return {"success": True, "files": targets}


@router.get("/support-bundle")
def download_support_bundle(request: Request, _user=Depends(get_logged_in_user)):
    """ZIP：环境摘要 + 近期后端日志节选（不含数据库正文）。仅桌面模式；需登录。"""
    if not is_desktop_mode():
        raise HTTPException(status_code=409, detail="诊断包仅在桌面模式下可用")
    try:
        raw = build_support_bundle_zip(fastapi_version=getattr(request.app, "version", "unknown"))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    buf = BytesIO(raw)
    buf.seek(0)
    fname = f"xcagi-support-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
