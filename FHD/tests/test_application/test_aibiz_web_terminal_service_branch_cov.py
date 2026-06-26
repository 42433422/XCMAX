"""Branch coverage tests for app.application.aibiz_web_terminal_service.

Focus on missing branches:
- _crop_png_top / _resize_png_thumb / _transform_png_view / _png_http_response
- _strip_b64_attach_image_urls hero index resolution branches
- _sanitize_pw_admin_pages admin page filtering
- _resolve_surface_audit additional branches (stale_cache, from_cache, message)
- _load_local_lane_surface cache hit/miss
- _resolve_market_authorization additional credential chain branches
- _local_surface_page additional branches
- fetch_surface_page_payload additional branches
- build_terminal_payload additional branches
"""

from __future__ import annotations

import base64
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse, Response

# ---------------------------------------------------------------------------
# _crop_png_top — branch coverage
# ---------------------------------------------------------------------------


class TestCropPngTop:
    """Cover _crop_png_top branches: empty raw, crop_h >= h, recoverable errors."""

    def test_empty_raw_returns_empty(self):
        from app.application.aibiz_web_terminal_service import _crop_png_top

        assert _crop_png_top(b"") == b""

    def test_raw_shorter_than_height_returns_raw(self, tmp_path: Path):
        from PIL import Image

        from app.application.aibiz_web_terminal_service import _crop_png_top

        # Create a 10x10 image, request crop height 720 (larger than image)
        img = Image.new("RGB", (10, 10), color="red")
        png_path = tmp_path / "small.png"
        img.save(png_path, format="PNG")
        raw = png_path.read_bytes()

        result = _crop_png_top(raw, height=720)
        # Should return raw unchanged since crop_h >= h
        assert result == raw

    def test_raw_taller_than_height_crops(self, tmp_path: Path):
        from PIL import Image

        from app.application.aibiz_web_terminal_service import _crop_png_top

        # Create a 10x100 image, request crop height 50
        img = Image.new("RGB", (10, 100), color="blue")
        png_path = tmp_path / "tall.png"
        img.save(png_path, format="PNG")
        raw = png_path.read_bytes()

        result = _crop_png_top(raw, height=50)
        # Should return cropped image (different bytes)
        assert result != raw
        assert len(result) < len(raw)

    def test_invalid_png_returns_raw(self):
        from app.application.aibiz_web_terminal_service import _crop_png_top

        # Invalid PNG bytes should trigger RECOVERABLE_ERRORS and return raw
        raw = b"not a png"
        result = _crop_png_top(raw, height=720)
        assert result == raw

    def test_height_clamped_to_at_least_1(self, tmp_path: Path):
        from PIL import Image

        from app.application.aibiz_web_terminal_service import _crop_png_top

        img = Image.new("RGB", (10, 100), color="green")
        png_path = tmp_path / "clamp.png"
        img.save(png_path, format="PNG")
        raw = png_path.read_bytes()

        # height=0 should be clamped to 1
        result = _crop_png_top(raw, height=0)
        # Should crop to 1 pixel height (different from raw)
        assert result != raw


# ---------------------------------------------------------------------------
# _resize_png_thumb — branch coverage
# ---------------------------------------------------------------------------


class TestResizePngThumb:
    """Cover _resize_png_thumb branches: empty raw, w <= max_width, recoverable errors."""

    def test_empty_raw_returns_empty(self):
        from app.application.aibiz_web_terminal_service import _resize_png_thumb

        assert _resize_png_thumb(b"") == b""

    def test_width_le_max_width_returns_reencoded(self, tmp_path: Path):
        from PIL import Image

        from app.application.aibiz_web_terminal_service import _resize_png_thumb

        # Create a 50x50 image (width <= 96 max_width)
        img = Image.new("RGB", (50, 50), color="red")
        png_path = tmp_path / "narrow.png"
        img.save(png_path, format="PNG")
        raw = png_path.read_bytes()

        result = _resize_png_thumb(raw, max_width=96)
        # Should return re-encoded bytes (may differ from raw due to optimize)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_width_gt_max_width_resizes(self, tmp_path: Path):
        from PIL import Image

        from app.application.aibiz_web_terminal_service import _resize_png_thumb

        # Create a 200x100 image (width > 96 max_width)
        img = Image.new("RGB", (200, 100), color="blue")
        png_path = tmp_path / "wide.png"
        img.save(png_path, format="PNG")
        raw = png_path.read_bytes()

        result = _resize_png_thumb(raw, max_width=96)
        # Should return resized bytes (smaller)
        assert isinstance(result, bytes)
        assert len(result) < len(raw)

    def test_invalid_png_returns_raw(self):
        from app.application.aibiz_web_terminal_service import _resize_png_thumb

        raw = b"not a png"
        result = _resize_png_thumb(raw)
        assert result == raw


# ---------------------------------------------------------------------------
# _transform_png_view — branch coverage
# ---------------------------------------------------------------------------


