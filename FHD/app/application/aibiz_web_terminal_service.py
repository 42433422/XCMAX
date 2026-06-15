"""AI 业务数据 Tab · 三端终端聚合（网站 / 软件 / App）。

网站端对接时间轨 SW 节点「P-W 网站截图+分析」：
  MODstore ``daily_digest_surface_audit.py`` + ``/api/xcmax/admin/surface-audit/lane``。

鉴权：优先当前 FHD 会话绑定的 market JWT；否则 ``XCAGI_AIBIZ_MARKET_USER`` /
``XCAGI_AIBIZ_MARKET_PASSWORD`` 服务账号；再否则回退 ``config/surface_audit_demo_account.json``
演示号（``xcagi-enterprise-demo``，与 P-S 巡检同源，非管理员）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_LANE_BY_TERMINAL = {
    "web": ("P-W", "SW"),
    "software": ("P-S", "SS"),
    "app": ("P-App", "SA"),
}


async def _resolve_market_authorization(request: Request) -> str:
    try:
        from app.fastapi_routes.market_account import (
            _authorization_from_request,
            login_market_with_password,
            session_id_from_request,
        )
    except RECOVERABLE_ERRORS as exc:
        raise RuntimeError(f"market proxy unavailable: {exc}") from exc

    sid = str(session_id_from_request(request) or "").strip()
    if sid:
        auth = _authorization_from_request(request, {})
        if auth:
            return auth

    creds: list[tuple[str, str]] = []
    env_user = (os.environ.get("XCAGI_AIBIZ_MARKET_USER") or "").strip()
    env_pass = os.environ.get("XCAGI_AIBIZ_MARKET_PASSWORD") or ""
    if env_user and env_pass:
        creds.append((env_user, env_pass))

    digest_user = (os.environ.get("MODSTORE_DIGEST_ADMIN_USER") or "").strip()
    digest_pass = os.environ.get("MODSTORE_DIGEST_ADMIN_PASSWORD") or ""
    if digest_user and digest_pass and (digest_user, digest_pass) not in creds:
        creds.append((digest_user, digest_pass))

    try:
        from app.application.surface_audit_demo_account import demo_password, demo_username

        demo_user = demo_username()
        demo_pass = demo_password()
        if demo_user and demo_pass and (demo_user, demo_pass) not in creds:
            creds.append((demo_user, demo_pass))
    except RECOVERABLE_ERRORS:
        logger.debug("surface audit demo creds unavailable", exc_info=True)

    for user, password in creds:
        login = await login_market_with_password(user, password)
        if login.get("success") and login.get("token"):
            return str(login["token"]).strip()

    return ""


def _unwrap(payload: Any) -> dict[str, Any]:
    if isinstance(payload, JSONResponse):
        return {"_error_response": payload}
    if isinstance(payload, dict):
        return payload
    return {}


def _surface_cache_token(surface: dict[str, Any]) -> str:
    raw = str(surface.get("captured_at") or surface.get("cached_at") or "").strip()
    if raw:
        return raw.replace(":", "").replace("-", "").replace(".", "").replace("Z", "")[:14]
    return date.today().isoformat().replace("-", "")


def _surface_image_url(terminal: str, index: int, *, view: str = "", v: str = "") -> str:
    url = f"/api/xcmax/aibiz/surface-image?terminal={terminal}&index={index}"
    if view:
        url += f"&view={view}"
    if v:
        url += f"&v={v}"
    return url


_VIEWPORT_CROP_HEIGHT = 720
_THUMB_MAX_WIDTH = 96


def _crop_png_top(raw: bytes, height: int = _VIEWPORT_CROP_HEIGHT) -> bytes:
    if not raw:
        return raw
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        crop_h = min(max(1, height), h)
        if crop_h >= h:
            return raw
        cropped = img.crop((0, 0, w, crop_h))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except RECOVERABLE_ERRORS:
        logger.debug("surface png viewport crop failed", exc_info=True)
        return raw


def _resize_png_thumb(raw: bytes, *, max_width: int = _THUMB_MAX_WIDTH) -> bytes:
    if not raw:
        return raw
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        w, h = img.size
        if w <= max_width:
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        nh = max(1, int(h * max_width / w))
        thumb = img.resize((max_width, nh), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        thumb.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except RECOVERABLE_ERRORS:
        logger.debug("surface png thumb resize failed", exc_info=True)
        return raw


def _transform_png_view(raw: bytes, view: str) -> bytes:
    if view == "viewport":
        return _crop_png_top(raw)
    if view == "thumb":
        return _resize_png_thumb(raw)
    return raw


def _png_http_response(raw: bytes, *, view: str = "") -> Response:
    body = _transform_png_view(raw, view)
    cacheable = view in ("thumb", "viewport", "")
    return Response(
        content=body,
        media_type="image/png",
        headers={
            "Cache-Control": (
                "public, max-age=86400, immutable" if cacheable else "no-cache, must-revalidate"
            )
        },
    )


async def _load_surface_png_bytes(
    lane: str,
    index: int,
    *,
    prefer_remote: bool,
    authorization: str,
) -> bytes | None:
    def _page_bytes(page: dict[str, Any] | None) -> bytes | None:
        if not page:
            return None
        # adb 真机截图优先于同页 Playwright Web 回退文件（merge 后两者可能并存）
        if page.get("android_capture"):
            b64 = str(page.get("screenshot_b64") or "").strip()
            if b64:
                import base64

                return base64.b64decode(b64)
        saved = str(page.get("screenshot_saved") or "").strip()
        if saved:
            png_path = Path(saved)
            if png_path.is_file():
                return png_path.read_bytes()
        from app.application.surface_audit_service import resolve_lane_page_png_path

        resolved = resolve_lane_page_png_path(lane, index, page if isinstance(page, dict) else None)
        if resolved is not None:
            return resolved.read_bytes()
        b64 = str(page.get("screenshot_b64") or "").strip()
        if b64:
            import base64

            return base64.b64decode(b64)
        return None

    if not prefer_remote:
        page = await _local_surface_page(lane, index)
        raw = _page_bytes(page if isinstance(page, dict) else None)
        if raw:
            return raw

    if authorization and prefer_remote:
        import httpx

        from app.fastapi_routes.market_account import _market_base_url

        url = (
            f"{_market_base_url().rstrip('/')}/api/xcmax/admin/surface-audit/image"
            f"?lane={lane}&index={index}"
        )
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {authorization}"})
        if r.status_code == 200:
            return r.content

    page = await _local_surface_page(lane, index)
    raw = _page_bytes(page if isinstance(page, dict) else None)
    if raw:
        return raw
    return None


def _strip_b64_attach_image_urls(surface: dict[str, Any], *, terminal: str) -> dict[str, Any]:
    """API 只返回页面元数据 + image_url；PNG 由 /surface-image 直出文件流。"""
    if not isinstance(surface, dict):
        return surface
    pages = surface.get("pages")
    if not isinstance(pages, list) or not pages:
        return surface

    hero_i = 0
    for i, page in enumerate(pages):
        if not isinstance(page, dict) or not page.get("preview"):
            continue
        pid = str(page.get("id") or "")
        if terminal == "software" and pid.startswith("admin_"):
            continue
        hero_i = i
        break
    else:
        if terminal == "app":
            preferred_ids = ("home_hub", "approval", "erp_overview", "chat", "workbench")
            for want in preferred_ids:
                for i, page in enumerate(pages):
                    if isinstance(page, dict) and str(page.get("id") or "") == want:
                        hero_i = i
                        break
                else:
                    continue
                break
        else:
            for i, page in enumerate(pages):
                if not isinstance(page, dict):
                    continue
                pid = str(page.get("id") or "")
                name = str(page.get("name") or "")
                str(page.get("path") or page.get("url") or "")
                if terminal == "software":
                    if pid.startswith("admin_"):
                        continue
                    if pid in ("chat", "home_hub") or name in ("智能对话", "首页"):
                        hero_i = i
                        break
                    continue
                if pid.startswith("mod_") or pid.startswith("admin_"):
                    hero_i = i
                    break
                if (
                    pid in ("home", "home_hub")
                    or "官网" in name
                    or "首页" in name
                    or name.lower() in {"home", "index"}
                ):
                    hero_i = i
                    break

    cache_token = _surface_cache_token(surface)

    out_pages: list[Any] = []
    for i, page in enumerate(pages):
        if not isinstance(page, dict):
            out_pages.append(page)
            continue
        row = {k: v for k, v in page.items() if k not in ("screenshot_b64", "screenshot_saved")}
        row["image_url"] = _surface_image_url(terminal, i, v=cache_token)
        if i == hero_i:
            row["preview"] = True
            row["preview_image_url"] = _surface_image_url(
                terminal, i, view="viewport", v=cache_token
            )
        out_pages.append(row)

    out = dict(surface)
    out["pages"] = out_pages
    out["preview_index"] = hero_i
    return out


def _compact_surface_pages(surface: dict[str, Any], *, compact: bool) -> dict[str, Any]:
    """兼容旧 compact 参数；实际不再 inline base64。"""
    _ = compact
    return surface


async def _local_surface_page(lane: str, index: int) -> dict[str, Any] | None:
    try:
        pages = await _local_lane_pages(lane)
        if index < 0 or index >= len(pages):
            return None
        page = pages[index]
        return page if isinstance(page, dict) else None
    except RECOVERABLE_ERRORS:
        return None


_local_lane_pages_cache: dict[str, tuple[str, list[Any]]] = {}


async def _local_lane_pages(lane: str) -> list[Any]:
    local = await asyncio.to_thread(_load_local_lane_surface, lane)
    return local.get("pages") if isinstance(local.get("pages"), list) else []


def _load_local_lane_surface(lane: str) -> dict[str, Any]:
    from app.application.surface_audit_service import run_surface_audit_lane

    local = run_surface_audit_lane(lane, refresh=False)
    token = str(local.get("cached_at") or local.get("captured_at") or "")
    cached = _local_lane_pages_cache.get(lane)
    if cached and cached[0] == token:
        return {"pages": cached[1]}
    pages = local.get("pages") if isinstance(local.get("pages"), list) else []
    _local_lane_pages_cache[lane] = (token, pages)
    return local


async def serve_surface_image(
    request: Request,
    *,
    terminal: str = "web",
    index: int = 0,
    view: str = "",
) -> Response:
    terminal = (terminal or "web").strip().lower()
    lane, _workflow_node = _LANE_BY_TERMINAL.get(terminal, ("P-W", "SW"))
    index = max(0, int(index))
    view = (view or "").strip().lower()
    prefer_remote = lane == "P-W"

    try:
        authorization = await _resolve_market_authorization(request)
    except RuntimeError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    raw = await _load_surface_png_bytes(
        lane, index, prefer_remote=prefer_remote, authorization=authorization
    )
    if raw:
        return _png_http_response(raw, view=view)

    if not authorization:
        return JSONResponse({"success": False, "message": "需要 market 会话"}, status_code=401)
    return JSONResponse({"success": False, "message": "截图不存在"}, status_code=404)


async def build_terminal_payload(
    request: Request,
    *,
    terminal: str = "web",
    refresh: bool = False,
    compact: bool = True,
) -> dict[str, Any] | JSONResponse:
    terminal = (terminal or "web").strip().lower()
    lane, workflow_node = _LANE_BY_TERMINAL.get(terminal, ("P-W", "SW"))

    try:
        from app.fastapi_routes.market_account import (
            _market_base_url,
        )
    except RECOVERABLE_ERRORS as exc:
        return JSONResponse(
            {"success": False, "message": f"market proxy unavailable: {exc}"},
            status_code=500,
        )

    try:
        authorization = await _resolve_market_authorization(request)
    except RuntimeError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    surface, surface_note = await _resolve_surface_audit(
        lane, refresh=refresh, authorization=authorization, compact=compact
    )

    if not authorization:
        if surface.get("pages"):
            data: dict[str, Any] = {
                "terminal": terminal,
                "lane": lane,
                "workflow_node": workflow_node,
                "workflow_label": {
                    "SW": "P-W 网站截图+分析",
                    "SS": "P-S 软件截图+分析",
                    "SA": "P-App 移动截图+分析",
                }.get(workflow_node, workflow_node),
                "market_base_url": _market_base_url(),
                "surface_audit": _strip_b64_attach_image_urls(surface, terminal=terminal),
                "surface_audit_note": surface_note,
                "android_audit": surface.get("android_audit"),
            }
            return {"success": True, "data": data}
        return JSONResponse(
            {
                "success": False,
                "message": "需要 market 会话，或配置 XCAGI_AIBIZ_MARKET_USER / XCAGI_AIBIZ_MARKET_PASSWORD（未配置时自动尝试演示账号 xcagi-enterprise-demo）；P-W 亦需今日 surface-audit 缓存或远端 MODstore",
                "data": {
                    "terminal": terminal,
                    "lane": lane,
                    "workflow_node": workflow_node,
                    "market_base_url": _market_base_url(),
                },
            },
            status_code=401,
        )

    data: dict[str, Any] = {
        "terminal": terminal,
        "lane": lane,
        "workflow_node": workflow_node,
        "workflow_label": {
            "SW": "P-W 网站截图+分析",
            "SS": "P-S 软件截图+分析",
            "SA": "P-App 移动截图+分析",
        }.get(workflow_node, workflow_node),
        "market_base_url": _market_base_url(),
        "surface_audit": _strip_b64_attach_image_urls(surface, terminal=terminal),
        "surface_audit_note": surface_note,
        "android_audit": surface.get("android_audit"),
    }
    return {"success": True, "data": data}


async def fetch_surface_page_payload(
    request: Request,
    *,
    terminal: str = "web",
    index: int = 0,
) -> dict[str, Any] | JSONResponse:
    terminal = (terminal or "web").strip().lower()
    lane, _workflow_node = _LANE_BY_TERMINAL.get(terminal, ("P-W", "SW"))
    index = max(0, int(index))

    try:
        authorization = await _resolve_market_authorization(request)
    except RuntimeError as exc:
        return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    if lane in ("P-App", "P-S") or not authorization:
        try:
            from app.application.surface_audit_service import run_surface_audit_lane

            local = await asyncio.to_thread(run_surface_audit_lane, lane, refresh=False)
            pages = local.get("pages") if isinstance(local.get("pages"), list) else []
            if index >= len(pages):
                return JSONResponse(
                    {"success": False, "message": "index out of range"}, status_code=404
                )
            page = pages[index] if isinstance(pages[index], dict) else {}
            return {
                "success": True,
                "data": {
                    "lane": lane,
                    "index": index,
                    "total": len(pages),
                    **{
                        k: page.get(k)
                        for k in (
                            "name",
                            "url",
                            "status",
                            "title",
                            "viewport",
                            "screenshot_b64",
                            "screenshot_saved",
                        )
                    },
                },
            }
        except RECOVERABLE_ERRORS as exc:
            return JSONResponse({"success": False, "message": str(exc)}, status_code=500)

    from app.fastapi_routes.market_account import _proxy_json

    surface_raw = _unwrap(
        await _proxy_json(
            "GET",
            f"/api/xcmax/admin/surface-audit/page?lane={lane}&index={index}",
            authorization=authorization,
            return_error_payload=True,
        )
    )
    if surface_raw.get("_error_response"):
        return cast("dict[str, Any] | JSONResponse", surface_raw["_error_response"])
    if surface_raw.get("success") and isinstance(surface_raw.get("data"), dict):
        return {"success": True, "data": surface_raw["data"]}
    return JSONResponse(
        {
            "success": False,
            "message": str(surface_raw.get("message") or "surface page unavailable"),
        },
        status_code=502,
    )


def _sanitize_pw_admin_pages(lane: str, surface: dict[str, Any]) -> dict[str, Any]:
    """P-W 管理端须 digest 解锁成功才展示；丢弃解锁弹层占位截图。"""

    def _is_admin_page(p: dict[str, Any]) -> bool:
        if p.get("admin"):
            return True
        url = str(p.get("url") or p.get("path") or "")
        name = str(p.get("name") or "")
        return "/market/admin/" in url or name.startswith("管理端")

    def _admin_ok(p: dict[str, Any]) -> bool:
        if p.get("digest_unlock_ok"):
            return True
        if not _is_admin_page(p):
            return True
        status = int(p.get("status") or 0)
        has_image = bool(p.get("screenshot_saved") or p.get("image_url") or p.get("screenshot_b64"))
        return not p.get("error") and status < 400 and has_image

    if lane != "P-W" or not isinstance(surface, dict):
        return surface
    pages = surface.get("pages")
    if not isinstance(pages, list):
        return surface
    kept = [p for p in pages if isinstance(p, dict) and _admin_ok(p)]
    if len(kept) == len(pages):
        return surface
    out = dict(surface)
    out["pages"] = kept
    out["page_count"] = len(kept)
    return out


async def _resolve_surface_audit(
    lane: str,
    *,
    refresh: bool,
    authorization: str,
    compact: bool = True,
) -> tuple[dict[str, Any], str]:
    """网站 P-W 走 xiu-ci.com 全量网页；P-S 本地企业版；P-App 本地 adb。"""

    surface: dict[str, Any] = {}
    surface_note = ""

    prefer_remote = bool(authorization) and lane == "P-W"

    if prefer_remote:
        surface, surface_note = await _fetch_remote_surface_audit(
            lane, refresh=refresh, authorization=authorization, compact=compact
        )
        if surface.get("pages"):
            surface = _sanitize_pw_admin_pages(lane, surface)
            n = len(surface["pages"])
            hint = "预览" if compact else "全量"
            return surface, f"MODstore surface-audit · xiu-ci.com 全部网页 · {n} 页 · {hint}"

    local_enabled = os.environ.get("XCAGI_SURFACE_AUDIT_LOCAL", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    if local_enabled and (lane in ("P-App", "P-S") or not surface.get("pages")):
        try:
            from app.application.surface_audit_service import run_surface_audit_lane

            local = await asyncio.to_thread(run_surface_audit_lane, lane, refresh=refresh)
            if local.get("success") and local.get("pages"):
                surface = local
                adb_n = sum(
                    1
                    for p in (local.get("pages") or [])
                    if isinstance(p, dict) and p.get("android_capture")
                )
                if adb_n:
                    sku_label = " · 企业版 enterprise SKU" if lane == "P-App" else ""
                    surface_note = (
                        f"Android App adb 真机截图 {adb_n} 页（SA · 模拟器/真机{sku_label}）"
                    )
                    web_n = sum(
                        1
                        for p in (local.get("pages") or [])
                        if isinstance(p, dict) and not p.get("android_capture")
                    )
                    if web_n:
                        surface_note += f" · Playwright Web 回退 {web_n} 页"
                elif lane == "P-W":
                    surface_note = "本地 Playwright · 营销静态站 xiu-ci.com"
                elif lane == "P-S":
                    surface_note = "本地 Playwright · FHD 企业版客户端 · 企业账号 · 127.0.0.1:5001"
                else:
                    surface_note = "本地 Playwright 巡检（无 adb 设备时无真 App 截图）"
                android_meta = local.get("android_audit")
                if (
                    isinstance(android_meta, dict)
                    and android_meta.get("merged_count")
                    and not adb_n
                ):
                    surface_note += f" · adb {android_meta['merged_count']} 页"
                if local.get("stale_cache"):
                    stale_date = str(local.get("stale_cache_date") or "").strip()
                    surface_note += (
                        f" · {stale_date} 缓存（今日尚未巡检）" if stale_date else " · 历史缓存"
                    )
                elif local.get("from_cache"):
                    surface_note += " · 今日缓存"
                return _sanitize_pw_admin_pages(lane, surface), surface_note
            if local.get("message") and not surface_note:
                surface_note = str(local["message"])
        except RECOVERABLE_ERRORS as exc:
            logger.warning("local surface audit failed lane=%s: %s", lane, exc)
            if not surface_note:
                surface_note = f"本地巡检异常: {exc}"

    if not surface.get("pages") and authorization and not prefer_remote:
        surface, remote_note = await _fetch_remote_surface_audit(
            lane, refresh=refresh, authorization=authorization, compact=compact
        )
        if remote_note and not surface_note:
            surface_note = remote_note

    if not authorization and not surface.get("pages") and not surface_note:
        surface_note = "需要 market 会话或配置 XCAGI_AIBIZ_MARKET_* 以拉取远端 surface-audit"

    return _sanitize_pw_admin_pages(lane, surface), surface_note


async def _fetch_remote_surface_audit(
    lane: str,
    *,
    refresh: bool,
    authorization: str,
    compact: bool = True,
) -> tuple[dict[str, Any], str]:
    from app.fastapi_routes.market_account import _proxy_json

    surface: dict[str, Any] = {}
    surface_note = ""

    surface_raw = _unwrap(
        await _proxy_json(
            "GET",
            f"/api/xcmax/admin/surface-audit/lane?lane={lane}&refresh={'1' if refresh else '0'}"
            f"&compact={'1' if compact else '0'}",
            authorization=authorization,
            return_error_payload=True,
        )
    )
    if surface_raw.get("_error_response"):
        err = surface_raw["_error_response"]
        if isinstance(err, JSONResponse) and err.status_code == 404:
            surface_note = "市场未部署 surface-audit 接口（可仅用本地 FHD 巡检）"
        else:
            surface_note = "surface-audit 暂不可用"
    elif surface_raw.get("missing_route"):
        surface_note = str(
            surface_raw.get("hint")
            or f"市场未挂载 {surface_raw.get('missing_route')} · 需在官网 MODstore 部署 surface-audit"
        )
    elif surface_raw.get("success") and isinstance(surface_raw.get("data"), dict):
        surface = surface_raw["data"]
        surface_note = "MODstore surface-audit"
    elif surface_raw.get("success") and surface_raw.get("data") is None:
        surface_note = "surface-audit 接口已响应但无数据（今日尚未巡检）"
    elif not surface:
        surface_note = str(surface_raw.get("message") or "surface-audit 无数据")

    return surface, surface_note
