"""COVERAGE_RAMP Phase 4 round 15: aibiz_web_terminal_service pure helpers (27%→)."""

from __future__ import annotations

import io

import pytest
from fastapi.responses import JSONResponse, Response
from PIL import Image

from app.application import aibiz_web_terminal_service as svc


def _png(w: int, h: int) -> bytes:
    img = Image.new("RGB", (w, h), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _size(raw: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(raw)).size


# ---------------------------------------------------------------------------
# _unwrap / cache token / image url
# ---------------------------------------------------------------------------


def test_unwrap_jsonresponse() -> None:
    resp = JSONResponse({"x": 1})
    out = svc._unwrap(resp)
    assert out["_error_response"] is resp


def test_unwrap_dict_and_other() -> None:
    assert svc._unwrap({"a": 1}) == {"a": 1}
    assert svc._unwrap(42) == {}


def test_surface_cache_token_from_captured_at() -> None:
    tok = svc._surface_cache_token({"captured_at": "2024-01-02T03:04:05.678Z"})
    assert tok == "20240102T03040"  # only :-.Z stripped, T retained, truncated to 14


def test_surface_cache_token_fallback_today() -> None:
    tok = svc._surface_cache_token({})
    assert len(tok) == 8 and tok.isdigit()


def test_surface_image_url_variants() -> None:
    assert svc._surface_image_url("app", 0) == "/api/xcmax/aibiz/surface-image?terminal=app&index=0"
    full = svc._surface_image_url("web", 2, view="viewport", v="20240101")
    assert "view=viewport" in full and "v=20240101" in full


# ---------------------------------------------------------------------------
# png transforms
# ---------------------------------------------------------------------------


def test_crop_png_top_crops_tall() -> None:
    raw = _png(200, 2000)
    out = svc._crop_png_top(raw, height=720)
    assert _size(out) == (200, 720)


def test_crop_png_top_no_crop_when_short() -> None:
    raw = _png(200, 300)
    assert svc._crop_png_top(raw, height=720) == raw


def test_crop_png_top_empty() -> None:
    assert svc._crop_png_top(b"") == b""


def test_resize_png_thumb_shrinks_wide() -> None:
    raw = _png(800, 400)
    out = svc._resize_png_thumb(raw, max_width=96)
    w, h = _size(out)
    assert w == 96 and h == 48


def test_resize_png_thumb_keeps_small() -> None:
    raw = _png(40, 20)
    out = svc._resize_png_thumb(raw, max_width=96)
    assert _size(out) == (40, 20)


def test_resize_png_thumb_empty() -> None:
    assert svc._resize_png_thumb(b"") == b""


def test_transform_png_view_dispatch() -> None:
    raw = _png(800, 2000)
    assert _size(svc._transform_png_view(raw, "viewport")) == (800, 720)
    assert _size(svc._transform_png_view(raw, "thumb"))[0] == 96
    assert svc._transform_png_view(raw, "raw") == raw


def test_png_http_response_cacheable() -> None:
    resp = svc._png_http_response(_png(10, 10), view="thumb")
    assert isinstance(resp, Response)
    assert resp.media_type == "image/png"
    assert "immutable" in resp.headers["Cache-Control"]


def test_png_http_response_non_cacheable() -> None:
    resp = svc._png_http_response(_png(10, 10), view="other")
    assert "no-cache" in resp.headers["Cache-Control"]


# ---------------------------------------------------------------------------
# surface shaping
# ---------------------------------------------------------------------------


def test_strip_b64_attach_image_urls_strips_and_marks_hero() -> None:
    surface = {
        "captured_at": "2024-01-01T00:00:00Z",
        "pages": [
            {"id": "home_hub", "name": "首页", "preview": True, "screenshot_b64": "AAA"},
            {"id": "other", "name": "其它", "screenshot_saved": "/tmp/x.png"},
        ],
    }
    out = svc._strip_b64_attach_image_urls(surface, terminal="app")
    pages = out["pages"]
    assert "screenshot_b64" not in pages[0]
    assert "screenshot_saved" not in pages[1]
    assert all("image_url" in p for p in pages)
    assert out["preview_index"] == 0
    assert pages[0]["preview"] is True


def test_strip_b64_non_dict_passthrough() -> None:
    assert svc._strip_b64_attach_image_urls("nope", terminal="app") == "nope"
    assert svc._strip_b64_attach_image_urls({"pages": []}, terminal="app") == {"pages": []}


def test_compact_surface_pages_noop() -> None:
    s = {"pages": [1, 2]}
    assert svc._compact_surface_pages(s, compact=True) is s
    assert svc._compact_surface_pages(s, compact=False) is s


# ---------------------------------------------------------------------------
# _sanitize_pw_admin_pages
# ---------------------------------------------------------------------------


def test_sanitize_pw_admin_non_pw_passthrough() -> None:
    s = {"pages": [{"id": "a"}]}
    assert svc._sanitize_pw_admin_pages("P-S", s) is s


def test_sanitize_pw_admin_drops_bad_admin_page() -> None:
    s = {
        "pages": [
            {"id": "home", "url": "/market/home", "status": 200, "image_url": "x"},
            {"id": "adm", "url": "/market/admin/x", "status": 500, "error": True},
        ]
    }
    out = svc._sanitize_pw_admin_pages("P-W", s)
    assert out["page_count"] == 1
    assert len(out["pages"]) == 1


def test_sanitize_pw_admin_keeps_all_when_ok() -> None:
    s = {
        "pages": [
            {"id": "home", "url": "/market/home", "status": 200, "image_url": "x"},
            {
                "id": "adm",
                "url": "/market/admin/x",
                "status": 200,
                "screenshot_saved": "/tmp/x.png",
            },
        ]
    }
    out = svc._sanitize_pw_admin_pages("P-W", s)
    assert out is s  # unchanged identity when nothing dropped


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
