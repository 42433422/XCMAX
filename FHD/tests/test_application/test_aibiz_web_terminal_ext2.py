"""Extended tests for app.application.aibiz_web_terminal_service — image transforms, surface helpers."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.aibiz_web_terminal_service import (
    _LANE_BY_TERMINAL,
    _compact_surface_pages,
    _crop_png_top,
    _png_http_response,
    _resize_png_thumb,
    _sanitize_pw_admin_pages,
    _strip_b64_attach_image_urls,
    _surface_cache_token,
    _surface_image_url,
    _transform_png_view,
    _unwrap,
)

# ---------------------------------------------------------------------------
# _surface_cache_token
# ---------------------------------------------------------------------------


class TestSurfaceCacheToken:
    def test_with_captured_at(self):
        surface = {"captured_at": "2026-06-15T10:30:00Z"}
        token = _surface_cache_token(surface)
        assert "20260615" in token

    def test_with_cached_at(self):
        surface = {"cached_at": "2026-06-14T08:00:00.000Z"}
        token = _surface_cache_token(surface)
        assert len(token) > 0

    def test_no_timestamp_uses_today(self):
        surface = {}
        token = _surface_cache_token(surface)
        assert token == date.today().isoformat().replace("-", "")

    def test_strips_special_chars(self):
        surface = {"captured_at": "2026:06:15-10.30Z"}
        token = _surface_cache_token(surface)
        assert ":" not in token
        assert "-" not in token


# ---------------------------------------------------------------------------
# _surface_image_url
# ---------------------------------------------------------------------------


class TestSurfaceImageUrl:
    def test_basic(self):
        url = _surface_image_url("web", 0)
        assert url == "/api/xcmax/aibiz/surface-image?terminal=web&index=0"

    def test_with_view(self):
        url = _surface_image_url("web", 1, view="viewport")
        assert "view=viewport" in url

    def test_with_version(self):
        url = _surface_image_url("app", 2, v="20260615")
        assert "v=20260615" in url


# ---------------------------------------------------------------------------
# _crop_png_top
# ---------------------------------------------------------------------------


class TestCropPngTop:
    def test_empty_bytes(self):
        assert _crop_png_top(b"") == b""

    def test_non_png_returns_raw(self):
        raw = b"not a png"
        with patch.dict("sys.modules", {"PIL": MagicMock(), "PIL.Image": MagicMock()}):
            # PIL import fails → returns raw
            result = _crop_png_top(raw)
            assert result == raw


# ---------------------------------------------------------------------------
# _resize_png_thumb
# ---------------------------------------------------------------------------


class TestResizePngThumb:
    def test_empty_bytes(self):
        assert _resize_png_thumb(b"") == b""

    def test_non_image_returns_raw(self):
        raw = b"not an image"
        result = _resize_png_thumb(raw)
        assert result == raw


# ---------------------------------------------------------------------------
# _transform_png_view
# ---------------------------------------------------------------------------


class TestTransformPngView:
    def test_viewport(self):
        with patch(
            "app.application.aibiz_web_terminal_service._crop_png_top",
            return_value=b"cropped",
        ):
            assert _transform_png_view(b"raw", "viewport") == b"cropped"

    def test_thumb(self):
        with patch(
            "app.application.aibiz_web_terminal_service._resize_png_thumb",
            return_value=b"thumb",
        ):
            assert _transform_png_view(b"raw", "thumb") == b"thumb"

    def test_other_view(self):
        assert _transform_png_view(b"raw", "full") == b"raw"

    def test_empty_view(self):
        assert _transform_png_view(b"raw", "") == b"raw"


# ---------------------------------------------------------------------------
# _png_http_response
# ---------------------------------------------------------------------------


class TestPngHttpResponse:
    def test_cacheable_view(self):
        resp = _png_http_response(b"png_data", view="thumb")
        assert resp.media_type == "image/png"
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")

    def test_non_cacheable_view(self):
        resp = _png_http_response(b"png_data", view="full")
        assert "no-cache" in resp.headers.get("Cache-Control", "")

    def test_empty_view_cacheable(self):
        resp = _png_http_response(b"png_data", view="")
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")


# ---------------------------------------------------------------------------
# _compact_surface_pages
# ---------------------------------------------------------------------------


class TestCompactSurfacePages:
    def test_passthrough(self):
        surface = {"pages": [{"id": 1}]}
        result = _compact_surface_pages(surface, compact=True)
        assert result == surface

    def test_compact_false(self):
        surface = {"pages": []}
        result = _compact_surface_pages(surface, compact=False)
        assert result == surface


# ---------------------------------------------------------------------------
# _sanitize_pw_admin_pages
# ---------------------------------------------------------------------------


class TestSanitizePwAdminPages:
    def test_non_pw_lane_passthrough(self):
        surface = {"pages": [{"admin": True, "error": "locked"}]}
        result = _sanitize_pw_admin_pages("P-S", surface)
        assert result == surface

    def test_non_dict_surface_passthrough(self):
        result = _sanitize_pw_admin_pages("P-W", "not a dict")
        assert result == "not a dict"

    def test_no_pages_key(self):
        surface = {"other": "data"}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert result == surface

    def test_removes_bad_admin_pages(self):
        pages = [
            {"name": "Home", "url": "/home", "status": 200, "screenshot_saved": "/tmp/1.png"},
            {
                "name": "管理端Dashboard",
                "url": "/market/admin/",
                "error": "digest required",
                "status": 401,
            },
        ]
        surface = {"pages": pages}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1
        assert result["pages"][0]["name"] == "Home"

    def test_keeps_unlocked_admin_pages(self):
        pages = [
            {
                "name": "管理端OK",
                "url": "/market/admin/",
                "digest_unlock_ok": True,
                "status": 200,
                "screenshot_saved": "/tmp/ok.png",
            },
        ]
        surface = {"pages": pages}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1

    def test_admin_page_with_image_no_error(self):
        pages = [
            {
                "name": "管理端",
                "url": "/market/admin/",
                "status": 200,
                "screenshot_saved": "/tmp/a.png",
            },
        ]
        surface = {"pages": pages}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1

    def test_non_dict_pages_filtered(self):
        pages = [{"name": "OK"}, "not a dict", {"name": "Also OK"}]
        surface = {"pages": pages}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 2

    def test_all_kept_no_change(self):
        pages = [
            {"name": "Home", "url": "/home", "status": 200, "screenshot_saved": "/tmp/1.png"},
        ]
        surface = {"pages": pages}
        result = _sanitize_pw_admin_pages("P-W", surface)
        # Same length → original surface returned
        assert result is surface


# ---------------------------------------------------------------------------
# _strip_b64_attach_image_urls
# ---------------------------------------------------------------------------


class TestStripB64AttachImageUrls:
    def test_non_dict_passthrough(self):
        assert _strip_b64_attach_image_urls("string", terminal="web") == "string"

    def test_no_pages_key(self):
        surface = {"other": "data"}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result == surface

    def test_empty_pages(self):
        surface = {"pages": []}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result == surface

    def test_strips_b64_and_adds_image_url(self):
        pages = [
            {
                "id": "home",
                "name": "首页",
                "preview": True,
                "screenshot_b64": "base64data",
                "screenshot_saved": "/tmp/screenshot.png",
            },
        ]
        surface = {"pages": pages, "captured_at": "2026-06-15T10:00:00Z"}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert "screenshot_b64" not in result["pages"][0]
        assert "screenshot_saved" not in result["pages"][0]
        assert "image_url" in result["pages"][0]
        assert result["pages"][0]["preview"] is True
        assert "preview_image_url" in result["pages"][0]

    def test_software_skips_admin_hero(self):
        pages = [
            {"id": "admin_dashboard", "name": "管理端", "preview": True},
            {"id": "chat", "name": "智能对话", "preview": False},
        ]
        surface = {"pages": pages, "captured_at": "2026-06-15T10:00:00Z"}
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        # hero should be the chat page (index 1)
        assert result["preview_index"] == 1

    def test_app_preferred_ids(self):
        pages = [
            {"id": "settings", "name": "设置"},
            {"id": "home_hub", "name": "首页"},
        ]
        surface = {"pages": pages, "captured_at": "2026-06-15T10:00:00Z"}
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        # home_hub should be hero
        assert result["preview_index"] == 1

    def test_web_falls_back_to_mod_or_home(self):
        pages = [
            {"id": "other", "name": "其他"},
            {"id": "mod_plugin", "name": "MOD插件"},
        ]
        surface = {"pages": pages, "captured_at": "2026-06-15T10:00:00Z"}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        # mod_ page should be hero
        assert result["preview_index"] == 1

    def test_non_dict_page_kept(self):
        pages = ["not a dict"]
        surface = {"pages": pages, "captured_at": "2026-06-15T10:00:00Z"}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["pages"] == ["not a dict"]

    def test_software_finds_chat_or_home_hub(self):
        pages = [
            {"id": "other", "name": "其他"},
            {"id": "home_hub", "name": "首页"},
        ]
        surface = {"pages": pages, "captured_at": "2026-06-15T10:00:00Z"}
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        assert result["preview_index"] == 1


# ---------------------------------------------------------------------------
# _LANE_BY_TERMINAL completeness
# ---------------------------------------------------------------------------


class TestLaneByTerminalComplete:
    def test_all_terminals(self):
        assert "web" in _LANE_BY_TERMINAL
        assert "software" in _LANE_BY_TERMINAL
        assert "app" in _LANE_BY_TERMINAL

    def test_unknown_terminal_defaults(self):
        lane, node = _LANE_BY_TERMINAL.get("unknown", ("P-W", "SW"))
        assert lane == "P-W"
