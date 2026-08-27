from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
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
from app.runtime_integrity import runtime_integrity_snapshot
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.security.safe_download_path import (
    UnsafeDownloadPathError,
    resolve_under_allowed_dirs,
)

router = APIRouter(prefix="/api/desktop", tags=["desktop-runtime"])

_MAX_CRASH_DUMP_BYTES = 20 * 1024 * 1024
_MAX_CRASH_JSON_BYTES = 1024 * 1024
_ALLOWED_CRASH_SUFFIXES = {".dmp", ".zip", ".json", ".txt", ".log"}


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


class UpdateInstallationReceiptReport(BaseModel):
    installation_id: str
    idempotency_key: str
    channel: str = "stable"
    platform: str = ""
    target_version: str = ""
    target_build_sha: str = ""
    installed_version: str = ""
    installed_build_sha: str = ""
    status: str
    error: str = ""
    source: str = "desktop_ota"
    reported_at: datetime | None = None


@router.post("/update-install-receipts/report")
async def report_update_install_receipt(body: UpdateInstallationReceiptReport, request: Request):
    """由 Electron 主进程在更新后稳定启动或回滚后调用。"""
    if not is_desktop_mode():
        raise HTTPException(403, "仅桌面运行时可上报安装回执")
    client_host = str(getattr(getattr(request, "client", None), "host", "") or "")
    if client_host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "安装回执只接受本机调用")
    if body.status not in {"installed", "failed", "rolled_back"}:
        raise HTTPException(422, "无效的安装回执状态")
    from app.fastapi_routes.market_account import (
        _proxy_json,
        latest_session_market_token,
    )

    token = latest_session_market_token()
    if not token:
        raise HTTPException(409, "当前桌面会话未绑定市场账号，回执已留在本机等待重试")
    return await _proxy_json(
        "POST",
        "/api/update-installations/receipts",
        json_body=body.model_dump(mode="json"),
        authorization=token,
        timeout=10.0,
        retries=2,
    )


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
    runtime = runtime_integrity_snapshot(app)
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
        "runtimeStatus": runtime["status"],
        "degraded": runtime["status"] != "healthy",
        "degradedReasons": runtime["degraded_reasons"],
        "runtimeIntegrity": runtime,
        "modsReady": mods_full or not mods_bg,
        "startupTiming": timing,
        "dbRecovery": db_recovery,
        "lastBackup": last_backup,
    }


@router.get("/deployment", response_model=dict[str, object])
def desktop_deployment_status():
    """Return the active desktop deployment, database, and migration plan."""
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


@router.put("/deployment", response_model=dict[str, object])
def update_desktop_deployment_settings(request: DeploymentSettingsUpdate):
    """Persist a desktop deployment mode and report any required restart or sync."""
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
    if not isinstance(remote, dict):
        remote = {}
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


@router.get("/mobile-pairing-status")
def mobile_pairing_status(_user=Depends(get_logged_in_user)):
    """本机与手机的服务器中继绑定状态，供设置页「移动端连接」展示。

    与手机端「我的 → 服务」的状态文案（server_mode_label）用同一套词汇（服务器中继 / 已绑定），
    让用户在两端看到一致的连接状态，而不是只能靠出码页面猜测是否已连上。
    """
    try:
        from app.application.facades.mobile_relay_facade import cached_desktop_relay_payload

        relay = cached_desktop_relay_payload()
    except RECOVERABLE_ERRORS:
        relay = None
    if not relay:
        return {"paired": False, "mobileUsername": "", "lastRelaySyncAt": 0}
    return {
        "paired": bool(relay.get("paired")),
        "mobileUsername": str(relay.get("mobile_username") or ""),
        "lastRelaySyncAt": int(relay.get("last_relay_sync_at") or 0),
    }


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
    try:
        manifest_path = resolve_under_allowed_dirs(
            path,
            [dirs["uploads"], dirs["cache"], dirs["models"]],
        )
    except UnsafeDownloadPathError as exc:
        raise HTTPException(
            status_code=400, detail="manifest path is outside desktop storage"
        ) from exc
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


@router.post("/crash-report")
async def receive_crash_report(request: Request):
    """接收桌面端 Electron 进程崩溃报告（JSON 或 multipart minidump）。

    不要求登录——崩溃可能发生在用户登录之前。存储到数据目录 crash-reports/ 下，
    供后续诊断分析。
    """
    if not is_desktop_mode():
        raise HTTPException(status_code=409, detail="崩溃报告仅在桌面模式下可用")

    dirs = ensure_desktop_dirs(os.environ.get("XCAGI_DATA_DIR"))
    crash_dir = dirs["root"] / "crash-reports"
    crash_dir.mkdir(parents=True, exist_ok=True)

    content_type = (request.headers.get("content-type") or "").lower()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_CRASH_DUMP_BYTES + 1024 * 1024:
                raise HTTPException(status_code=413, detail="崩溃报告过大")
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length 无效") from None
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    report_id = uuid.uuid4().hex[:12]

    if "multipart/form-data" in content_type:
        saved: list[str] = []
        # The request form owns SpooledTemporaryFile instances for uploaded
        # dumps. Its async context manager closes every upload on success and
        # on validation errors, preventing descriptor leaks in the long-lived
        # desktop backend.
        async with request.form() as form:
            for field_name in form:
                field = form[field_name]
                filename = str(getattr(field, "filename", "") or "").strip()
                reader = getattr(field, "read", None)
                if not filename or not callable(reader):
                    continue
                content = await reader()
                if len(content) > _MAX_CRASH_DUMP_BYTES:
                    raise HTTPException(status_code=413, detail="崩溃转储超过 20 MB")
                ext = Path(filename).suffix.lower()
                if ext not in _ALLOWED_CRASH_SUFFIXES:
                    ext = ".bin"
                target = crash_dir / f"crash-{ts}-{report_id}-{len(saved)}{ext}"
                target.write_bytes(content)
                saved.append(target.name)
        if not saved:
            raise HTTPException(status_code=400, detail="未收到崩溃转储文件")
        return JSONResponse({"saved": True, "files": saved})

    if "application/json" not in content_type:
        raise HTTPException(status_code=415, detail="仅支持 JSON 或 multipart 崩溃报告")
    body = await request.body()
    if len(body) > _MAX_CRASH_JSON_BYTES:
        raise HTTPException(status_code=413, detail="JSON 崩溃报告超过 1 MB")
    target = crash_dir / f"crash-{ts}-{report_id}.json"
    target.write_bytes(body)
    return JSONResponse({"saved": True, "file": target.name})


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
