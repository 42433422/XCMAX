"""Image loading, transformation and metadata projection for AIBIZ surfaces."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi.responses import Response

from app.utils.operational_errors import RECOVERABLE_ERRORS

VIEWPORT_CROP_HEIGHT = 720
THUMB_MAX_WIDTH = 96


def surface_cache_token(surface: dict[str, Any]) -> str:
    raw = str(surface.get("captured_at") or surface.get("cached_at") or "").strip()
    if raw:
        return raw.replace(":", "").replace("-", "").replace(".", "").replace("Z", "")[:14]
    return date.today().isoformat().replace("-", "")


def surface_image_url(terminal: str, index: int, *, view: str = "", v: str = "") -> str:
    url = f"/api/xcmax/aibiz/surface-image?terminal={terminal}&index={index}"
    if view:
        url += f"&view={view}"
    if v:
        url += f"&v={v}"
    return url


def crop_png_top(raw: bytes, height: int = VIEWPORT_CROP_HEIGHT) -> bytes:
    if not raw:
        return raw
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(raw))
        width, image_height = image.size
        crop_height = min(max(1, height), image_height)
        if crop_height >= image_height:
            return raw
        cropped = image.crop((0, 0, width, crop_height))
        buffer = io.BytesIO()
        cropped.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except RECOVERABLE_ERRORS:
        from app.application import aibiz_web_terminal_service as facade

        facade.logger.debug("surface png viewport crop failed", exc_info=True)
        return raw


def resize_png_thumb(raw: bytes, *, max_width: int = THUMB_MAX_WIDTH) -> bytes:
    if not raw:
        return raw
    try:
        import io

        from PIL import Image

        image = Image.open(io.BytesIO(raw))
        width, height = image.size
        if width <= max_width:
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
        thumb_height = max(1, int(height * max_width / width))
        thumbnail = image.resize((max_width, thumb_height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        thumbnail.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()
    except RECOVERABLE_ERRORS:
        from app.application import aibiz_web_terminal_service as facade

        facade.logger.debug("surface png thumb resize failed", exc_info=True)
        return raw


def transform_png_view(raw: bytes, view: str) -> bytes:
    from app.application import aibiz_web_terminal_service as facade

    if view == "viewport":
        return facade._crop_png_top(raw)
    if view == "thumb":
        return facade._resize_png_thumb(raw)
    return raw


def png_http_response(raw: bytes, *, view: str = "") -> Response:
    from app.application import aibiz_web_terminal_service as facade

    body = facade._transform_png_view(raw, view)
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


async def load_surface_png_bytes(
    lane: str,
    index: int,
    *,
    prefer_remote: bool,
    authorization: str,
) -> bytes | None:
    from app.application import aibiz_web_terminal_service as facade

    def page_bytes(page: dict[str, Any] | None) -> bytes | None:
        if not page:
            return None
        if page.get("android_capture"):
            encoded = str(page.get("screenshot_b64") or "").strip()
            if encoded:
                import base64

                return base64.b64decode(encoded)
        saved = str(page.get("screenshot_saved") or "").strip()
        if saved:
            png_path = Path(saved)
            if png_path.is_file():
                return png_path.read_bytes()
        from app.application.surface_audit_service import resolve_lane_page_png_path

        resolved = resolve_lane_page_png_path(lane, index, page if isinstance(page, dict) else None)
        if resolved is not None:
            return bytes(resolved.read_bytes())
        encoded = str(page.get("screenshot_b64") or "").strip()
        if encoded:
            import base64

            return base64.b64decode(encoded)
        return None

    if not prefer_remote:
        page = await facade._local_surface_page(lane, index)
        raw = page_bytes(page if isinstance(page, dict) else None)
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
            response = await client.get(url, headers={"Authorization": f"Bearer {authorization}"})
        if response.status_code == 200:
            return bytes(response.content)
    page = await facade._local_surface_page(lane, index)
    raw = page_bytes(page if isinstance(page, dict) else None)
    return raw or None


def strip_b64_attach_image_urls(surface: dict[str, Any], *, terminal: str) -> dict[str, Any]:
    """Return page metadata with file-stream URLs instead of inline PNG data."""
    from app.application import aibiz_web_terminal_service as facade

    if not isinstance(surface, dict):
        return surface
    pages = surface.get("pages")
    if not isinstance(pages, list) or not pages:
        return surface
    hero_index = 0
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or not page.get("preview"):
            continue
        page_id = str(page.get("id") or "")
        if terminal == "software" and page_id.startswith("admin_"):
            continue
        hero_index = index
        break
    else:
        if terminal == "app":
            for wanted in ("home_hub", "approval", "erp_overview", "chat", "workbench"):
                match = next(
                    (
                        index
                        for index, page in enumerate(pages)
                        if isinstance(page, dict) and str(page.get("id") or "") == wanted
                    ),
                    None,
                )
                if match is not None:
                    hero_index = match
                    break
        else:
            for index, page in enumerate(pages):
                if not isinstance(page, dict):
                    continue
                page_id = str(page.get("id") or "")
                name = str(page.get("name") or "")
                if terminal == "software":
                    if page_id.startswith("admin_"):
                        continue
                    if page_id in ("chat", "home_hub") or name in ("智能对话", "首页"):
                        hero_index = index
                        break
                    continue
                if (
                    page_id.startswith(("mod_", "admin_"))
                    or page_id in ("home", "home_hub")
                    or "官网" in name
                    or "首页" in name
                    or name.lower() in {"home", "index"}
                ):
                    hero_index = index
                    break
    cache_token = facade._surface_cache_token(surface)
    projected_pages: list[Any] = []
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            projected_pages.append(page)
            continue
        row = {
            key: value
            for key, value in page.items()
            if key not in ("screenshot_b64", "screenshot_saved")
        }
        row["image_url"] = facade._surface_image_url(terminal, index, v=cache_token)
        if index == hero_index:
            row["preview"] = True
            row["preview_image_url"] = facade._surface_image_url(
                terminal, index, view="viewport", v=cache_token
            )
        projected_pages.append(row)
    result = dict(surface)
    result["pages"] = projected_pages
    result["preview_index"] = hero_index
    return result


def compact_surface_pages(surface: dict[str, Any], *, compact: bool) -> dict[str, Any]:
    """Retain the legacy compact argument; images are never inlined."""
    del compact
    return surface
