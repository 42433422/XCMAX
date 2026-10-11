"""Mod signatures, request scope and fail-closed authorization tests."""

from __future__ import annotations

import hashlib
import hmac
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from app.infrastructure.mods.mod_auth import (
    ModContext,
    ModContextMiddleware,
    get_mod_context,
    require_verified_mod,
)
from app.request_active_mod_ctx import get_request_active_mod_id


def _http_scope(path, headers=()):
    return {"type": "http", "method": "GET", "path": path, "headers": list(headers)}


class TestModContextMethods:
    @pytest.mark.parametrize(
        "kwargs", [{}, {"permissions": ["read:products"]}, {"metadata": {"source": "test"}}]
    )
    def test_initialization_preserves_fields(self, kwargs):
        ctx = ModContext(**kwargs)
        assert ctx.permissions == kwargs.get("permissions", [])
        assert ctx.metadata == kwargs.get("metadata", {})
        assert ctx.mod_id is None and ctx.verified is False

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("mod1", "mod1"),
            ("mod.test-v1_2", "mod.test-v1_2"),
            ("1mod", "1mod"),
            ("", None),
            (None, None),
            ("  mod1  ", "mod1"),
            (".mod1", None),
            ("-mod1", None),
            ("mod 1", None),
            ("mod@1", None),
            ("a" * 128, "a" * 128),
            ("a" * 129, None),
        ],
    )
    def test_normalization(self, raw, expected):
        assert ModContext._normalize_mod_id(raw) == expected

    @pytest.mark.parametrize("secret", ["", "test-secret-key"])
    def test_signature_matches_hmac(self, monkeypatch, secret):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", secret)
        expected = hmac.new(secret.encode(), b"mod1", hashlib.sha256).hexdigest()[:32]
        expected = expected if secret else ""
        sig = ModContext._generate_signature("mod1")
        assert sig == expected and len(sig) == (32 if secret else 0)

    @pytest.mark.parametrize("mid,admin", [("mod1", False), ("admin-mod", True)])
    def test_permissions(self, mid, admin):
        perms = ModContext._load_mod_permissions(mid)
        assert all(p in perms for p in ["read:products", "read:customers", "write:shipments"])
        assert ("admin:*" in perms) == admin

    @pytest.mark.parametrize(
        "mid,verified,permissions,resource,expected",
        [
            ("mod1", False, [], "read:products", False),
            (None, True, [], "read:products", False),
            ("mod1", True, ["read:products"], "read:products", True),
            ("mod1", True, ["read:products"], "write:products", False),
            ("admin-mod", True, ["admin:*"], "anything", True),
        ],
    )
    def test_permissions_gate(self, mid, verified, permissions, resource, expected):
        assert ModContext(mid, verified, permissions).can_access(resource) is expected

    @pytest.mark.parametrize("verified", [True, False])
    def test_verification_flag(self, verified):
        assert ModContext(verified=verified).is_verified() is verified


class TestFromRequest:
    @pytest.mark.parametrize(
        "mid,secret,sig,lower_mid,lower_sig,expected,verified",
        [
            (None, "", None, False, False, None, False),
            (".invalid", "", None, False, False, None, False),
            ("mod1", "", None, True, False, "mod1", True),
            ("mod1", "", None, False, False, "mod1", True),
            ("admin-mod", "", None, False, False, "admin-mod", True),
            ("mod1", "test-secret", "valid", False, False, "mod1", True),
            ("mod1", "secret", "badsig", False, False, "mod1", False),
            ("mod1", "secret", None, False, False, "mod1", False),
            ("mod1", "test-secret", "valid", False, True, "mod1", True),
        ],
    )
    def test_header_verification(
        self, monkeypatch, mid, secret, sig, lower_mid, lower_sig, expected, verified
    ):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", secret)
        headers = (
            {"x-xcagi-active-mod-id" if lower_mid else "X-XCAGI-Active-Mod-Id": mid} if mid else {}
        )
        if sig:
            headers["x-xcagi-mod-signature" if lower_sig else "X-XCAGI-Mod-Signature"] = (
                hmac.new(secret.encode(), mid.encode(), hashlib.sha256).hexdigest()[:32]
                if sig == "valid"
                else sig
            )
        request = MagicMock(spec=Request, headers=headers)
        ctx = ModContext.from_request(request)
        assert ctx.mod_id == expected and ctx.verified is verified
        if verified:
            base = ["read:products", "read:customers", "write:shipments"]
            assert ctx.permissions == base + (["admin:*"] if mid.startswith("admin") else [])
            assert ctx.metadata["source"] == "header"
        else:
            assert ctx.permissions == []


class TestModContextFromPath:
    @pytest.mark.parametrize(
        "path,mid",
        [
            ("/api/other", None),
            ("/api/mod/mymod/resource", "mymod"),
            ("/api/mod/mymod", "mymod"),
            ("/api/mod/.invalid", None),
            ("", None),
            (None, None),
        ],
    )
    def test_path_context(self, path, mid):
        ctx = ModContextMiddleware._mod_context_from_path(path)
        assert ctx.mod_id == mid and ctx.verified is False
        if mid:
            assert ctx.metadata["source"] == "path"


