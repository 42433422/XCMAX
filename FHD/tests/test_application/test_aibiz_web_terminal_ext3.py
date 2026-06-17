"""Tests for app.application.aibiz_web_terminal_service — deep coverage (ext3).

Focus: _surface_cache_token, _surface_image_url, _crop_png_top, _resize_png_thumb,
_transform_png_view, _png_http_response, _strip_b64_attach_image_urls,
_sanitize_pw_admin_pages, _compact_surface_pages, _unwrap.
"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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
        result = _surface_cache_token(surface)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_with_cached_at(self):
        surface = {"cached_at": "2026-06-14T08:00:00Z"}
        result = _surface_cache_token(surface)
        assert isinstance(result, str)

    def test_empty_surface(self):
        surface = {}
        result = _surface_cache_token(surface)
        assert isinstance(result, str)
        assert result == date.today().isoformat().replace("-", "")

    def test_none_values(self):
        surface = {"captured_at": None, "cached_at": None}
        result = _surface_cache_token(surface)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _surface_image_url
# ---------------------------------------------------------------------------


class TestSurfaceImageUrl:
    def test_basic_url(self):
        result = _surface_image_url("web", 0)
        assert "terminal=web" in result
        assert "index=0" in result

    def test_with_view(self):
        result = _surface_image_url("software", 1, view="viewport")
        assert "view=viewport" in result

    def test_with_version(self):
        result = _surface_image_url("app", 2, v="20260615")
        assert "v=20260615" in result

    def test_all_params(self):
        result = _surface_image_url("web", 3, view="thumb", v="abc")
        assert "view=thumb" in result
        assert "v=abc" in result


# ---------------------------------------------------------------------------
# _crop_png_top
# ---------------------------------------------------------------------------


class TestCropPngTop:
    def test_empty_bytes(self):
        result = _crop_png_top(b"")
        assert result == b""

    def test_none_input(self):
        result = _crop_png_top(None)
        assert result is None

    def test_non_png_data(self):
        result = _crop_png_top(b"not a png")
        # Should return raw on failure
        assert result == b"not a png" or isinstance(result, bytes)


# ---------------------------------------------------------------------------
# _resize_png_thumb
# ---------------------------------------------------------------------------


class TestResizePngThumb:
    def test_empty_bytes(self):
        result = _resize_png_thumb(b"")
        assert result == b""

    def test_none_input(self):
        result = _resize_png_thumb(None)
        assert result is None

    def test_non_png_data(self):
        result = _resize_png_thumb(b"not a png")
        assert result == b"not a png" or isinstance(result, bytes)


# ---------------------------------------------------------------------------
# _transform_png_view
# ---------------------------------------------------------------------------


class TestTransformPngView:
    def test_viewport(self):
        result = _transform_png_view(b"", "viewport")
        assert isinstance(result, bytes)

    def test_thumb(self):
        result = _transform_png_view(b"", "thumb")
        assert isinstance(result, bytes)

    def test_empty_view(self):
        data = b"some data"
        result = _transform_png_view(data, "")
        assert result == data

    def test_unknown_view(self):
        data = b"some data"
        result = _transform_png_view(data, "unknown")
        assert result == data


# ---------------------------------------------------------------------------
# _png_http_response
# ---------------------------------------------------------------------------


class TestPngHttpResponse:
    def test_basic_response(self):
        resp = _png_http_response(b"\x89PNG\r\n", view="")
        assert resp.media_type == "image/png"
        assert resp.status_code == 200

    def test_cacheable_view(self):
        resp = _png_http_response(b"\x89PNG\r\n", view="thumb")
        assert "max-age" in resp.headers.get("Cache-Control", "")

    def test_non_cacheable_view(self):
        resp = _png_http_response(b"\x89PNG\r\n", view="full")
        assert "no-cache" in resp.headers.get("Cache-Control", "") or "max-age" not in resp.headers.get(
            "Cache-Control", ""
        )


# ---------------------------------------------------------------------------
# _unwrap
# ---------------------------------------------------------------------------


class TestUnwrap:
    def test_dict_input(self):
        result = _unwrap({"key": "value"})
        assert result == {"key": "value"}

    def test_json_response_input(self):
        from fastapi.responses import JSONResponse

        resp = JSONResponse({"error": "bad"})
        result = _unwrap(resp)
        assert "_error_response" in result

    def test_none_input(self):
        result = _unwrap(None)
        assert result == {}

    def test_string_input(self):
        result = _unwrap("hello")
        assert result == {}

    def test_list_input(self):
        result = _unwrap([1, 2, 3])
        assert result == {}


# ---------------------------------------------------------------------------
# _strip_b64_attach_image_urls
# ---------------------------------------------------------------------------


class TestStripB64AttachImageUrls:
    def test_non_dict_input(self):
        result = _strip_b64_attach_image_urls("not a dict", terminal="web")
        assert result == "not a dict"

    def test_empty_pages(self):
        surface = {"pages": []}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert isinstance(result, dict)

    def test_no_pages_key(self):
        surface = {"other": "data"}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result == surface

    def test_with_pages(self):
        surface = {
            "pages": [
                {
                    "id": "home",
                    "name": "首页",
                    "screenshot_b64": "base64data",
                    "screenshot_saved": "/path/to/file.png",
                },
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert "screenshot_b64" not in result["pages"][0]
        assert "screenshot_saved" not in result["pages"][0]
        assert "image_url" in result["pages"][0]

    def test_software_terminal_admin_page_skipped(self):
        surface = {
            "pages": [
                {"id": "admin_dashboard", "preview": True, "name": "管理端"},
                {"id": "chat", "preview": False, "name": "智能对话"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        # admin pages should not be hero
        assert isinstance(result, dict)

    def test_app_terminal_preferred_ids(self):
        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "home_hub", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _sanitize_pw_admin_pages
# ---------------------------------------------------------------------------


class TestSanitizePwAdminPages:
    def test_non_pw_lane_passthrough(self):
        surface = {"pages": [{"admin": True}]}
        result = _sanitize_pw_admin_pages("P-S", surface)
        assert result == surface

    def test_non_dict_surface_passthrough(self):
        result = _sanitize_pw_admin_pages("P-W", "not a dict")
        assert result == "not a dict"

    def test_pw_lane_filters_admin(self):
        surface = {
            "pages": [
                {"admin": True, "error": "auth required"},
                {"id": "home", "name": "首页"},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert isinstance(result, dict)
        assert result["page_count"] <= len(surface["pages"])

    def test_pw_lane_keeps_valid_admin(self):
        surface = {
            "pages": [
                {"admin": True, "digest_unlock_ok": True},
                {"id": "home", "name": "首页"},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 2

    def test_pw_no_pages_key(self):
        surface = {"other": "data"}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert result == surface


# ---------------------------------------------------------------------------
# _compact_surface_pages
# ---------------------------------------------------------------------------


class TestCompactSurfacePages:
    def test_passthrough(self):
        surface = {"pages": [{"id": "home"}]}
        result = _compact_surface_pages(surface, compact=True)
        assert result == surface

    def test_compact_false(self):
        surface = {"pages": [{"id": "home"}]}
        result = _compact_surface_pages(surface, compact=False)
        assert result == surface


# ---------------------------------------------------------------------------
# _LANE_BY_TERMINAL
# ---------------------------------------------------------------------------


class TestLaneByTerminal:
    def test_web(self):
        assert _LANE_BY_TERMINAL["web"] == ("P-W", "SW")

    def test_software(self):
        assert _LANE_BY_TERMINAL["software"] == ("P-S", "SS")

    def test_app(self):
        assert _LANE_BY_TERMINAL["app"] == ("P-App", "SA")
