"""Tests for app.application.aibiz_web_terminal_service — coverage ramp."""

import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.aibiz_web_terminal_service import (
    _LANE_BY_TERMINAL,
    _compact_surface_pages,
    _crop_png_top,
    _resize_png_thumb,
    _surface_cache_token,
    _surface_image_url,
    _transform_png_view,
    _unwrap,
    _strip_b64_attach_image_urls,
    _sanitize_pw_admin_pages,
)


# ========================= _LANE_BY_TERMINAL =============================


class TestLaneByTerminal:
    def test_web(self):
        assert _LANE_BY_TERMINAL["web"] == ("P-W", "SW")

    def test_software(self):
        assert _LANE_BY_TERMINAL["software"] == ("P-S", "SS")

    def test_app(self):
        assert _LANE_BY_TERMINAL["app"] == ("P-App", "SA")


# ========================= _unwrap =======================================


class TestUnwrap:
    def test_dict_passthrough(self):
        from app.application.aibiz_web_terminal_service import _unwrap

        assert _unwrap({"key": "val"}) == {"key": "val"}

    def test_json_response(self):
        from fastapi.responses import JSONResponse
        from app.application.aibiz_web_terminal_service import _unwrap

        resp = JSONResponse({"a": 1})
        result = _unwrap(resp)
        assert "_error_response" in result

    def test_other_type(self):
        from app.application.aibiz_web_terminal_service import _unwrap

        assert _unwrap("string") == {}

    def test_none(self):
        from app.application.aibiz_web_terminal_service import _unwrap

        assert _unwrap(None) == {}


# ========================= _surface_cache_token ==========================


class TestSurfaceCacheToken:
    def test_with_captured_at(self):
        result = _surface_cache_token({"captured_at": "2026-06-14T10:30:00Z"})
        assert "20260614" in result

    def test_with_cached_at(self):
        result = _surface_cache_token({"cached_at": "2026-01-01T00:00:00"})
        assert "20260101" in result

    def test_fallback_today(self):
        result = _surface_cache_token({})
        assert result == date.today().isoformat().replace("-", "")


# ========================= _surface_image_url ============================


class TestSurfaceImageUrl:
    def test_basic(self):
        url = _surface_image_url("web", 0)
        assert "terminal=web" in url
        assert "index=0" in url

    def test_with_view(self):
        url = _surface_image_url("web", 1, view="viewport")
        assert "view=viewport" in url

    def test_with_version(self):
        url = _surface_image_url("app", 2, v="20260614")
        assert "v=20260614" in url


# ========================= _transform_png_view ===========================


class TestTransformPngView:
    def test_viewport(self):
        result = _transform_png_view(b"fake", "viewport")
        assert isinstance(result, bytes)

    def test_thumb(self):
        result = _transform_png_view(b"fake", "thumb")
        assert isinstance(result, bytes)

    def test_empty_view(self):
        result = _transform_png_view(b"data", "")
        assert result == b"data"


# ========================= _crop_png_top =================================


class TestCropPngTop:
    def test_empty_bytes(self):
        assert _crop_png_top(b"") == b""

    def test_invalid_png(self):
        result = _crop_png_top(b"not a png")
        assert result == b"not a png"


# ========================= _resize_png_thumb =============================


class TestResizePngThumb:
    def test_empty_bytes(self):
        assert _resize_png_thumb(b"") == b""

    def test_invalid_png(self):
        result = _resize_png_thumb(b"not a png")
        assert result == b"not a png"


# ========================= _compact_surface_pages ========================


class TestCompactSurfacePages:
    def test_passthrough(self):
        surface = {"pages": [{"id": "home"}]}
        result = _compact_surface_pages(surface, compact=True)
        assert result == surface

    def test_compact_false(self):
        surface = {"pages": []}
        result = _compact_surface_pages(surface, compact=False)
        assert result == surface


# ========================= _strip_b64_attach_image_urls ==================


class TestStripB64AttachImageUrls:
    def test_basic(self):
        surface = {
            "pages": [
                {
                    "id": "home",
                    "name": "首页",
                    "screenshot_b64": "abc",
                    "screenshot_saved": "/tmp/a.png",
                },
                {"id": "about", "name": "关于"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert "screenshot_b64" not in result["pages"][0]
        assert "screenshot_saved" not in result["pages"][0]
        assert "image_url" in result["pages"][0]

    def test_non_dict_surface(self):
        result = _strip_b64_attach_image_urls("not a dict", terminal="web")
        assert result == "not a dict"

    def test_empty_pages(self):
        result = _strip_b64_attach_image_urls({"pages": []}, terminal="web")
        assert result["pages"] == []

    def test_no_pages_key(self):
        result = _strip_b64_attach_image_urls({"other": "data"}, terminal="web")
        assert result == {"other": "data"}

    def test_software_skips_admin_hero(self):
        surface = {
            "pages": [
                {"id": "admin_dashboard", "name": "管理端", "preview": True},
                {"id": "chat", "name": "智能对话"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        # chat should be hero for software
        hero_page = result["pages"][1]
        assert hero_page.get("preview") is True

    def test_app_preferred_ids(self):
        surface = {
            "pages": [
                {"id": "other", "name": "其他"},
                {"id": "approval", "name": "审批"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        # approval should be hero for app
        hero_page = result["pages"][1]
        assert hero_page.get("preview") is True


# ========================= _sanitize_pw_admin_pages =====================


class TestSanitizePwAdminPages:
    def test_non_pw_lane_passthrough(self):
        surface = {"pages": [{"admin": True, "error": "locked"}]}
        result = _sanitize_pw_admin_pages("P-S", surface)
        assert result == surface

    def test_pw_removes_failed_admin(self):
        surface = {
            "pages": [
                {"id": "home", "name": "首页", "status": 200, "screenshot_saved": "/tmp/a.png"},
                {
                    "id": "admin",
                    "name": "管理端",
                    "admin": True,
                    "error": "digest required",
                    "status": 401,
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1
        assert result["pages"][0]["id"] == "home"

    def test_pw_keeps_ok_admin(self):
        surface = {
            "pages": [
                {
                    "id": "admin",
                    "name": "管理端",
                    "admin": True,
                    "digest_unlock_ok": True,
                    "status": 200,
                    "screenshot_saved": "/tmp/a.png",
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1

    def test_non_dict_surface(self):
        result = _sanitize_pw_admin_pages("P-W", "not a dict")
        assert result == "not a dict"
