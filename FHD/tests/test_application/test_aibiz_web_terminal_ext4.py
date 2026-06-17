"""Tests for app.application.aibiz_web_terminal_service — extended coverage (ext4).

Focus: _resolve_market_authorization credential chain, _load_surface_png_bytes
remote/local paths, serve_surface_image error responses, build_terminal_payload
no-auth branch, fetch_surface_page_payload local/remote paths,
_resolve_surface_audit branches, _fetch_remote_surface_audit branches,
_local_surface_page, _local_lane_pages, _load_local_lane_surface.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# _resolve_market_authorization — credential chain
# ---------------------------------------------------------------------------


class TestResolveMarketAuthorization:
    """Cover _resolve_market_authorization credential chain branches."""

    @pytest.mark.asyncio
    async def test_session_id_with_auth_header(self):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        request = MagicMock()
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="session123",
        ), patch(
            "app.fastapi_routes.market_account._authorization_from_request",
            return_value="Bearer token123",
        ):
            result = await _resolve_market_authorization(request)
        assert result == "Bearer token123"

    @pytest.mark.asyncio
    async def test_env_credentials_success(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_username",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_password",
            return_value="",
        ), patch(
            "app.fastapi_routes.market_account.login_market_with_password",
            new_callable=AsyncMock,
            return_value={"success": True, "token": "env_token"},
        ):
            result = await _resolve_market_authorization(request)
        assert result == "env_token"

    @pytest.mark.asyncio
    async def test_env_credentials_login_failure(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_USER", "envuser")
        monkeypatch.setenv("XCAGI_AIBIZ_MARKET_PASSWORD", "envpass")
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_username",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_password",
            return_value="",
        ), patch(
            "app.fastapi_routes.market_account.login_market_with_password",
            new_callable=AsyncMock,
            return_value={"success": False},
        ):
            result = await _resolve_market_authorization(request)
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_empty(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_USER", raising=False)
        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_PASSWORD", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_username",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_password",
            return_value="",
        ):
            result = await _resolve_market_authorization(request)
        assert result == ""

    @pytest.mark.asyncio
    async def test_digest_credentials(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_USER", raising=False)
        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_PASSWORD", raising=False)
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_USER", "digest_user")
        monkeypatch.setenv("MODSTORE_DIGEST_ADMIN_PASSWORD", "digest_pass")

        request = MagicMock()
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_username",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_password",
            return_value="",
        ), patch(
            "app.fastapi_routes.market_account.login_market_with_password",
            new_callable=AsyncMock,
            return_value={"success": True, "token": "digest_token"},
        ):
            result = await _resolve_market_authorization(request)
        assert result == "digest_token"

    @pytest.mark.asyncio
    async def test_demo_credentials(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_USER", raising=False)
        monkeypatch.delenv("XCAGI_AIBIZ_MARKET_PASSWORD", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_USER", raising=False)
        monkeypatch.delenv("MODSTORE_DIGEST_ADMIN_PASSWORD", raising=False)

        request = MagicMock()
        with patch(
            "app.fastapi_routes.market_account.session_id_from_request",
            return_value="",
        ), patch(
            "app.application.surface_audit_demo_account.demo_username",
            return_value="demo_user",
        ), patch(
            "app.application.surface_audit_demo_account.demo_password",
            return_value="demo_pass",
        ), patch(
            "app.fastapi_routes.market_account.login_market_with_password",
            new_callable=AsyncMock,
            return_value={"success": True, "token": "demo_token"},
        ):
            result = await _resolve_market_authorization(request)
        assert result == "demo_token"

    @pytest.mark.asyncio
    async def test_import_error_raises_runtime_error(self):
        from app.application.aibiz_web_terminal_service import _resolve_market_authorization

        request = MagicMock()
        with patch.dict(
            "sys.modules",
            {"app.fastapi_routes.market_account": None},
        ):
            with pytest.raises(RuntimeError, match="market proxy unavailable"):
                await _resolve_market_authorization(request)


# ---------------------------------------------------------------------------
# _load_surface_png_bytes — local/remote paths
# ---------------------------------------------------------------------------


class TestLoadSurfacePngBytes:
    """Cover _load_surface_png_bytes local/remote paths."""

    @pytest.mark.asyncio
    async def test_local_path_with_screenshot_saved(self, tmp_path: Path):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        png_file = tmp_path / "screenshot.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n")

        mock_page = {"screenshot_saved": str(png_file)}
        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=mock_page,
        ):
            result = await _load_surface_png_bytes(
                "P-S", 0, prefer_remote=False, authorization=""
            )
        assert result == b"\x89PNG\r\n\x1a\n"

    @pytest.mark.asyncio
    async def test_local_path_with_android_capture(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        import base64

        b64_data = base64.b64encode(b"android screenshot").decode()
        mock_page = {"android_capture": True, "screenshot_b64": b64_data}
        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=mock_page,
        ):
            result = await _load_surface_png_bytes(
                "P-App", 0, prefer_remote=False, authorization=""
            )
        assert result == b"android screenshot"

    @pytest.mark.asyncio
    async def test_local_path_with_resolved_png_path(self, tmp_path: Path):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        png_file = tmp_path / "resolved.png"
        png_file.write_bytes(b"resolved png")

        mock_page = {"id": "home"}
        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=mock_page,
        ), patch(
            "app.application.surface_audit_service.resolve_lane_page_png_path",
            return_value=png_file,
        ):
            result = await _load_surface_png_bytes(
                "P-S", 0, prefer_remote=False, authorization=""
            )
        assert result == b"resolved png"

    @pytest.mark.asyncio
    async def test_local_path_with_b64_fallback(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        import base64

        b64_data = base64.b64encode(b"fallback png").decode()
        mock_page = {"screenshot_b64": b64_data}
        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=mock_page,
        ), patch(
            "app.application.surface_audit_service.resolve_lane_page_png_path",
            return_value=None,
        ):
            result = await _load_surface_png_bytes(
                "P-S", 0, prefer_remote=False, authorization=""
            )
        assert result == b"fallback png"

    @pytest.mark.asyncio
    async def test_local_path_none_page(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _load_surface_png_bytes(
                "P-S", 0, prefer_remote=False, authorization=""
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_remote_path_success(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"remote png"

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=None,
        ), patch("httpx.AsyncClient", return_value=mock_client), patch(
            "app.fastapi_routes.market_account._market_base_url",
            return_value="https://example.com",
        ):
            result = await _load_surface_png_bytes(
                "P-W", 0, prefer_remote=True, authorization="Bearer token"
            )
        assert result == b"remote png"

    @pytest.mark.asyncio
    async def test_remote_path_non_200_falls_back_to_local(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=None,
        ), patch("httpx.AsyncClient", return_value=mock_client), patch(
            "app.fastapi_routes.market_account._market_base_url",
            return_value="https://example.com",
        ):
            result = await _load_surface_png_bytes(
                "P-W", 0, prefer_remote=True, authorization="Bearer token"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_authorization_skips_remote(self):
        from app.application.aibiz_web_terminal_service import _load_surface_png_bytes

        with patch(
            "app.application.aibiz_web_terminal_service._local_surface_page",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _load_surface_png_bytes(
                "P-W", 0, prefer_remote=True, authorization=""
            )
        assert result is None


# ---------------------------------------------------------------------------
# serve_surface_image — error responses
# ---------------------------------------------------------------------------


class TestServeSurfaceImage:
    """Cover serve_surface_image error response branches."""

    @pytest.mark.asyncio
    async def test_runtime_error_returns_500(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            side_effect=RuntimeError("market proxy unavailable"),
        ):
            result = await serve_surface_image(request, terminal="web", index=0)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_no_auth_no_screenshot_returns_401(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await serve_surface_image(request, terminal="web", index=0)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_but_no_screenshot_returns_404(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await serve_surface_image(request, terminal="web", index=0)
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_success_returns_png_response(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image
        from fastapi.responses import Response

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
            new_callable=AsyncMock,
            return_value=b"\x89PNG\r\n\x1a\n",
        ):
            result = await serve_surface_image(
                request, terminal="web", index=0, view="thumb"
            )
        assert isinstance(result, Response)
        assert result.media_type == "image/png"

    @pytest.mark.asyncio
    async def test_unknown_terminal_defaults_to_web(self):
        from app.application.aibiz_web_terminal_service import serve_surface_image
        from fastapi.responses import Response

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.application.aibiz_web_terminal_service._load_surface_png_bytes",
            new_callable=AsyncMock,
            return_value=b"\x89PNG\r\n\x1a\n",
        ) as mock_load:
            result = await serve_surface_image(request, terminal="unknown", index=0)
        assert isinstance(result, Response)
        # Should default to P-W lane.
        call_args = mock_load.call_args[0]
        assert call_args[0] == "P-W"


# ---------------------------------------------------------------------------
# build_terminal_payload — no-auth branch
# ---------------------------------------------------------------------------


class TestBuildTerminalPayload:
    """Cover build_terminal_payload no-auth and auth branches."""

    @pytest.mark.asyncio
    async def test_no_auth_with_local_pages(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {"pages": [{"id": "home", "name": "首页"}]}
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.application.aibiz_web_terminal_service._resolve_surface_audit",
            new_callable=AsyncMock,
            return_value=(mock_surface, "local"),
        ), patch(
            "app.fastapi_routes.market_account._market_base_url",
            return_value="https://example.com",
        ):
            result = await build_terminal_payload(request, terminal="software")
        assert result["success"] is True
        assert "data" in result
        assert result["data"]["terminal"] == "software"

    @pytest.mark.asyncio
    async def test_no_auth_no_pages_returns_401(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.application.aibiz_web_terminal_service._resolve_surface_audit",
            new_callable=AsyncMock,
            return_value=({}, "no data"),
        ), patch(
            "app.fastapi_routes.market_account._market_base_url",
            return_value="https://example.com",
        ):
            result = await build_terminal_payload(request, terminal="web")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_with_auth_returns_success(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload

        request = MagicMock()
        mock_surface = {"pages": [{"id": "home"}]}
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.application.aibiz_web_terminal_service._resolve_surface_audit",
            new_callable=AsyncMock,
            return_value=(mock_surface, "remote"),
        ), patch(
            "app.fastapi_routes.market_account._market_base_url",
            return_value="https://example.com",
        ):
            result = await build_terminal_payload(request, terminal="web")
        assert result["success"] is True
        assert "data" in result

    @pytest.mark.asyncio
    async def test_market_proxy_unavailable_returns_500(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch.dict(
            "sys.modules", {"app.fastapi_routes.market_account": None}
        ):
            result = await build_terminal_payload(request, terminal="web")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_auth_runtime_error_returns_500(self):
        from app.application.aibiz_web_terminal_service import build_terminal_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ), patch(
            "app.fastapi_routes.market_account._market_base_url",
            return_value="https://example.com",
        ):
            result = await build_terminal_payload(request, terminal="web")
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# fetch_surface_page_payload — local/remote paths
# ---------------------------------------------------------------------------


class TestFetchSurfacePagePayload:
    """Cover fetch_surface_page_payload local/remote paths."""

    @pytest.mark.asyncio
    async def test_local_lane_index_out_of_range(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value={"pages": [{"id": "home"}]},
        ):
            result = await fetch_surface_page_payload(
                request, terminal="software", index=5
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_local_lane_success(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        mock_local = {
            "pages": [
                {"name": "Home", "url": "/", "status": 200, "title": "Home Page"},
            ]
        }
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            result = await fetch_surface_page_payload(
                request, terminal="software", index=0
            )
        assert result["success"] is True
        assert result["data"]["name"] == "Home"

    @pytest.mark.asyncio
    async def test_local_lane_recoverable_error(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="",
        ), patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            side_effect=RuntimeError("boom"),
        ):
            result = await fetch_surface_page_payload(
                request, terminal="software", index=0
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500

    @pytest.mark.asyncio
    async def test_remote_lane_success(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {"name": "Remote"}},
        ):
            result = await fetch_surface_page_payload(
                request, terminal="web", index=0
            )
        assert result["success"] is True
        assert result["data"]["name"] == "Remote"

    @pytest.mark.asyncio
    async def test_remote_lane_error_response(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        err_resp = JSONResponse({"error": "bad"}, status_code=500)
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value=err_resp,
        ):
            result = await fetch_surface_page_payload(
                request, terminal="web", index=0
            )
        # Should return the error response.
        assert isinstance(result, JSONResponse)

    @pytest.mark.asyncio
    async def test_remote_lane_no_success(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            return_value="Bearer token",
        ), patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "unavailable"},
        ):
            result = await fetch_surface_page_payload(
                request, terminal="web", index=0
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 502

    @pytest.mark.asyncio
    async def test_auth_runtime_error_returns_500(self):
        from app.application.aibiz_web_terminal_service import fetch_surface_page_payload
        from fastapi.responses import JSONResponse

        request = MagicMock()
        with patch(
            "app.application.aibiz_web_terminal_service._resolve_market_authorization",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await fetch_surface_page_payload(
                request, terminal="web", index=0
            )
        assert isinstance(result, JSONResponse)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# _resolve_surface_audit — branches
# ---------------------------------------------------------------------------


class TestResolveSurfaceAudit:
    """Cover _resolve_surface_audit branches."""

    @pytest.mark.asyncio
    async def test_remote_success_for_pw(self):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        mock_surface = {"pages": [{"id": "home"}]}
        with patch(
            "app.application.aibiz_web_terminal_service._fetch_remote_surface_audit",
            new_callable=AsyncMock,
            return_value=(mock_surface, "remote note"),
        ):
            surface, note = await _resolve_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "pages" in surface
        assert "remote note" in note or "MODstore" in note

    @pytest.mark.asyncio
    async def test_local_fallback_for_ps(self, monkeypatch):
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
        assert surface.get("pages") is not None
        assert isinstance(note, str)

    @pytest.mark.asyncio
    async def test_local_with_android_capture(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        mock_local = {
            "success": True,
            "pages": [
                {"id": "home", "android_capture": True},
                {"id": "settings"},
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

    @pytest.mark.asyncio
    async def test_local_recoverable_error(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "1")
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            side_effect=RuntimeError("boom"),
        ):
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        assert isinstance(note, str)
        assert "异常" in note or "boom" in note

    @pytest.mark.asyncio
    async def test_no_auth_no_pages_returns_hint(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "0")
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value={"success": False, "message": "no data"},
        ):
            surface, note = await _resolve_surface_audit(
                "P-W", refresh=False, authorization="", compact=True
            )
        assert "market 会话" in note or "XCAGI_AIBIZ_MARKET" in note

    @pytest.mark.asyncio
    async def test_local_disabled(self, monkeypatch):
        from app.application.aibiz_web_terminal_service import _resolve_surface_audit

        monkeypatch.setenv("XCAGI_SURFACE_AUDIT_LOCAL", "0")
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value={"success": True, "pages": [{"id": "home"}]},
        ) as mock_local:
            surface, note = await _resolve_surface_audit(
                "P-S", refresh=False, authorization="", compact=True
            )
        # Local should not be called when disabled.
        mock_local.assert_not_called()


# ---------------------------------------------------------------------------
# _fetch_remote_surface_audit — branches
# ---------------------------------------------------------------------------


class TestFetchRemoteSurfaceAudit:
    """Cover _fetch_remote_surface_audit branches."""

    @pytest.mark.asyncio
    async def test_success_with_data(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": True, "data": {"pages": [{"id": "home"}]}},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert surface.get("pages") is not None
        assert "MODstore" in note

    @pytest.mark.asyncio
    async def test_success_no_data(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": True, "data": None},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "尚未巡检" in note

    @pytest.mark.asyncio
    async def test_missing_route(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"missing_route": "/api/surface-audit", "hint": "not mounted"},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "not mounted" in note or "surface-audit" in note

    @pytest.mark.asyncio
    async def test_error_response_404(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit
        from fastapi.responses import JSONResponse

        err_resp = JSONResponse({"error": "not found"}, status_code=404)
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value=err_resp,
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "未部署" in note or "本地" in note

    @pytest.mark.asyncio
    async def test_error_response_500(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit
        from fastapi.responses import JSONResponse

        err_resp = JSONResponse({"error": "server error"}, status_code=500)
        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value=err_resp,
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "不可用" in note

    @pytest.mark.asyncio
    async def test_no_success_no_data(self):
        from app.application.aibiz_web_terminal_service import _fetch_remote_surface_audit

        with patch(
            "app.fastapi_routes.market_account._proxy_json",
            new_callable=AsyncMock,
            return_value={"success": False, "message": "custom error"},
        ):
            surface, note = await _fetch_remote_surface_audit(
                "P-W", refresh=False, authorization="Bearer token", compact=True
            )
        assert "custom error" in note


# ---------------------------------------------------------------------------
# _local_surface_page / _local_lane_pages / _load_local_lane_surface
# ---------------------------------------------------------------------------


class TestLocalSurfacePage:
    """Cover _local_surface_page, _local_lane_pages, _load_local_lane_surface."""

    @pytest.mark.asyncio
    async def test_local_surface_page_valid_index(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=[{"id": "home"}, {"id": "settings"}],
        ):
            result = await _local_surface_page("P-S", 0)
        assert result == {"id": "home"}

    @pytest.mark.asyncio
    async def test_local_surface_page_out_of_range(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=[{"id": "home"}],
        ):
            result = await _local_surface_page("P-S", 5)
        assert result is None

    @pytest.mark.asyncio
    async def test_local_surface_page_negative_index(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=[{"id": "home"}],
        ):
            result = await _local_surface_page("P-S", -1)
        assert result is None

    @pytest.mark.asyncio
    async def test_local_surface_page_non_dict_entry(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            return_value=["not a dict"],
        ):
            result = await _local_surface_page("P-S", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_local_surface_page_recoverable_error(self):
        from app.application.aibiz_web_terminal_service import _local_surface_page

        with patch(
            "app.application.aibiz_web_terminal_service._local_lane_pages",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await _local_surface_page("P-S", 0)
        assert result is None

    @pytest.mark.asyncio
    async def test_local_lane_pages_returns_list(self):
        from app.application.aibiz_web_terminal_service import _local_lane_pages

        mock_local = {"pages": [{"id": "home"}]}
        with patch(
            "app.application.aibiz_web_terminal_service._load_local_lane_surface",
            return_value=mock_local,
        ):
            result = await _local_lane_pages("P-S")
        assert isinstance(result, list)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_local_lane_pages_no_pages_key(self):
        from app.application.aibiz_web_terminal_service import _local_lane_pages

        with patch(
            "app.application.aibiz_web_terminal_service._load_local_lane_surface",
            return_value={"other": "data"},
        ):
            result = await _local_lane_pages("P-S")
        assert result == []

    def test_load_local_lane_surface_caches(self):
        from app.application.aibiz_web_terminal_service import (
            _load_local_lane_surface,
            _local_lane_pages_cache,
        )

        # Clear cache for this lane.
        _local_lane_pages_cache.pop("P-S", None)
        mock_local = {"pages": [{"id": "home"}], "cached_at": "2026-06-15T10:00:00Z"}
        with patch(
            "app.application.surface_audit_service.run_surface_audit_lane",
            return_value=mock_local,
        ):
            result1 = _load_local_lane_surface("P-S")
            result2 = _load_local_lane_surface("P-S")
        assert result1.get("pages") is not None
        # Second call should use cache.
        assert "P-S" in _local_lane_pages_cache


# ---------------------------------------------------------------------------
# _strip_b64_attach_image_urls — additional hero index branches
# ---------------------------------------------------------------------------


class TestStripB64AttachImageUrlsAdditional:
    """Cover additional _strip_b64_attach_image_urls hero index branches."""

    def test_software_terminal_chat_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "chat", "name": "智能对话"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        assert isinstance(result, dict)
        assert result["preview_index"] == 1

    def test_software_terminal_home_hub_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "home_hub", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="software")
        assert result["preview_index"] == 1

    def test_web_terminal_mod_admin_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "mod_something", "name": "MOD"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_web_terminal_home_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "home", "name": "官网首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert result["preview_index"] == 1

    def test_app_terminal_approval_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "approval", "name": "审批"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        assert result["preview_index"] == 1

    def test_app_terminal_erp_overview_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "erp_overview", "name": "ERP"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        assert result["preview_index"] == 1

    def test_app_terminal_chat_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "chat", "name": "聊天"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        assert result["preview_index"] == 1

    def test_app_terminal_workbench_hero(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                {"id": "other", "name": "Other"},
                {"id": "workbench", "name": "工作台"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="app")
        assert result["preview_index"] == 1

    def test_pages_with_non_dict_entries(self):
        from app.application.aibiz_web_terminal_service import _strip_b64_attach_image_urls

        surface = {
            "pages": [
                "not a dict",
                {"id": "home", "name": "首页"},
            ]
        }
        result = _strip_b64_attach_image_urls(surface, terminal="web")
        assert isinstance(result, dict)
        # Non-dict entries are preserved as-is.
        assert result["pages"][0] == "not a dict"
