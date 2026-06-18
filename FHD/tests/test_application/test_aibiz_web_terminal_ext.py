"""Tests for app.application.aibiz_web_terminal_service — coverage ramp for uncovered branches."""

from __future__ import annotations

import os
from datetime import date
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.application.aibiz_web_terminal_service import (
    _LANE_BY_TERMINAL,
    _compact_surface_pages,
    _crop_png_top,
    _load_local_lane_surface,
    _local_lane_pages,
    _local_surface_page,
    _png_http_response,
    _resize_png_thumb,
    _resolve_market_authorization,
    _sanitize_pw_admin_pages,
    _strip_b64_attach_image_urls,
    _surface_cache_token,
    _surface_image_url,
    _transform_png_view,
    _unwrap,
    build_terminal_payload,
    fetch_surface_page_payload,
    serve_surface_image,
)

# ========================= _png_http_response ============================


class TestPngHttpResponse:
    def test_basic(self):
        resp = _png_http_response(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        assert resp.media_type == "image/png"
        assert "max-age=86400" in resp.headers.get("Cache-Control", "")

    def test_viewport(self):
        resp = _png_http_response(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, view="viewport")
        assert resp.media_type == "image/png"

    def test_thumb(self):
        resp = _png_http_response(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, view="thumb")
        assert resp.media_type == "image/png"

    def test_no_cache_for_unknown_view(self):
        resp = _png_http_response(b"data", view="unknown")
        assert "no-cache" in resp.headers.get("Cache-Control", "")


# ========================= _strip_b64_attach_image_urls - extended ========


class TestStripB64AttachImageUrlsExtended:
    def test_web_home_hero(self):
        surface = {
            "pages": [
                {"id": "home", "name": "首页", "preview": True, "screenshot_b64": "abc"},
                {"id": "about", "name": "关于"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["pages"][0].get("preview") is True
        assert "preview_image_url" in result["pages"][0]

    def test_software_chat_hero(self):
        surface = {
            "pages": [
                {"id": "admin_dashboard", "name": "管理端"},
                {"id": "chat", "name": "智能对话"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        hero = [p for p in result["pages"] if p.get("preview")][0]
        assert hero["id"] == "chat"

    def test_software_home_hub_hero(self):
        surface = {
            "pages": [
                {"id": "other", "name": "其他"},
                {"id": "home_hub", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        hero = [p for p in result["pages"] if p.get("preview")][0]
        assert hero["id"] == "home_hub"

    def test_web_mod_admin_hero(self):
        surface = {
            "pages": [
                {"id": "mod_settings", "name": "MOD设置"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["pages"][0].get("preview") is True

    def test_web_home_name_hero(self):
        surface = {
            "pages": [
                {"id": "landing", "name": "官网首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["pages"][0].get("preview") is True

    def test_web_home_english_hero(self):
        surface = {
            "pages": [
                {"id": "landing", "name": "Home"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["pages"][0].get("preview") is True

    def test_app_workbench_hero(self):
        surface = {
            "pages": [
                {"id": "other", "name": "其他"},
                {"id": "workbench", "name": "工作台"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        hero = [p for p in result["pages"] if p.get("preview")][0]
        assert hero["id"] == "workbench"

    def test_app_chat_hero(self):
        surface = {
            "pages": [
                {"id": "other", "name": "其他"},
                {"id": "chat", "name": "对话"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        hero = [p for p in result["pages"] if p.get("preview")][0]
        assert hero["id"] == "chat"

    def test_app_erp_overview_hero(self):
        surface = {
            "pages": [
                {"id": "other", "name": "其他"},
                {"id": "erp_overview", "name": "ERP概览"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        hero = [p for p in result["pages"] if p.get("preview")][0]
        assert hero["id"] == "erp_overview"

    def test_non_dict_page_skipped(self):
        surface = {
            "pages": [
                "not a dict",
                {"id": "home", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert len(result["pages"]) == 2
        assert result["pages"][0] == "not a dict"

    def test_preview_index_set(self):
        surface = {
            "pages": [
                {"id": "home", "name": "首页", "preview": True},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 0


# ========================= _sanitize_pw_admin_pages - extended ===========


class TestSanitizePwAdminPagesExtended:
    def test_admin_page_with_url_pattern(self):
        surface = {
            "pages": [
                {
                    "id": "admin",
                    "name": "管理端",
                    "url": "/market/admin/dashboard",
                    "error": "locked",
                    "status": 401,
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 0

    def test_admin_page_with_name_prefix(self):
        surface = {
            "pages": [
                {
                    "id": "admin2",
                    "name": "管理端设置",
                    "error": "locked",
                    "status": 401,
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 0

    def test_admin_page_ok_with_image(self):
        surface = {
            "pages": [
                {
                    "id": "admin",
                    "name": "管理端",
                    "admin": True,
                    "status": 200,
                    "image_url": "/api/image.png",
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 1

    def test_non_list_pages(self):
        surface = {"pages": "not a list"}
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert result == surface

    def test_all_kept_no_filtering(self):
        surface = {
            "pages": [
                {"id": "home", "name": "首页", "status": 200, "screenshot_saved": "/tmp/a.png"},
                {
                    "id": "admin",
                    "name": "管理端",
                    "admin": True,
                    "digest_unlock_ok": True,
                    "status": 200,
                    "screenshot_saved": "/tmp/b.png",
                },
            ]
        }
        result = _sanitize_pw_admin_pages("P-W", surface)
        assert len(result["pages"]) == 2
        assert "page_count" not in result  # no filtering happened


# ========================= _resolve_market_authorization =================


class TestResolveMarketAuthorization:
    @pytest.mark.asyncio
    async def test_no_session_no_creds(self):
        from fastapi import Request

        mock_request = Mock(spec=Request)
        with patch(
            "app.application.aibiz_web_terminal_service.session_id_from_request",
            return_value=None,
            create=True,
        ):
            with patch(
                "app.fastapi_routes.market_account.session_id_from_request",
                return_value=None,
            ):
                with patch(
                    "app.fastapi_routes.market_account._authorization_from_request",
                    return_value=None,
                ):
                    with patch.dict(os.environ, {}, clear=False):
                        os.environ.pop("XCAGI_AIBIZ_MARKET_USER", None)
                        os.environ.pop("XCAGI_AIBIZ_MARKET_PASSWORD", None)
                        os.environ.pop("MODSTORE_DIGEST_ADMIN_USER", None)
                        os.environ.pop("MODSTORE_DIGEST_ADMIN_PASSWORD", None)
                        with patch(
                            "app.application.aibiz_web_terminal_service.login_market_with_password",
                            return_value={"success": False},
                            create=True,
                        ):
                            with patch(
                                "app.fastapi_routes.market_account.login_market_with_password",
                                return_value={"success": False},
                            ):
                                result = await _resolve_market_authorization(mock_request)
        assert result == ""

    @pytest.mark.asyncio
    async def test_with_session_auth(self):
        from fastapi import Request

        mock_request = Mock(spec=Request)
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="session123",
        ):
            with patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value="Bearer token123",
            ):
                result = await _resolve_market_authorization(mock_request)
        assert result == "Bearer token123"

    @pytest.mark.asyncio
    async def test_with_env_creds(self):
        from fastapi import Request

        mock_request = Mock(spec=Request)
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value=None,
        ):
            with patch(
                "app.fastapi_routes.market_account._authorization_from_request",
                return_value=None,
            ):
                with patch.dict(
                    os.environ,
                    {
                        "XCAGI_AIBIZ_MARKET_USER": "testuser",
                        "XCAGI_AIBIZ_MARKET_PASSWORD": "testpass",
                    },
                ):
                    with patch(
                        "app.fastapi_routes.market_account.login_market_with_password",
                        return_value={"success": True, "token": "env_token"},
                    ):
                        result = await _resolve_market_authorization(mock_request)
        assert result == "env_token"

    @pytest.mark.asyncio
    async def test_import_error(self):
        from fastapi import Request

        mock_request = Mock(spec=Request)
        # When the import of app.fastapi_routes.market_account fails,
        # _resolve_market_authorization catches it as RECOVERABLE_ERRORS
        # and raises RuntimeError
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XCAGI_AIBIZ_MARKET_USER", None)
            os.environ.pop("XCAGI_AIBIZ_MARKET_PASSWORD", None)
            os.environ.pop("MODSTORE_DIGEST_ADMIN_USER", None)
            os.environ.pop("MODSTORE_DIGEST_ADMIN_PASSWORD", None)
            with patch(
                "app.application.aibiz_web_terminal_service.RECOVERABLE_ERRORS",
                (ImportError, ModuleNotFoundError),
            ):
                # The function does: from app.fastapi_routes.market_account import ...
                # If that raises ImportError, it catches RECOVERABLE_ERRORS and raises RuntimeError
                with patch.dict("sys.modules", {"app.fastapi_routes.market_account": None}):
                    with pytest.raises(RuntimeError, match="market proxy unavailable"):
                        await _resolve_market_authorization(mock_request)


# ========================= _local_surface_page ===========================


class TestLocalSurfacePage:
    @pytest.mark.asyncio
    async def test_valid_index(self):
        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            return_value=[{"id": "home"}, {"id": "about"}],
        ):
            result = await _local_surface_page("P-W", 0)
        assert result == {"id": "home"}

    @pytest.mark.asyncio
    async def test_invalid_index(self):
        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            return_value=[{"id": "home"}],
        ):
            result = await _local_surface_page("P-W", 5)
        assert result is None

    @pytest.mark.asyncio
    async def test_negative_index(self):
        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            return_value=[{"id": "home"}],
        ):
            result = await _local_surface_page("P-W", -1)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_dict_page(self):
        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            return_value=["not a dict"],
        ):
            result = await _local_surface_page("P-W", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            side_effect=RuntimeError("fail"),
        ):
            result = await _local_surface_page("P-W", 0)
        assert result is None


# ========================= _load_local_lane_surface ======================


class TestLoadLocalLaneSurface:
    def test_basic(self):
        with patch(
            "app.application.aibiz_web_terminal_service.run_surface_audit_lane",
            return_value={"pages": [{"id": "home"}], "cached_at": "2026-01-01"},
            create=True,
        ):
            with patch(
                "app.application.surface_audit_service.run_surface_audit_lane",
                return_value={"pages": [{"id": "home"}], "cached_at": "2026-01-01"},
            ):
                result = _load_local_lane_surface("P-W")
        assert "pages" in result

    def test_caching(self):
        # First call populates cache
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value={"pages": [{"id": "home"}], "cached_at": "2026-01-01"},
        ):
            _load_local_lane_surface("P-W-test-cache")
        # Second call should use cache
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value={"pages": [{"id": "home"}], "cached_at": "2026-01-01"},
        ):
            result = _load_local_lane_surface("P-W-test-cache")
        assert "pages" in result


# ========================= _surface_cache_token - extended ================


class TestSurfaceCacheTokenExtended:
    def test_with_whitespace(self):
        surface = {"captured_at": "  2026-06-14T10:30:00.000Z  "}
        token = _surface_cache_token(surface)
        assert len(token) > 0

    def test_with_none_captured_at(self):
        surface = {"captured_at": None}
        token = _surface_cache_token(surface)
        assert token == date.today().isoformat().replace("-", "")


# ========================= _crop_png_top - extended ======================


class TestCropPngTopExtended:
    def test_with_valid_png(self):
        # Create a minimal valid PNG
        try:
            import io

            from PIL import Image

            img = Image.new("RGB", (100, 200), color="red")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            result = _crop_png_top(png_bytes, height=50)
            assert isinstance(result, bytes)
            assert len(result) > 0
        except ImportError:
            pytest.skip("PIL not available")

    def test_with_small_png(self):
        try:
            import io

            from PIL import Image

            img = Image.new("RGB", (100, 50), color="blue")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            result = _crop_png_top(png_bytes, height=200)
            # Image is smaller than crop height, should return original
            assert result == png_bytes
        except ImportError:
            pytest.skip("PIL not available")


# ========================= _resize_png_thumb - extended ==================


class TestResizePngThumbExtended:
    def test_with_wide_png(self):
        try:
            import io

            from PIL import Image

            img = Image.new("RGB", (200, 100), color="green")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            result = _resize_png_thumb(png_bytes, max_width=96)
            assert isinstance(result, bytes)
            assert len(result) > 0
        except ImportError:
            pytest.skip("PIL not available")

    def test_with_narrow_png(self):
        try:
            import io

            from PIL import Image

            img = Image.new("RGB", (50, 100), color="yellow")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
            result = _resize_png_thumb(png_bytes, max_width=96)
            # Image is narrower than max_width, should return re-saved PNG
            assert isinstance(result, bytes)
        except ImportError:
            pytest.skip("PIL not available")