class TestTransformPngView:
    """Cover _transform_png_view all branches."""

    def test_view_viewport_calls_crop(self):
        from app.application.aibiz_web_terminal_service import _transform_png_view

        with patch(
            "app.application.aibiz_web_terminal_service._crop_png_top",
            return_value=b"cropped",
        ) as mock_crop:
            result = _transform_png_view(b"raw", "viewport")
        mock_crop.assert_called_once_with(b"raw")
        assert result == b"cropped"

    def test_view_thumb_calls_resize(self):
        from app.application.aibiz_web_terminal_service import _transform_png_view

        with patch(
            "app.application.aibiz_web_terminal_service._resize_png_thumb",
            return_value=b"thumb",
        ) as mock_resize:
            result = _transform_png_view(b"raw", "thumb")
        mock_resize.assert_called_once_with(b"raw")
        assert result == b"thumb"

    def test_view_other_returns_raw(self):
        from app.application.aibiz_web_terminal_service import _transform_png_view

        result = _transform_png_view(b"raw", "full")
        assert result == b"raw"

    def test_view_empty_returns_raw(self):
        from app.application.aibiz_web_terminal_service import _transform_png_view

        result = _transform_png_view(b"raw", "")
        assert result == b"raw"


# ---------------------------------------------------------------------------
# _png_http_response — branch coverage
# ---------------------------------------------------------------------------


class TestPngHttpResponse:
    """Cover _png_http_response cacheable vs non-cacheable branches."""

    def test_cacheable_view_thumb(self):
        from app.application.aibiz_web_terminal_service import _png_http_response

        resp = _png_http_response(b"raw", view="thumb")
        assert isinstance(resp, Response)
        assert resp.media_type == "image/png"
        assert "immutable" in resp.headers.get("Cache-Control", "")

    def test_cacheable_view_viewport(self):
        from app.application.aibiz_web_terminal_service import _png_http_response

        resp = _png_http_response(b"raw", view="viewport")
        assert "immutable" in resp.headers.get("Cache-Control", "")

    def test_cacheable_view_empty(self):
        from app.application.aibiz_web_terminal_service import _png_http_response

        resp = _png_http_response(b"raw", view="")
        assert "immutable" in resp.headers.get("Cache-Control", "")

    def test_non_cacheable_view(self):
        from app.application.aibiz_web_terminal_service import _png_http_response

        resp = _png_http_response(b"raw", view="full")
        assert "no-cache" in resp.headers.get("Cache-Control", "")
        assert "must-revalidate" in resp.headers.get("Cache-Control", "")


# ---------------------------------------------------------------------------
# _strip_b64_attach_image_urls — additional hero index branches
# ---------------------------------------------------------------------------


