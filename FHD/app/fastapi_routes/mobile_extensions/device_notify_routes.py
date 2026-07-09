"""Mobile 设备注册 / 通知 / LAN APK 更新 routes (split from mobile_api_extensions).

Included into ``extension_router``; handlers and helpers are re-exported from
``mobile_api_extensions`` for tests and patch compatibility.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.fastapi_routes.mobile_api import get_mobile_user
from app.fastapi_routes.mobile_extensions import _ext as mext
from app.utils.mobile_api import format_mobile_response

logger = logging.getLogger(__name__)

device_notify_router = APIRouter()

from app.fastapi_routes.mobile_extensions.models import (
    DeviceRegisterBody,
    LanAndroidUpdateNotifyBody,
)

# ── 设备管理 ──


@device_notify_router.post("/devices/register")
async def mobile_device_register(body: DeviceRegisterBody, user=Depends(get_mobile_user)):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    mext._ensure_mobile_device_table()
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db
    from app.utils.time import utc_now_naive

    token = (body.push_token or body.fcm_token).strip()
    provider = (body.push_provider or "fcm").strip().lower()[:16]
    if not token:
        return JSONResponse(
            format_mobile_response(None, "缺少 push_token", success=False, code=400),
            status_code=400,
        )
    with get_db() as db:
        row = (
            db.query(MobileDeviceToken)
            .filter(
                MobileDeviceToken.user_id == user.id,
                MobileDeviceToken.fcm_token == body.fcm_token.strip(),
            )
            .first()
        )
        if row:
            row.device_label = body.device_label[:200]
            row.platform = body.platform[:32]
            row.fcm_token = body.fcm_token.strip()[:512]
            row.push_provider = provider
            row.push_token = token
            row.product_sku = (body.product_sku or "personal")[:32]
            row.updated_at = utc_now_naive()
        else:
            db.add(
                MobileDeviceToken(
                    user_id=user.id,
                    fcm_token=body.fcm_token.strip(),
                    push_provider=provider,
                    push_token=token,
                    product_sku=(body.product_sku or "personal")[:32],
                    platform=body.platform[:32],
                    device_label=body.device_label[:200],
                )
            )
    return format_mobile_response(data={"registered": True})


@device_notify_router.delete("/devices/unregister")
async def mobile_device_unregister(
    fcm_token: str = Query(..., min_length=8),
    user=Depends(get_mobile_user),
):
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    mext._ensure_mobile_device_table()
    from app.db.models.mobile_device import MobileDeviceToken
    from app.db.session import get_db

    with get_db() as db:
        db.query(MobileDeviceToken).filter(
            MobileDeviceToken.user_id == user.id,
            MobileDeviceToken.fcm_token == fcm_token.strip(),
        ).delete()
    return format_mobile_response(data={"unregistered": True})


@device_notify_router.get("/notifications/pending")
async def mobile_notifications_pending(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_mobile_user),
):
    """自建推送后台通道:返回未送达的离线通知并标记 delivered（客户端 WorkManager 轮询）。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401), status_code=401
        )
    mext._ensure_outbox_table()
    import json as _json

    from app.db.models.mobile_notification import MobileNotificationOutbox
    from app.db.session import get_db
    from app.utils.time import utc_now_naive

    items: list[dict] = []
    with get_db() as db:
        rows = (
            db.query(MobileNotificationOutbox)
            .filter(
                MobileNotificationOutbox.user_id == user.id,
                MobileNotificationOutbox.delivered.is_(False),
            )
            .order_by(MobileNotificationOutbox.created_at.asc())
            .limit(limit)
            .all()
        )
        now = utc_now_naive()
        for r in rows:
            try:
                data = _json.loads(r.data_json or "{}")
            except (ValueError, TypeError):
                data = {}
            items.append(
                {
                    "id": r.id,
                    "title": r.title,
                    "body": r.body,
                    "route": r.route,
                    "channel": r.channel,
                    "data": data,
                }
            )
            r.delivered = True
            r.delivered_at = now
    return format_mobile_response(data={"notifications": items})


# ── 局域网 APK 自更新（本机 publish → 手机检查更新）──


def _lan_releases_root() -> Path | None:
    try:
        from app.fastapi_app.static_mounts import resolve_lan_releases_dir

        root = resolve_lan_releases_dir()
        return Path(root) if root else None
    except Exception:  # noqa: BLE001
        return None


def _lan_public_base_url(request: Request) -> str:
    """拼手机可达的本机基址（优先请求 Host，避免写死 loopback）。"""
    forwarded = (request.headers.get("x-forwarded-host") or "").strip()
    host = forwarded.split(",")[0].strip() if forwarded else ""
    if not host:
        host = (request.headers.get("host") or "").strip()
    if not host:
        hostname = (request.url.hostname or "").strip() or "127.0.0.1"
        port = request.url.port
        host = f"{hostname}:{port}" if port else hostname
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").strip()
    return f"{scheme}://{host}".rstrip("/")


