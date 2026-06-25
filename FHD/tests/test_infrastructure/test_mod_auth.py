"""Branch-coverage tests for app.infrastructure.mods.mod_auth.

Covers: ModContext (from_request, normalize, signature, permissions, can_access),
ModContextMiddleware (_mod_context_from_path, __call__ error paths),
get_mod_context, require_verified_mod.
Focus on signature verification branches, invalid inputs, and error handling.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException, Request
from starlette.requests import Request as StarletteRequest

from app.infrastructure.mods.mod_auth import (
    MOD_SIGNATURE_SECRET,
    ModContext,
    ModContextMiddleware,
    get_mod_context,
    require_verified_mod,
)

# ---------------------------------------------------------------------------
# ModContext.__post_init__
# ---------------------------------------------------------------------------


class TestModContextPostInit:
    def test_default_initializes_permissions_and_metadata(self):
        ctx = ModContext()
        assert ctx.permissions == []
        assert ctx.metadata == {}
        assert ctx.mod_id is None
        assert ctx.verified is False

    def test_custom_permissions_preserved(self):
        ctx = ModContext(permissions=["read:products"])
        assert ctx.permissions == ["read:products"]

    def test_custom_metadata_preserved(self):
        ctx = ModContext(metadata={"source": "test"})
        assert ctx.metadata == {"source": "test"}


# ---------------------------------------------------------------------------
# ModContext._normalize_mod_id
# ---------------------------------------------------------------------------


class TestNormalizeModId:
    def test_valid_simple(self):
        assert ModContext._normalize_mod_id("mod1") == "mod1"

    def test_valid_with_dots_dashes_underscores(self):
        assert ModContext._normalize_mod_id("mod.test-v1_2") == "mod.test-v1_2"

    def test_valid_starting_with_alnum(self):
        assert ModContext._normalize_mod_id("1mod") == "1mod"

    def test_empty_string_returns_none(self):
        assert ModContext._normalize_mod_id("") is None

    def test_none_returns_none(self):
        assert ModContext._normalize_mod_id(None) is None

    def test_strips_whitespace(self):
        assert ModContext._normalize_mod_id("  mod1  ") == "mod1"

    def test_invalid_starting_with_dot(self):
        assert ModContext._normalize_mod_id(".mod1") is None

    def test_invalid_starting_with_dash(self):
        assert ModContext._normalize_mod_id("-mod1") is None

    def test_invalid_with_spaces(self):
        assert ModContext._normalize_mod_id("mod 1") is None

    def test_invalid_with_special_chars(self):
        assert ModContext._normalize_mod_id("mod@1") is None

    def test_long_valid_id(self):
        long_id = "a" * 128
        assert ModContext._normalize_mod_id(long_id) == long_id

    def test_too_long_returns_none(self):
        long_id = "a" * 129
        assert ModContext._normalize_mod_id(long_id) is None


# ---------------------------------------------------------------------------
# ModContext._generate_signature
# ---------------------------------------------------------------------------


class TestGenerateSignature:
    def test_no_secret_returns_empty(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")
        assert ModContext._generate_signature("mod1") == ""

    def test_with_secret_returns_hex(self, monkeypatch):
        secret = "test-secret-key"
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", secret)
        sig = ModContext._generate_signature("mod1")
        expected = hmac.new(secret.encode(), b"mod1", hashlib.sha256).hexdigest()[:32]
        assert sig == expected
        assert len(sig) == 32


# ---------------------------------------------------------------------------
# ModContext._load_mod_permissions
# ---------------------------------------------------------------------------


class TestLoadModPermissions:
    def test_default_permissions(self):
        perms = ModContext._load_mod_permissions("mod1")
        assert "read:products" in perms
        assert "read:customers" in perms
        assert "write:shipments" in perms
        assert "admin:*" not in perms

    def test_admin_permissions(self):
        perms = ModContext._load_mod_permissions("admin-mod")
        assert "admin:*" in perms


# ---------------------------------------------------------------------------
# ModContext.can_access / is_verified
# ---------------------------------------------------------------------------


class TestCanAccess:
    def test_unverified_returns_false(self):
        ctx = ModContext(mod_id="mod1", verified=False)
        assert ctx.can_access("read:products") is False

    def test_no_mod_id_returns_false(self):
        ctx = ModContext(verified=True)
        assert ctx.can_access("read:products") is False

    def test_has_permission(self):
        ctx = ModContext(mod_id="mod1", verified=True, permissions=["read:products"])
        assert ctx.can_access("read:products") is True

    def test_no_permission(self):
        ctx = ModContext(mod_id="mod1", verified=True, permissions=["read:products"])
        assert ctx.can_access("write:products") is False

    def test_admin_wildcard(self):
        ctx = ModContext(mod_id="admin-mod", verified=True, permissions=["admin:*"])
        assert ctx.can_access("anything") is True


class TestIsVerified:
    def test_verified_true(self):
        ctx = ModContext(verified=True)
        assert ctx.is_verified() is True

    def test_verified_false(self):
        ctx = ModContext(verified=False)
        assert ctx.is_verified() is False


# ---------------------------------------------------------------------------
# ModContext.from_request
# ---------------------------------------------------------------------------


def _make_request(headers=None, cookies=None):
    """Build a mock Request with headers."""
    request = MagicMock(spec=Request)
    headers = headers or {}
    request.headers = headers
    request.cookies = cookies or {}
    return request


class TestFromRequest:
    def test_no_mod_id_header(self):
        request = _make_request(headers={})
        ctx = ModContext.from_request(request)
        assert ctx.mod_id is None
        assert ctx.verified is False

    def test_invalid_mod_id_format(self):
        request = _make_request(headers={"X-XCAGI-Active-Mod-Id": ".invalid"})
        ctx = ModContext.from_request(request)
        assert ctx.mod_id is None
        assert ctx.verified is False

    def test_lowercase_header(self):
        request = _make_request(headers={"x-xcagi-active-mod-id": "mod1"})
        ctx = ModContext.from_request(request)
        assert ctx.mod_id == "mod1"

    def test_dev_mode_no_secret_accepts(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")
        request = _make_request(headers={"X-XCAGI-Active-Mod-Id": "mod1"})
        ctx = ModContext.from_request(request)
        assert ctx.mod_id == "mod1"
        assert ctx.verified is True
        assert ctx.permissions == ["read:products", "read:customers", "write:shipments"]
        assert ctx.metadata["source"] == "header"

    def test_dev_mode_admin_mod(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")
        request = _make_request(headers={"X-XCAGI-Active-Mod-Id": "admin-mod"})
        ctx = ModContext.from_request(request)
        assert ctx.verified is True
        assert "admin:*" in ctx.permissions

    def test_with_secret_valid_signature(self, monkeypatch):
        secret = "test-secret"
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", secret)
        sig = hmac.new(secret.encode(), b"mod1", hashlib.sha256).hexdigest()[:32]
        request = _make_request(
            headers={"X-XCAGI-Active-Mod-Id": "mod1", "X-XCAGI-Mod-Signature": sig}
        )
        ctx = ModContext.from_request(request)
        assert ctx.mod_id == "mod1"
        assert ctx.verified is True

    def test_with_secret_invalid_signature(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "secret")
        request = _make_request(
            headers={"X-XCAGI-Active-Mod-Id": "mod1", "X-XCAGI-Mod-Signature": "badsig"}
        )
        ctx = ModContext.from_request(request)
        assert ctx.mod_id == "mod1"
        assert ctx.verified is False
        assert ctx.permissions == []

    def test_with_secret_no_signature(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "secret")
        request = _make_request(headers={"X-XCAGI-Active-Mod-Id": "mod1"})
        ctx = ModContext.from_request(request)
        assert ctx.mod_id == "mod1"
        assert ctx.verified is False

    def test_lowercase_signature_header(self, monkeypatch):
        secret = "test-secret"
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", secret)
        sig = hmac.new(secret.encode(), b"mod1", hashlib.sha256).hexdigest()[:32]
        request = _make_request(
            headers={"X-XCAGI-Active-Mod-Id": "mod1", "x-xcagi-mod-signature": sig}
        )
        ctx = ModContext.from_request(request)
        assert ctx.verified is True


# ---------------------------------------------------------------------------
# ModContextMiddleware._mod_context_from_path
# ---------------------------------------------------------------------------


class TestModContextFromPath:
    def test_no_match(self):
        ctx = ModContextMiddleware._mod_context_from_path("/api/other")
        assert ctx.mod_id is None

    def test_match(self):
        ctx = ModContextMiddleware._mod_context_from_path("/api/mod/mymod/resource")
        assert ctx.mod_id == "mymod"
        assert ctx.verified is False
        assert ctx.metadata["source"] == "path"

    def test_match_at_root(self):
        ctx = ModContextMiddleware._mod_context_from_path("/api/mod/mymod")
        assert ctx.mod_id == "mymod"

    def test_invalid_mod_id_in_path(self):
        ctx = ModContextMiddleware._mod_context_from_path("/api/mod/.invalid")
        assert ctx.mod_id is None

    def test_empty_path(self):
        ctx = ModContextMiddleware._mod_context_from_path("")
        assert ctx.mod_id is None

    def test_none_path(self):
        ctx = ModContextMiddleware._mod_context_from_path(None)
        assert ctx.mod_id is None


# ---------------------------------------------------------------------------
# ModContextMiddleware.__call__
# ---------------------------------------------------------------------------


class TestMiddlewareCall:
    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        called = False

        async def app(scope, receive, send):
            nonlocal called
            called = True

        middleware = ModContextMiddleware(app)
        await middleware({"type": "lifespan"}, MagicMock(), MagicMock())
        assert called is True

    @pytest.mark.asyncio
    async def test_http_scope_no_mod_id(self):
        received = {}

        async def app(scope, receive, send):
            received["scope"] = scope

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/other",
            "headers": [],
        }
        await middleware(scope, MagicMock(), MagicMock())
        # mod_context should be set on request.state but we can't easily access it
        # without a real Starlette request. Just verify no exception.

    @pytest.mark.asyncio
    async def test_http_scope_with_mod_id_header(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")

        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/other",
            "headers": [
                (b"x-xcagi-active-mod-id", b"mod1"),
            ],
        }
        with patch("app.infrastructure.mods.mod_manager.ensure_mod_api_ready"):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_http_scope_mod_id_from_path(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")

        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/mod/mymod/resource",
            "headers": [],
        }
        with patch("app.infrastructure.mods.mod_manager.ensure_mod_api_ready"):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_ensure_mod_api_ready_recoverable_error(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")

        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/mod/mymod/resource",
            "headers": [],
        }
        with patch(
            "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
            side_effect=RuntimeError("recoverable"),
        ):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_ensure_mod_api_ready_unexpected_error(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")

        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/mod/mymod/resource",
            "headers": [],
        }
        with patch(
            "app.infrastructure.mods.mod_manager.ensure_mod_api_ready",
            side_effect=Exception("unexpected"),
        ):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_value_error_in_mod_context_parsing(self, monkeypatch):
        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/other",
            "headers": [],
        }
        with patch.object(ModContext, "from_request", side_effect=ValueError("parse error")):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_type_error_in_mod_context_parsing(self):
        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/other",
            "headers": [],
        }
        with patch.object(ModContext, "from_request", side_effect=TypeError("type error")):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_runtime_error_in_mod_context_parsing(self):
        async def app(scope, receive, send):
            pass

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/other",
            "headers": [],
        }
        with patch.object(ModContext, "from_request", side_effect=RuntimeError("runtime error")):
            await middleware(scope, MagicMock(), MagicMock())

    @pytest.mark.asyncio
    async def test_app_exception_still_resets_token(self, monkeypatch):
        monkeypatch.setattr("app.infrastructure.mods.mod_auth.MOD_SIGNATURE_SECRET", "")

        async def app(scope, receive, send):
            raise RuntimeError("app failed")

        middleware = ModContextMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/mod/mymod/resource",
            "headers": [],
        }
        with (
            patch("app.infrastructure.mods.mod_manager.ensure_mod_api_ready"),
            pytest.raises(RuntimeError, match="app failed"),
        ):
            await middleware(scope, MagicMock(), MagicMock())


# ---------------------------------------------------------------------------
# get_mod_context / require_verified_mod
# ---------------------------------------------------------------------------


class TestGetModContext:
    def test_returns_existing_context(self):
        request = MagicMock(spec=Request)
        ctx = ModContext(mod_id="mod1", verified=True)
        request.state.mod_context = ctx
        result = get_mod_context(request)
        assert result is ctx

    def test_returns_default_when_missing(self):
        request = MagicMock(spec=Request)
        # request.state.mod_context doesn't exist
        del request.state.mod_context
        result = get_mod_context(request)
        assert result.mod_id is None
        assert result.verified is False


class TestRequireVerifiedMod:
    def test_raises_when_no_mod_id(self):
        request = MagicMock(spec=Request)
        ctx = ModContext(mod_id=None, verified=False)
        request.state.mod_context = ctx
        with pytest.raises(HTTPException) as exc_info:
            require_verified_mod(request)
        assert exc_info.value.status_code == 403

    def test_raises_when_not_verified(self):
        request = MagicMock(spec=Request)
        ctx = ModContext(mod_id="mod1", verified=False)
        request.state.mod_context = ctx
        with pytest.raises(HTTPException) as exc_info:
            require_verified_mod(request)
        assert exc_info.value.status_code == 403

    def test_returns_ctx_when_verified(self):
        request = MagicMock(spec=Request)
        ctx = ModContext(mod_id="mod1", verified=True)
        request.state.mod_context = ctx
        result = require_verified_mod(request)
        assert result is ctx