class TestRequestContext:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("scope_type", ["lifespan", "http"])
    async def test_without_mod_passes_through(self, scope_type):
        app = AsyncMock()
        scope = {"type": scope_type, "method": "GET", "path": "/api/other", "headers": []}
        await ModContextMiddleware(app)(scope, AsyncMock(), AsyncMock())
        app.assert_awaited_once()
        if scope_type == "http":
            assert scope["state"]["mod_context"].mod_id is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path,requires_http", [("/api/other", False), ("/api/mod/mod1/resource", True)]
    )
    @pytest.mark.parametrize("enterprise", [False, True])
    async def test_authorized_signed_cookie_request(
        self, monkeypatch, path, requires_http, enterprise
    ):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "test-secret")
        app = AsyncMock()
        scope = _http_scope(
            path,
            [
                (b"x-xcagi-active-mod-id", b"mod1"),
                (b"x-xcagi-mod-signature", ModContext._generate_signature("mod1").encode()),
                (b"cookie", b"session_id=A"),
            ],
        )
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
                return_value=enterprise,
            ),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise", return_value=True
            ),
            patch(
                "app.enterprise.mod_entitlements.sync_entitlements_for_session", new=AsyncMock()
            ) as sync,
            patch(
                "app.infrastructure.mods.mod_manager.ensure_mod_api_ready", return_value=True
            ) as ready,
        ):
            await ModContextMiddleware(app)(scope, AsyncMock(), AsyncMock())
        app.assert_awaited_once()
        assert scope["state"]["mod_context"].verified
        ready.assert_called_once_with("mod1", session_id="A", requires_http=requires_http)
        assert sync.await_count == int(enterprise)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure", [RuntimeError("recoverable"), ValueError("unexpected"), None]
    )
    async def test_mod_bootstrap_failure_stops_dispatch(self, monkeypatch, failure):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")
        app, send = AsyncMock(), AsyncMock()
        scope = {"type": "http", "method": "GET", "path": "/api/mod/mymod/resource", "headers": []}
        with patch(
            "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
            side_effect=failure,
            return_value=False,
        ):
            await ModContextMiddleware(app)(scope, AsyncMock(), send)
        app.assert_not_called()
        assert send.call_args_list[0].args[0]["status"] == 503

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sid,allowed,status,mid",
        [
            ("A", True, 204, "private-A"),
            ("B", False, 403, "private-A"),
            ("B", None, 503, "private-A"),
            ("", False, 403, "private-A"),
            ("", True, 403, "private-A"),
            ("", True, 204, "coating-industry"),
        ],
    )
    async def test_entitlement_scope_denial_and_failure(
        self, monkeypatch, sid, allowed, status, mid
    ):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")
        app, send = AsyncMock(), AsyncMock()
        scope = _http_scope(f"/api/mod/{mid}/probe", [(b"cookie", f"session_id={sid}".encode())])
        with (
            patch(
                "app.enterprise.mod_entitlements.enterprise_mod_filter_active", return_value=True
            ),
            patch("app.enterprise.mod_entitlements.is_client_mod_id", return_value=True),
            patch("app.enterprise.mod_entitlements.sync_entitlements_for_session", new=AsyncMock()),
            patch(
                "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
                return_value=allowed,
                side_effect=RuntimeError("unavailable") if allowed is None else None,
            ),
            patch("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", return_value=True),
        ):
            await ModContextMiddleware(app)(scope, AsyncMock(), send)
        if status == 204:
            app.assert_awaited_once()
        else:
            app.assert_not_called()
            assert send.call_args_list[0].args[0]["status"] == status

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure", [ValueError("parse"), TypeError("type"), RuntimeError("runtime")]
    )
    async def test_mod_context_parsing_error_preserves_host_request(self, failure):
        app = AsyncMock()
        scope = {"type": "http", "method": "GET", "path": "/api/other", "headers": []}
        with patch.object(ModContext, "from_request", side_effect=failure):
            await ModContextMiddleware(app)(scope, AsyncMock(), AsyncMock())
        app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_app_exception_still_resets_token(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")
        before = get_request_active_mod_id()
        app = AsyncMock(side_effect=RuntimeError("app failed"))
        scope = {"type": "http", "method": "GET", "path": "/api/mod/mymod/resource", "headers": []}
        with (
            patch("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", return_value=True),
            pytest.raises(RuntimeError, match="app failed"),
        ):
            await ModContextMiddleware(app)(scope, AsyncMock(), AsyncMock())
        app.assert_awaited_once()
        assert get_request_active_mod_id() == before

    @pytest.mark.parametrize("existing", [True, False])
    def test_context_or_default(self, existing):
        request = MagicMock(spec=Request)
        ctx = ModContext(mod_id="mod1", verified=True)
        if existing:
            request.state.mod_context = ctx
            assert get_mod_context(request) is ctx
        else:
            del request.state.mod_context
            result = get_mod_context(request)
            assert result.mod_id is None and result.verified is False

    @pytest.mark.parametrize("mid,verified", [(None, False), ("mod1", False), ("mod1", True)])
    def test_verified_dependency(self, mid, verified):
        request = MagicMock(spec=Request)
        ctx = ModContext(mod_id=mid, verified=verified)
        request.state.mod_context = ctx
        if verified:
            assert require_verified_mod(request) is ctx
        else:
            with pytest.raises(HTTPException) as exc_info:
                require_verified_mod(request)
            assert exc_info.value.status_code == 403