@device_notify_router.get("/lan/android-update")
async def mobile_lan_android_update(
    request: Request,
    sku: str = Query("enterprise"),
    current_version_code: int = Query(0, ge=0),
    user=Depends(get_mobile_user),
):
    """已配对手机查询本机 LAN 发布的 APK（不经公网 MODstore）。"""
    if user is None:
        return JSONResponse(
            format_mobile_response(None, "未授权", success=False, code=401),
            status_code=401,
        )
    clean_sku = (sku or "enterprise").strip().lower() or "enterprise"
    if clean_sku not in {"enterprise", "personal"}:
        return JSONResponse(
            format_mobile_response(None, "sku 仅支持 enterprise/personal", success=False, code=400),
            status_code=400,
        )
    root = _lan_releases_root()
    if root is None:
        return JSONResponse(
            format_mobile_response(None, "本机未配置 LAN 发布目录", success=False, code=404),
            status_code=404,
        )
    manifest_path = root / clean_sku / "manifest.json"
    if not manifest_path.is_file():
        return JSONResponse(
            format_mobile_response(
                None,
                "尚未发布局域网 APK，请先运行 lan-mobile-apk-publish.sh",
                success=False,
                code=404,
            ),
            status_code=404,
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("lan android-update manifest 读取失败: %s", exc)
        return JSONResponse(
            format_mobile_response(None, "局域网更新清单损坏", success=False, code=500),
            status_code=500,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            format_mobile_response(None, "局域网更新清单格式错误", success=False, code=500),
            status_code=500,
        )
    version_code = int(payload.get("version_code") or 0)
    version_name = str(payload.get("version_name") or "10.0.0").strip() or "10.0.0"
    apk_rel = str(payload.get("apk_path") or "").strip().lstrip("/")
    if not apk_rel:
        apk_name = str(payload.get("apk_name") or "").strip()
        apk_rel = f"{clean_sku}/{apk_name}" if apk_name else ""
    apk_file = (root / apk_rel).resolve() if apk_rel else None
    if (
        version_code <= 0
        or not apk_rel
        or apk_file is None
        or not str(apk_file).startswith(str(root.resolve()))
        or not apk_file.is_file()
    ):
        return JSONResponse(
            format_mobile_response(None, "局域网 APK 文件缺失，请重新发布", success=False, code=404),
            status_code=404,
        )
    base = _lan_public_base_url(request)
    download_url = f"{base}/download/lan/{apk_rel}"
    available = current_version_code < version_code
    data = {
        "sku": clean_sku,
        "platform": "android",
        "latest_android_version": version_code,
        "latest_android_version_name": version_name,
        "min_android_version": 0,
        "force_update": False,
        "apk_download_url": download_url,
        "sha256": str(payload.get("sha256") or ""),
        "built_at": str(payload.get("built_at") or ""),
        "source": "lan",
        "available": available,
        "current_version_code": current_version_code,
    }
    return format_mobile_response(data=data)


def _is_loopback_request(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    # Starlette TestClient 使用 host=testclient
    if host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return True
    try:
        from app.security.lan_config import get_lan_config
        from app.security.lan_ip import get_client_ip

        cfg = get_lan_config()
        ip = get_client_ip(request.scope, cfg.trusted_proxies) or host
        return ip in {"127.0.0.1", "::1", "localhost", "testclient"}
    except Exception:  # noqa: BLE001
        return False


@device_notify_router.post("/lan/android-update/notify")
async def mobile_lan_android_update_notify(
    request: Request,
    body: LanAndroidUpdateNotifyBody,
):
    """本机 publish 脚本调用：写入 outbox，唤醒已登录手机检查/安装 LAN APK。

    仅允许 loopback，避免局域网任意主机滥发更新通知。
    """
    if not _is_loopback_request(request):
        return JSONResponse(
            format_mobile_response(None, "仅本机可触发更新通知", success=False, code=403),
            status_code=403,
        )
    clean_sku = (body.sku or "enterprise").strip().lower() or "enterprise"
    if clean_sku not in {"enterprise", "personal"}:
        return JSONResponse(
            format_mobile_response(None, "sku 仅支持 enterprise/personal", success=False, code=400),
            status_code=400,
        )
    user_ids = [int(x) for x in (body.user_ids or []) if int(x) > 0]
    if not user_ids:
        # 默认通知最近登录的 admin（user_id=1），可用 body.user_ids 覆盖
        user_ids = [1]

    version_code = int(body.version_code or 0)
    if version_code <= 0:
        root = _lan_releases_root()
        manifest_path = (root / clean_sku / "manifest.json") if root else None
        if manifest_path and manifest_path.is_file():
            try:
                version_code = int(
                    json.loads(manifest_path.read_text(encoding="utf-8")).get("version_code") or 0
                )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                version_code = 0

    from app.application.mobile_push_app_service import notify_mobile_user

    notified: list[dict[str, Any]] = []
    for uid in user_ids:
        result = notify_mobile_user(
            uid,
            title="局域网有新版本",
            body=f"企业版 APK 已发布（versionCode={version_code or '最新'}），正在准备安装…",
            data={
                "type": "lan_apk_ready",
                "channel": "xcagi_system",
                "route": "update/check",
                "sku": clean_sku,
                "version_code": str(version_code),
                "auto_install": "1" if body.auto_install else "0",
            },
        )
        notified.append({"user_id": uid, **result})

    return format_mobile_response(
        data={
            "sku": clean_sku,
            "version_code": version_code,
            "notified": notified,
            "route": "update/check",
        }
    )