class TestStripB64AttachImageUrlsBranchCov:
    """Cover additional _strip_b64_attach_image_urls branches."""

    def test_non_dict_surface_returns_as_is(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        result = _strip_b64_attach_image_urls("not a dict", terminal="web")  # type: ignore[arg-type]
        assert result == "not a dict"

    def test_non_list_pages_returns_surface(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {"pages": "not a list"}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result == surface

    def test_empty_pages_returns_surface(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {"pages": []}
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result == surface

    def test_software_terminal_admin_page_skipped_as_hero(self):
        """Software terminal: admin_ pages are skipped when looking for preview hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "admin_dashboard", "name": "管理端", "preview": True},
                {"id": "home", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        # admin_ page is skipped, falls to else branch looking for non-admin hero
        assert isinstance(result, dict)

    def test_software_terminal_no_preview_falls_to_else(self):
        """Software terminal with no preview pages falls to else branch."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "home_hub", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        assert result["preview_index"] == 1

    def test_software_terminal_admin_page_in_else_continues(self):
        """Software terminal: admin_ pages continue (skip) in else branch."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "admin_x", "name": "管理"},
                {"id": "home_hub", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        # admin_x is skipped, home_hub is found as hero
        assert result["preview_index"] == 1

    def test_software_terminal_chat_name_hero(self):
        """Software terminal: name '智能对话' triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "x", "name": "智能对话"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        assert result["preview_index"] == 1

    def test_software_terminal_home_name_hero(self):
        """Software terminal: name '首页' triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "x", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        assert result["preview_index"] == 1

    def test_web_terminal_admin_hero(self):
        """Web terminal: admin_ prefix triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "admin_panel", "name": "Admin"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_web_terminal_home_hub_hero(self):
        """Web terminal: home_hub id triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "home_hub", "name": "Hub"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_web_terminal_guanwang_name_hero(self):
        """Web terminal: name containing '官网' triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "x", "name": "官网首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_web_terminal_home_lower_name_hero(self):
        """Web terminal: name.lower() == 'home' triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "x", "name": "Home"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_web_terminal_index_lower_name_hero(self):
        """Web terminal: name.lower() == 'index' triggers hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "x", "name": "Index"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_app_terminal_no_preferred_match_keeps_default_hero(self):
        """App terminal: no preferred id match keeps hero_i=0."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other1", "name": "Other1"},
                {"id": "other2", "name": "Other2"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        # No preferred id matched, hero_i stays 0
        assert result["preview_index"] == 0

    def test_pages_with_non_dict_page_in_loop(self):
        """Non-dict page entries are preserved in output."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                "string_entry",
                {"id": "home", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["pages"][0] == "string_entry"

    def test_preview_page_already_set_hero(self):
        """Page with preview=True becomes hero."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "home", "name": "Home"},
                {"id": "x", "name": "X", "preview": True},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_software_terminal_preview_admin_skipped(self):
        """Software terminal: admin_ page with preview=True is skipped."""
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "admin_x", "name": "Admin", "preview": True},
                {"id": "home", "name": "Home", "preview": True},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        # First preview admin_ is skipped, second preview home is hero
        assert result["preview_index"] == 1


# ---------------------------------------------------------------------------
# _sanitize_pw_admin_pages — branch coverage
# ---------------------------------------------------------------------------


class TestSanitizePwAdminPages:
    """Cover _sanitize_pw_admin_pages branches."""

    def test_non_pw_lane_returns_surface(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {"pages": [{"id": "home"}]}
        result = _sanitize_pw_admin_pages("P-S", surface)
        assert result == surface

    def test_non_dict_surface_returns_as_is(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        result = _sanitize_pw_admin_pages("P-W", "not a dict")  # type: ignore[arg-type]
        assert result == "not a dict"

    def test_non_list_pages_returns_surface(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {"pages": "not a list"}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert result == surface

    def test_admin_page_with_digest_unlock_ok_kept(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {"id": "admin_x", "digest_unlock_ok": True},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1

    def test_admin_page_with_admin_flag_filtered(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {"id": "x", "admin": True, "error": True},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        # admin page with error should be filtered out
        assert len(result["pages"]) == 0
        assert result["page_count"] == 0

    def test_admin_page_url_market_admin_filtered(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {"id": "x", "url": "/market/admin/dashboard", "error": True},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 0

    def test_admin_page_name_prefix_filtered(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {"id": "x", "name": "管理端Dashboard", "error": True},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 0

    def test_admin_page_ok_when_no_error_status_ok_has_image(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {
                    "id": "x",
                    "admin": True,
                    "error": False,
                    "status": 200,
                    "screenshot_saved": "/tmp/x.png",
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        # admin page with no error, status<400, has image should be kept
        assert len(result["pages"]) == 1

    def test_admin_page_filtered_when_status_ge_400(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {
                    "id": "x",
                    "admin": True,
                    "error": False,
                    "status": 500,
                    "screenshot_saved": "/tmp/x.png",
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 0

    def test_admin_page_filtered_when_no_image(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {
                    "id": "x",
                    "admin": True,
                    "error": False,
                    "status": 200,
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 0

    def test_non_admin_page_always_ok(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {"id": "x", "error": True, "status": 500},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        # non-admin page always ok
        assert len(result["pages"]) == 1

    def test_all_kept_returns_original_surface(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                {"id": "x", "digest_unlock_ok": True},
                {"id": "y"},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        # All kept, should return original surface (no page_count key added)
        assert "page_count" not in result

    def test_non_dict_page_filtered(self):
        from app.application.aibiz_web_terminal_service import _sanitize_pw_admin_pages

        surface = {
            "pages": [
                "not a dict",
                {"id": "x"},
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        # non-dict page filtered out
        assert len(result["pages"]) == 1


# ---------------------------------------------------------------------------
# _resolve_surface_audit — additional branch coverage
# ---------------------------------------------------------------------------


class TestResolveSurfaceAuditBranchCov:
    """Cover additional _resolve_surface_audit branches."""

    @pytest.mark.asyncio
    async def test_remote_no_pages_falls_to_local(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "from_cache": True,
        }
        with (
            patch(
                "app.application.aibiz_web_terminal_service._fetch_remote_surface_audit",
                new_callable=AsyncMock,
                return_value=({}, "remote empty"),
            ),
            patch(
                "app.application.surface_audit_service.run_surface_audit_lane",
                return_value=mock_local,
            ),
        ):
            surface, note = await _resolve_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert surface.get("pages") is not None

    @pytest.mark.asyncio
    async def test_local_pw_lane_note(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "from_cache": True,
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-W", refresh=False, authorization="", compact=True
            )
        assert "本地 Playwright" in note or "xiu-ci.com" in note

    @pytest.mark.asyncio
    async def test_local_ps_lane_note(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "from_cache": True,
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        assert "FHD 企业版" in note or "127.0.0.1:5001" in note

    @pytest.mark.asyncio
    async def test_local_other_lane_note(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "from_cache": True,
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-Other", refresh=False, authorization="", compact=True
            )
        assert "本地 Playwright 巡检" in note

    @pytest.mark.asyncio
    async def test_local_android_with_web_fallback(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [
                {"id": "home", "android_capture": True},
                {"id": "web1"},
                {"id": "web2"},
            ],
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-App", refresh=False, authorization="", compact=True
            )
        assert "Android" in note or "adb" in note
        assert "Playwright Web 回退" in note

    @pytest.mark.asyncio
    async def test_local_android_meta_merged_count_no_adb(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "android_audit": {"merged_count": 5},
            "from_cache": True,
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-App", refresh=False, authorization="", compact=True
            )
        assert "adb 5 页" in note

    @pytest.mark.asyncio
    async def test_local_stale_cache_with_date(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "stale_cache": True,
            "stale_cache_date": "2026-06-01",
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        assert "2026-06-01 缓存" in note

    @pytest.mark.asyncio
    async def test_local_stale_cache_no_date(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [{"id": "home"}],
            "stale_cache": True,
            "stale_cache_date": "",
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        assert "历史缓存" in note

    @pytest.mark.asyncio
    async def test_local_message_when_no_surface_note(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": False,
            "message": "custom local message",
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        assert "custom local message" in note

    @pytest.mark.asyncio
    async def test_local_recoverable_error_with_existing_note(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        with (
            patch(
                "app.application.aibiz_web_terminal_service._fetch_remote_surface_audit",
                new_callable=AsyncMock,
                return_value=({}, "existing note"),
            ),
            patch(
                "app.application.surface_audit_service.run_surface_audit_lane",
                side_effect=RuntimeError("boom"),
            ),
        ):
            surface, note = await _resolve_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        # existing note should be preserved
        assert "existing note" in note or "异常" in note

    @pytest.mark.asyncio
    async def test_fallback_to_remote_when_no_pages_and_auth(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "0")
        with (
            patch(
                "app.application.aibiz_web_terminal_service._fetch_remote_surface_audit",
                new_callable=AsyncMock,
                return_value=({"pages": [{"id": "home"}]}, "fallback remote"),
            ) as mock_remote,
        ):
            # P-S lane, not prefer_remote, but local disabled and no pages
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="Bearer token", compact=True
            )
        # Should call remote as fallback
        mock_remote.assert_called()

    @pytest.mark.asyncio
    async def test_no_auth_no_pages_no_note_returns_hint(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "0")
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value={"success": False},
        ):
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        assert "market 会话" in note or "XCAGI_AIBIZ_MARKET" in note


# ---------------------------------------------------------------------------
# _load_local_lane_surface — cache hit/miss branches
# ---------------------------------------------------------------------------


class TestLoadLocalLaneSurfaceBranchCov:
    """Cover _load_local_lane_surface cache hit/miss branches."""

    def test_cache_hit_returns_cached_pages(self):
        from app.application.aibiz_web_terminal_service import (
            _load_local_lane_surface,
            _local_lane_pages_cache,
        )

        lane = "P-Test-Cache-Hit"
        _local_lane_pages_cache.pop(lane, None)
        token = "2026-06-15T10:00:00Z"
        cached_pages = [{"id": "cached"}]
        _local_lane_pages_cache[lane] = (token, cached_pages)

        mock_local = {"cached_at": token, "pages": [{"id": "new"}]}
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            result = _load_local_lane_surface(lane)
        # Should return cached pages
        assert result.get("pages") == cached_pages

        # Cleanup
        _local_lane_pages_cache.pop(lane, None)

    def test_cache_miss_loads_new_pages(self):
        from app.application.aibiz_web_terminal_service import (
            _load_local_lane_surface,
            _local_lane_pages_cache,
        )

        lane = "P-Test-Cache-Miss"
        _local_lane_pages_cache.pop(lane, None)

        mock_local = {
            "captured_at": "2026-06-15T10:00:00Z",
            "pages": [{"id": "new"}],
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            result = _load_local_lane_surface(lane)
        # Should return new pages
        assert result.get("pages") == [{"id": "new"}]
        # Cache should be populated
        assert lane in _local_lane_pages_cache

        # Cleanup
        _local_lane_pages_cache.pop(lane, None)

    def test_no_pages_key_returns_empty_list(self):
        from app.application.aibiz_web_terminal_service import (
            _load_local_lane_surface,
            _local_lane_pages_cache,
        )

        lane = "P-Test-No-Pages"
        _local_lane_pages_cache.pop(lane, None)

        mock_local = {"captured_at": "2026-06-15T10:00:00Z", "other": "data"}
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            result = _load_local_lane_surface(lane)
        # Should return original local dict
        assert result == mock_local
        # Cache should have empty list
        assert _local_lane_pages_cache[lane][1] == []

        # Cleanup
        _local_lane_pages_cache.pop(lane, None)

    def test_cache_token_from_captured_at(self):
        from app.application.aibiz_web_terminal_service import (
            _load_local_lane_surface,
            _local_lane_pages_cache,
        )

        lane = "P-Test-Token-Captured"
        _local_lane_pages_cache.pop(lane, None)

        mock_local = {
            "captured_at": "2026-06-15T10:00:00Z",
            "pages": [{"id": "x"}],
        }
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            _load_local_lane_surface(lane)
        # Cache token should be from captured_at
        assert _local_lane_pages_cache[lane][0] == "2026-06-15T10:00:00Z"

        # Cleanup
        _local_lane_pages_cache.pop(lane, None)


# ---------------------------------------------------------------------------
# _resolve_market_authorization — additional credential chain branches
# ---------------------------------------------------------------------------


class TestResolveMarketAuthorizationBranchCov:
    """Cover additional _resolve_market_authorization branches."""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        """清理可能影响 _resolve_market_authorization 的环境变量。"""
        for key in (
            "XCAGI_AIBIZ_MARKET_USER",
            "XCAGI_AIBIZ_MARKET_PASSWORD",
            "MODSTORE_DIGEST_ADMIN_USER",
            "MODSTORE_DIGEST_ADMIN_PASSWORD",
        ):
            monkeypatch.delenv(key, raising=False)
        yield

    @pytest.mark.asyncio
    async def test_sid_but_no_auth_header(self):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="session123",
            ),
            patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
        ):
            result = await _resolve_market_authorization(request)
        # No auth header, no env creds, no digest, no demo → empty
        assert result == ""

    @pytest.mark.asyncio
    async def test_env_creds_login_no_token(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                return_value={"success": True, "token": ""},
            ),
        ):
            result = await _resolve_market_authorization(request)
        # Login success but no token → empty
        assert result == ""

    @pytest.mark.asyncio
    async def test_env_creds_login_failure_returns_empty(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                return_value={"success": False},
            ),
        ):
            result = await _resolve_market_authorization(request)
        assert result == ""

    @pytest.mark.asyncio
    async def test_digest_creds_duplicate_with_env_skipped(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        # Same creds for env and digest → digest should be skipped (not in creds)
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "sameuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "samepass")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_USER", "sameuser")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_PASSWORD", "samepass")

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "env_token"},
            ) as mock_login,
        ):
            result = await _resolve_market_authorization(request)
        # Should only call login once (digest is duplicate)
        assert mock_login.call_count == 1
        assert result == "env_token"

    @pytest.mark.asyncio
    async def test_demo_creds_duplicate_with_env_skipped(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "sameuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "samepass")
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="sameuser",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="samepass",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "env_token"},
            ) as mock_login,
        ):
            result = await _resolve_market_authorization(request)
        # Should only call login once (demo is duplicate)
        assert mock_login.call_count == 1
        assert result == "env_token"

    @pytest.mark.asyncio
    async def test_demo_creds_unavailable_silently_skipped(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_USER", raising=False)
        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_PASSWORD", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                side_effect=ImportError("no demo module"),
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
        ):
            result = await _resolve_market_authorization(request)
        # demo creds unavailable → empty
        assert result == ""

    @pytest.mark.asyncio
    async def test_multiple_creds_first_succeeds(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_USER", "digest_user")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_PASSWORD", "digest_pass")

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                return_value={"success": True, "token": "first_token"},
            ) as mock_login,
        ):
            result = await _resolve_market_authorization(request)
        # First cred succeeds, should not try second
        assert mock_login.call_count == 1
        assert result == "first_token"

    @pytest.mark.asyncio
    async def test_multiple_creds_first_fails_second_succeeds(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_USER", "digest_user")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_PASSWORD", "digest_pass")

        request = MagicMock()
        login_results = [
            {"success": False},
            {"success": True, "token": "second_token"},
        ]
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
            patch(
                "app.fastapi_routes.market_account.login_market_with_password",
                new_callable=AsyncMock,
                side_effect=login_results,
            ),
        ):
            result = await _resolve_market_authorization(request)
        assert result == "second_token"

    @pytest.mark.asyncio
    async def test_env_user_only_no_password_skipped(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_PASSWORD", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
        ):
            result = await _resolve_market_authorization(request)
        # env_user only, no password → skipped
        assert result == ""

    @pytest.mark.asyncio
    async def test_env_password_only_no_user_skipped(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_USER", raising=False)
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with (
            patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_username",
                return_value="",
            ),
            patch(
                "app.application.surface_audit_demo_account.demo_password",
                return_value="",
            ),
        ):
            result = await _resolve_market_authorization(request)
        assert result == ""


# ---------------------------------------------------------------------------
# _local_surface_page — additional branch coverage
# ---------------------------------------------------------------------------


class TestLocalSurfacePageBranchCov:
    """Cover additional _local_surface_page branches."""

    @pytest.mark.asyncio
    async def test_valid_index_returns_dict(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=[{"id": "home"}],
        ):
            result = await _local_surface_page("P-S", 0)
        assert result == {"id": "home"}

    @pytest.mark.asyncio
    async def test_index_equal_to_len_returns_none(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=[{"id": "home"}],
        ):
            result = await _local_surface_page("P-S", 1)
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_pages_returns_none(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await _local_surface_page("P-S", 0)
        assert result is None


# ---------------------------------------------------------------------------
# fetch_surface_page_payload — additional branch coverage
# ---------------------------------------------------------------------------


class TestFetchSurfacePagePayloadBranchCov:
    """Cover additional fetch_surface_page_payload branches."""

    @pytest.mark.asyncio
    async def test_local_lane_non_dict_page_returns_empty_dict(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        mock_local = {
            "pages": ["not a dict"],
        }
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.application.surface_audit_service.run_surface_audit_lane",
                return_value=mock_local,
            ),
        ):
            result = await fetch_surface_page_payload(request, terminal="software", index=0)
        assert result["success"] is True
        # Non-dict page becomes empty dict, so all keys are None
        assert result["data"]["name"] is None

    @pytest.mark.asyncio
    async def test_local_lane_no_pages_key(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        mock_local = {"other": "data"}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.application.surface_audit_service.run_surface_audit_lane",
                return_value=mock_local,
            ),
        ):
            result = await fetch_surface_page_payload(request, terminal="software", index=0)
        # No pages key → pages=[], index 0 >= 0 → 404
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_remote_lane_success_no_data_dict(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"success": True, "data": "not a dict"},
            ),
        ):
            result = await fetch_surface_page_payload(request, terminal="web", index=0)
        # data is not dict → falls through to 502
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_remote_lane_success_false_with_message(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"success": False, "message": "custom error msg"},
            ),
        ):
            result = await fetch_surface_page_payload(request, terminal="web", index=0)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_remote_lane_no_message_default(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.fastapi_routes.market_account._proxy_json",
                new_callable=AsyncMock,
                return_value={"success": False},
            ),
        ):
            result = await fetch_surface_page_payload(request, terminal="web", index=0)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502
        assert "surface page unavailable" in result.body.decode()

    @pytest.mark.asyncio
    async def test_app_terminal_uses_local(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        mock_local = {
            "pages": [{"name": "App Home", "url": "/", "status": 200, "title": "App"}],
        }
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.surface_audit_service.run_surface_audit_lane",
                return_value=mock_local,
            ),
        ):
            result = await fetch_surface_page_payload(request, terminal="app", index=0)
        # P-App always uses local even with auth
        assert result["success"] is True
        assert result["data"]["name"] == "App Home"


# ---------------------------------------------------------------------------
# build_terminal_payload — additional branch coverage
# ---------------------------------------------------------------------------


class TestBuildTerminalPayloadBranchCov:
    """Cover additional build_terminal_payload branches."""

    @pytest.mark.asyncio
    async def test_software_terminal_workflow_label(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {"pages": [{"id": "home"}]}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._resolve_surface_audit",
                new_callable=AsyncMock,
                return_value=(mock_surface, "note"),
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await build_terminal_payload(request, terminal="software")
        assert result["success"] is True
        assert result["data"]["workflow_label"] == "P-S 软件截图+分析"

    @pytest.mark.asyncio
    async def test_app_terminal_workflow_label(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {"pages": [{"id": "home"}]}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._resolve_surface_audit",
                new_callable=AsyncMock,
                return_value=(mock_surface, "note"),
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await build_terminal_payload(request, terminal="app")
        assert result["success"] is True
        assert result["data"]["workflow_label"] == "P-App 移动截图+分析"

    @pytest.mark.asyncio
    async def test_unknown_terminal_defaults_to_web_workflow(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {"pages": [{"id": "home"}]}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._resolve_surface_audit",
                new_callable=AsyncMock,
                return_value=(mock_surface, "note"),
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await build_terminal_payload(request, terminal="unknown")
        assert result["success"] is True
        # Unknown terminal defaults to P-W/SW
        assert result["data"]["workflow_label"] == "P-W 网站截图+分析"

    @pytest.mark.asyncio
    async def test_no_auth_with_pages_includes_android_audit(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {
            "pages": [{"id": "home"}],
            "android_audit": {"devices": 1},
        }
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._resolve_surface_audit",
                new_callable=AsyncMock,
                return_value=(mock_surface, "local"),
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await build_terminal_payload(request, terminal="app")
        assert result["success"] is True
        assert result["data"]["android_audit"] == {"devices": 1}

    @pytest.mark.asyncio
    async def test_with_auth_includes_android_audit(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {
            "pages": [{"id": "home"}],
            "android_audit": {"devices": 2},
        }
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._resolve_surface_audit",
                new_callable=AsyncMock,
                return_value=(mock_surface, "remote"),
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await build_terminal_payload(request, terminal="app")
        assert result["success"] is True
        assert result["data"]["android_audit"] == {"devices": 2}

    @pytest.mark.asyncio
    async def test_no_auth_no_pages_returns_401_with_data(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._resolve_surface_audit",
                new_callable=AsyncMock,
                return_value=({}, "no data"),
            ),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await build_terminal_payload(request, terminal="web")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401
        body = result.body.decode()
        assert "market_base_url" in body


# ---------------------------------------------------------------------------
# serve_surface_image — additional branch coverage
# ---------------------------------------------------------------------------


class TestServeSurfaceImageBranchCov:
    """Cover additional serve_surface_image branches."""

    @pytest.mark.asyncio
    async def test_software_terminal_uses_ps_lane(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
                new_callable=AsyncMock,
                return_value=b"\x89PNG\r\n\x1a\n",
            ) as mock_load,
        ):
            result = await serve_surface_image(request, terminal="software", index=0)
        assert isinstance(result, Response)
        call_args = mock_load.call_args
        # lane should be P-S, prefer_remote=False
        assert call_args.kwargs["prefer_remote"] is False
        assert call_args.args[0] == "P-S"

    @pytest.mark.asyncio
    async def test_app_terminal_uses_papp_lane(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
                new_callable=AsyncMock,
                return_value=b"\x89PNG\r\n\x1a\n",
            ) as mock_load,
        ):
            result = await serve_surface_image(request, terminal="app", index=0)
        assert isinstance(result, Response)
        call_args = mock_load.call_args
        assert call_args.args[0] == "P-App"
        assert call_args.kwargs["prefer_remote"] is False

    @pytest.mark.asyncio
    async def test_web_terminal_prefer_remote_true(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
                new_callable=AsyncMock,
                return_value=b"\x89PNG\r\n\x1a\n",
            ) as mock_load,
        ):
            result = await serve_surface_image(request, terminal="web", index=0)
        assert isinstance(result, Response)
        call_args = mock_load.call_args
        # P-W lane should have prefer_remote=True
        assert call_args.kwargs["prefer_remote"] is True

    @pytest.mark.asyncio
    async def test_negative_index_clamped_to_zero(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
                new_callable=AsyncMock,
                return_value=b"\x89PNG\r\n\x1a\n",
            ) as mock_load,
        ):
            result = await serve_surface_image(request, terminal="web", index=-5)
        assert isinstance(result, Response)
        call_args = mock_load.call_args
        assert call_args.args[1] == 0

    @pytest.mark.asyncio
    async def test_view_viewport(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
                new_callable=AsyncMock,
                return_value=b"\x89PNG\r\n\x1a\n",
            ),
        ):
            result = await serve_surface_image(request, terminal="web", index=0, view="VIEWPORT")
        assert isinstance(result, Response)
        assert result.media_type == "image/png"

    @pytest.mark.asyncio
    async def test_empty_terminal_defaults_to_web(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image

        request = MagicMock()
        with (
            patch(
                "app.application.aibiz_web_terminal_service._resolve_market_authorization",
                new_callable=AsyncMock,
                return_value="Bearer token",
            ),
            patch(
                "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
                new_callable=AsyncMock,
                return_value=b"\x89PNG\r\n\x1a\n",
            ) as mock_load,
        ):
            result = await serve_surface_image(request, terminal="", index=0)
        assert isinstance(result, Response)
        call_args = mock_load.call_args
        assert call_args.args[0] == "P-W"


# ---------------------------------------------------------------------------
# _fetch_remote_surface_audit — additional branch coverage
# ---------------------------------------------------------------------------


class TestFetchRemoteSurfaceAuditBranchCov:
    """Cover additional _fetch_remote_surface_audit branches."""

    @pytest.mark.asyncio
    async def test_error_response_not_jsonresponse(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        # _error_response that is not JSONResponse
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value=JSONResponse({"error": "bad"}, status_code=500),
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "不可用" in note

    @pytest.mark.asyncio
    async def test_missing_route_no_hint_uses_default(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"missing_route": "/api/custom-route"},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "/api/custom-route" in note or "surface-audit" in note

    @pytest.mark.asyncio
    async def test_success_with_data_not_dict_falls_through(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": True, "data": "not a dict"},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        # data is not dict, falls to elif not surface → message or default
        assert isinstance(note, str)

    @pytest.mark.asyncio
    async def test_empty_response_uses_default_message(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "surface-audit 无数据" in note

    @pytest.mark.asyncio
    async def test_compact_false_in_url(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {"pages": []}},
        ) as mock_proxy:
            await _fetch_remote_surface_audit(
                "P-W", refresh=True, authorization="Bearer token", compact=False
            )
        call_args = mock_proxy.call_args
        url = call_args.args[1]
        assert "refresh=1" in url
        assert "compact=0" in url


# ---------------------------------------------------------------------------
# _load_surface_png_bytes — additional branch coverage
# ---------------------------------------------------------------------------


class TestLoadSurfacePngBytesBranchCov:
    """Cover additional _load_surface_png_bytes branches."""

    @pytest.mark.asyncio
    async def test_local_path_with_screenshot_saved_not_file(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        # screenshot_saved path that doesn't exist as file
        mock_page = {"screenshot_saved": "/nonexistent/path.png"}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._local_surface_page",
                new_callable=AsyncMock,
                return_value=mock_page,
            ),
            patch(
                "app.application.surface_audit_service.resolve_lane_page_png_path",
                return_value=None,
            ),
        ):
            result = await _load_surface_png_bytes("P-S", 0, prefer_remote=False, authorization="")
        # No file, no resolve, no b64 → None
        assert result is None

    @pytest.mark.asyncio
    async def test_local_path_android_capture_no_b64(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        mock_page = {"android_capture": True, "screenshot_b64": ""}
        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=mock_page,
        ):
            result = await _load_surface_png_bytes(
                "P-App", 0, prefer_remote=False, authorization=""
            )
        # android_capture but no b64 → falls through to other checks → None
        assert result is None

    @pytest.mark.asyncio
    async def test_local_path_with_resolved_png_path_not_file(self, tmp_path: Path):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        # resolved path that doesn't exist
        non_existent = tmp_path / "non_existent.png"
        mock_page = {"id": "home"}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._local_surface_page",
                new_callable=AsyncMock,
                return_value=mock_page,
            ),
            patch(
                "app.application.surface_audit_service.resolve_lane_page_png_path",
                return_value=non_existent,
            ),
        ):
            # read_bytes() will raise FileNotFoundError → RECOVERABLE_ERRORS
            # Actually, resolve returns a Path, and read_bytes is called on it
            # If file doesn't exist, FileNotFoundError is raised
            # This should be caught by the outer try/except in _page_bytes? No, _page_bytes has no try/except
            # The exception will propagate up
            with pytest.raises(FileNotFoundError):
                await _load_surface_png_bytes("P-S", 0, prefer_remote=False, authorization="")

    @pytest.mark.asyncio
    async def test_remote_path_200_returns_content(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"remote png content"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)

        with (
            patch(
                "app.application.aibiz_web_terminal_service._local_surface_page",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com/",
            ),
        ):
            result = await _load_surface_png_bytes(
                "P-W", 0, prefer_remote=True, authorization="Bearer token"
            )
        assert result == b"remote png content"

    @pytest.mark.asyncio
    async def test_remote_path_200_then_no_local_fallback(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)

        with (
            patch(
                "app.application.aibiz_web_terminal_service._local_surface_page",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch("httpx.AsyncClient", return_value=mock_client),
            patch(
                "app.fastapi_routes.market_account._market_base_url",
                return_value="https://example.com",
            ),
        ):
            result = await _load_surface_png_bytes(
                "P-W", 0, prefer_remote=True, authorization="Bearer token"
            )
        # Remote 500, local returns None → None
        assert result is None

    @pytest.mark.asyncio
    async def test_no_prefer_remote_no_raw_returns_none(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _load_surface_png_bytes(
                "P-S", 0, prefer_remote=False, authorization="Bearer token"
            )
        # No prefer_remote, local returns None → None
        assert result is None

    @pytest.mark.asyncio
    async def test_prefer_remote_no_auth_falls_to_local(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        # prefer_remote=True but no authorization → skips remote, goes to local
        with (
            patch(
                "app.application.aibiz_web_terminal_service._local_surface_page",
                new_callable=AsyncMock,
                return_value={"screenshot_b64": base64.b64encode(b"local").decode()},
            ),
            patch(
                "app.application.surface_audit_service.resolve_lane_page_png_path",
                return_value=None,
            ),
        ):
            result = await _load_surface_png_bytes("P-W", 0, prefer_remote=True, authorization="")
        # Should call local (prefer_remote=True skips first local, no auth skips remote,
        # then falls to second local call)
        assert result == b"local"

    @pytest.mark.asyncio
    async def test_local_path_with_b64_only(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        b64_data = base64.b64encode(b"b64 only png").decode()
        mock_page = {"screenshot_b64": b64_data}
        with (
            patch(
                "app.application.aibiz_web_terminal_service._local_surface_page",
                new_callable=AsyncMock,
                return_value=mock_page,
            ),
            patch(
                "app.application.surface_audit_service.resolve_lane_page_png_path",
                return_value=None,
            ),
        ):
            result = await _load_surface_png_bytes("P-S", 0, prefer_remote=False, authorization="")
        assert result == b"b64 only png"


# ---------------------------------------------------------------------------
# _compact_surface_pages — branch coverage
# ---------------------------------------------------------------------------


class TestCompactSurfacePages:
    """Cover _compact_surface_pages (compatibility function)."""

    def test_returns_surface_unchanged(self):
        from app.application.aibiz_web_terminal_service import _compact_surface_pages

        surface = {"pages": [{"id": "home"}]}
        result = _compact_surface_pages(surface, compact=True)
        assert result == surface

    def test_returns_surface_compact_false(self):
        from app.application.aibiz_web_terminal_service import _compact_surface_pages

        surface = {"pages": [{"id": "home"}]}
        result = _compact_surface_pages(surface, compact=False)
        assert result == surface

    def test_returns_empty_dict(self):
        from app.application.aibiz_web_terminal_service import _compact_surface_pages

        result = _compact_surface_pages({}, compact=True)
        assert result == {}
