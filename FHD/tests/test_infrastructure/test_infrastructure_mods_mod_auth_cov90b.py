"""Second-wave real-behavior coverage for app/infrastructure/mods/mod_auth.py.

Targets previously-uncovered lines: signature verification branches in
ModContext.from_request, _normalize_mod_id / _generate_signature / _load_mod_permissions
helpers, can_access / is_verified, path inference with invalid id, the enterprise
entitlement gate (403 paths) and exception handling inside ModContextMiddleware, plus
get_mod_context / require_verified_mod dependencies.

All external deps (entitlements, mod_manager, signature secret) are patched; no DB,
network or filesystem access. Deterministic and offline.
"""

import asyncio

import pytest
from fastapi import HTTPException

import app.infrastructure.mods.mod_auth as mod_auth
from app.infrastructure.mods.mod_auth import (
    ModContext,
    ModContextMiddleware,
    get_mod_context,
    require_verified_mod,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class _FakeHeaders:
    """Mimics starlette Headers.get with case-insensitive lookup."""

    def __init__(self, data: dict[str, str]):
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, key, default=None):
        return self._data.get(key.lower(), default)


class _FakeRequest:
    def __init__(self, headers: dict[str, str]):
        self.headers = _FakeHeaders(headers)


class _FakeState:
    pass


class _StateRequest:
    """Minimal request exposing only .state for dependency helpers."""

    def __init__(self, state):
        self.state = state


def _build_scope(path: str, headers: list[tuple[bytes, bytes]] | None = None) -> dict:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }


async def _receive():
    return {"type": "http.request", "body": b"", "more_body": False}


def _run_middleware(middleware, scope):
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, _receive, send))
    return sent


# ---------------------------------------------------------------------------
# _normalize_mod_id  (lines 99-107)
# ---------------------------------------------------------------------------
def test_normalize_mod_id_empty_returns_none():
    assert ModContext._normalize_mod_id("") is None


def test_normalize_mod_id_invalid_chars_returns_none():
    # Leading punctuation / spaces fail the regex.
    assert ModContext._normalize_mod_id("  ") is None
    assert ModContext._normalize_mod_id("-bad-start") is None
    assert ModContext._normalize_mod_id("has space") is None


def test_normalize_mod_id_valid_passthrough_and_strip():
    assert ModContext._normalize_mod_id("  good-mod_1.x  ") == "good-mod_1.x"


# ---------------------------------------------------------------------------
# _generate_signature  (lines 112-116)
# ---------------------------------------------------------------------------
def test_generate_signature_empty_when_no_secret(monkeypatch):
    monkeypatch.setattr(mod_auth, "MOD_SIGNATURE_SECRET", "")
    assert ModContext._generate_signature("any-mod") == ""


def test_generate_signature_is_deterministic_32_hex(monkeypatch):
    monkeypatch.setattr(mod_auth, "MOD_SIGNATURE_SECRET", "topsecret")
    sig1 = ModContext._generate_signature("mod-a")
    sig2 = ModContext._generate_signature("mod-a")
    sig_other = ModContext._generate_signature("mod-b")
    assert sig1 == sig2
    assert len(sig1) == 32
    assert all(c in "0123456789abcdef" for c in sig1)
    assert sig1 != sig_other


# ---------------------------------------------------------------------------
# _load_mod_permissions  (line 124 admin branch)
# ---------------------------------------------------------------------------
def test_load_mod_permissions_default():
    perms = ModContext._load_mod_permissions("regular-mod")
    assert perms == ["read:products", "read:customers", "write:shipments"]
    assert "admin:*" not in perms


def test_load_mod_permissions_admin_branch():
    perms = ModContext._load_mod_permissions("admin-dashboard")
    assert "admin:*" in perms


# ---------------------------------------------------------------------------
# can_access  (lines 129-131) + is_verified (line 135)
# ---------------------------------------------------------------------------
def test_can_access_false_when_not_verified():
    ctx = ModContext(mod_id="m1", verified=False, permissions=["read:products"])
    assert ctx.can_access("read:products") is False
    assert ctx.is_verified() is False


def test_can_access_false_when_no_mod_id():
    ctx = ModContext(mod_id=None, verified=True, permissions=["read:products"])
    assert ctx.can_access("read:products") is False


def test_can_access_true_for_exact_permission():
    ctx = ModContext(mod_id="m1", verified=True, permissions=["read:products"])
    assert ctx.can_access("read:products") is True
    assert ctx.can_access("write:shipments") is False
    assert ctx.is_verified() is True


def test_can_access_true_via_admin_wildcard():
    ctx = ModContext(mod_id="m1", verified=True, permissions=["admin:*"])
    assert ctx.can_access("anything:at:all") is True


# ---------------------------------------------------------------------------
# from_request  (lines 65-66, 72-80)
# ---------------------------------------------------------------------------
def test_from_request_no_mod_id_returns_blank_ctx():
    ctx = ModContext.from_request(_FakeRequest({}))
    assert ctx.mod_id is None
    assert ctx.verified is False


def test_from_request_invalid_mod_id_format_returns_blank(caplog):
    # Bad format -> _normalize_mod_id None -> warning + return blank ctx (lines 64-66).
    ctx = ModContext.from_request(_FakeRequest({"X-XCAGI-Active-Mod-Id": "-illegal"}))
    assert ctx.mod_id is None
    assert ctx.verified is False


def test_from_request_with_secret_valid_signature_verifies(monkeypatch):
    monkeypatch.setattr(mod_auth, "MOD_SIGNATURE_SECRET", "s3cr3t")
    sig = ModContext._generate_signature("verified-mod")
    ctx = ModContext.from_request(
        _FakeRequest(
            {
                "X-XCAGI-Active-Mod-Id": "verified-mod",
                "X-XCAGI-Mod-Signature": sig,
            }
        )
    )
    assert ctx.mod_id == "verified-mod"
    assert ctx.verified is True
    # verified -> permissions + metadata populated (lines 89-92)
    assert ctx.permissions == ["read:products", "read:customers", "write:shipments"]
    assert ctx.metadata == {"source": "header", "verified_at": "now"}


def test_from_request_with_secret_bad_signature_not_verified(monkeypatch):
    # lines 74-78: compare_digest fails -> verified False + warning, no permissions.
    monkeypatch.setattr(mod_auth, "MOD_SIGNATURE_SECRET", "s3cr3t")
    ctx = ModContext.from_request(
        _FakeRequest(
            {
                "X-XCAGI-Active-Mod-Id": "tampered-mod",
                "X-XCAGI-Mod-Signature": "deadbeef" * 4,
            }
        )
    )
    assert ctx.mod_id == "tampered-mod"
    assert ctx.verified is False
    assert ctx.permissions == []


def test_from_request_with_secret_missing_signature_not_verified(monkeypatch):
    # line 80: secret configured but no signature header.
    monkeypatch.setattr(mod_auth, "MOD_SIGNATURE_SECRET", "s3cr3t")
    ctx = ModContext.from_request(_FakeRequest({"X-XCAGI-Active-Mod-Id": "unsigned-mod"}))
    assert ctx.mod_id == "unsigned-mod"
    assert ctx.verified is False


def test_from_request_dev_mode_accepts_without_signature(monkeypatch):
    # No secret -> dev mode -> verified True (lines 82-92).
    monkeypatch.setattr(mod_auth, "MOD_SIGNATURE_SECRET", "")
    ctx = ModContext.from_request(_FakeRequest({"X-XCAGI-Active-Mod-Id": "dev-mod"}))
    assert ctx.mod_id == "dev-mod"
    assert ctx.verified is True
    assert "read:products" in ctx.permissions


# ---------------------------------------------------------------------------
# _mod_context_from_path  (line 152 invalid id)
# ---------------------------------------------------------------------------
def test_mod_context_from_path_no_match_returns_blank():
    ctx = ModContextMiddleware._mod_context_from_path("/health")
    assert ctx.mod_id is None


def test_mod_context_from_path_valid():
    ctx = ModContextMiddleware._mod_context_from_path("/api/mod/my-mod/status")
    assert ctx.mod_id == "my-mod"
    assert ctx.verified is False
    assert ctx.metadata == {"source": "path"}


def test_mod_context_from_path_invalid_segment_returns_blank(monkeypatch):
    # Force the regex to match but normalize to fail, exercising line 151-152.
    captured = {}

    real_normalize = ModContext._normalize_mod_id

    def fake_normalize(value):
        captured["value"] = value
        return None

    monkeypatch.setattr(ModContext, "_normalize_mod_id", staticmethod(fake_normalize))
    try:
        ctx = ModContextMiddleware._mod_context_from_path("/api/mod/whatever/status")
    finally:
        monkeypatch.setattr(ModContext, "_normalize_mod_id", staticmethod(real_normalize))
    assert ctx.mod_id is None
    assert captured["value"] == "whatever"


# ---------------------------------------------------------------------------
# get_mod_context  (line 248)
# ---------------------------------------------------------------------------
def test_get_mod_context_missing_returns_blank():
    ctx = get_mod_context(_StateRequest(_FakeState()))
    assert isinstance(ctx, ModContext)
    assert ctx.mod_id is None


def test_get_mod_context_returns_existing():
    state = _FakeState()
    existing = ModContext(mod_id="present", verified=True)
    state.mod_context = existing
    assert get_mod_context(_StateRequest(state)) is existing


# ---------------------------------------------------------------------------
# require_verified_mod  (lines 253-259)
# ---------------------------------------------------------------------------
def test_require_verified_mod_raises_without_mod_id():
    state = _FakeState()
    state.mod_context = ModContext(mod_id=None, verified=False)
    with pytest.raises(HTTPException) as exc_info:
        require_verified_mod(_StateRequest(state))
    assert exc_info.value.status_code == 403


def test_require_verified_mod_raises_when_unverified():
    state = _FakeState()
    state.mod_context = ModContext(mod_id="m1", verified=False)
    with pytest.raises(HTTPException) as exc_info:
        require_verified_mod(_StateRequest(state))
    assert exc_info.value.status_code == 403


def test_require_verified_mod_returns_ctx_when_verified():
    state = _FakeState()
    ctx = ModContext(mod_id="m1", verified=True)
    state.mod_context = ctx
    assert require_verified_mod(_StateRequest(state)) is ctx


# ---------------------------------------------------------------------------
# Middleware enterprise entitlement gate + exception handling
# (lines 182-210, 220-226)
# ---------------------------------------------------------------------------
async def _ok_downstream(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


def test_middleware_non_http_scope_passthrough():
    seen = {}

    async def downstream(scope, receive, send):
        seen["called"] = scope["type"]

    middleware = ModContextMiddleware(downstream)
    asyncio.run(middleware({"type": "lifespan"}, _receive, lambda m: None))
    assert seen["called"] == "lifespan"


def test_middleware_entitlement_sync_path_ok(monkeypatch):
    """sid present + filter active -> sync_entitlements + visible mod -> 200 (lines 181-200,211-213)."""
    calls = {"sync": 0, "ensure": 0}

    async def fake_sync(session_id):
        calls["sync"] += 1
        calls["sid"] = session_id
        return set()

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.sync_entitlements_for_session",
        fake_sync,
    )
    monkeypatch.setattr("app.enterprise.mod_entitlements.is_client_mod_id", lambda mid: False)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mid: True,
    )

    def fake_ensure(mod_id, session_id=None):
        calls["ensure"] += 1

    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", fake_ensure)

    middleware = ModContextMiddleware(_ok_downstream)
    scope = _build_scope(
        "/api/mod/some-mod/status",
        headers=[(b"cookie", b"session_id=live-session")],
    )
    sent = _run_middleware(middleware, scope)

    assert calls["sync"] == 1
    assert calls["sid"] == "live-session"
    assert calls["ensure"] == 1
    assert sent[0]["status"] == 200


def test_middleware_mod_not_visible_returns_403(monkeypatch):
    """sid present + filter active + mod NOT visible -> 403 short-circuit (lines 200-210)."""

    async def fake_sync(session_id):
        return set()

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.sync_entitlements_for_session",
        fake_sync,
    )
    monkeypatch.setattr("app.enterprise.mod_entitlements.is_client_mod_id", lambda mid: True)
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.is_mod_visible_for_enterprise",
        lambda mid: False,
    )

    ensure_called = {"n": 0}

    def fake_ensure(mod_id, session_id=None):
        ensure_called["n"] += 1

    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", fake_ensure)

    middleware = ModContextMiddleware(_ok_downstream)
    scope = _build_scope(
        "/api/mod/blocked-mod/status",
        headers=[(b"cookie", b"session_id=live-session")],
    )
    sent = _run_middleware(middleware, scope)

    # 403 JSONResponse short-circuits; downstream never runs, so ensure not called.
    assert sent[0]["status"] == 403
    assert ensure_called["n"] == 0
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b"mod_not_entitled" in body


def test_middleware_filter_inactive_skips_entitlement_checks(monkeypatch):
    """filter inactive -> skip sync/visibility, still calls ensure_mod_api_ready (line 211-213)."""
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )

    sync_called = {"n": 0}

    async def fake_sync(session_id):
        sync_called["n"] += 1
        return set()

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.sync_entitlements_for_session",
        fake_sync,
    )

    ensure_called = {"n": 0}

    def fake_ensure(mod_id, session_id=None):
        ensure_called["n"] += 1

    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", fake_ensure)

    middleware = ModContextMiddleware(_ok_downstream)
    scope = _build_scope(
        "/api/mod/free-mod/status",
        headers=[(b"cookie", b"session_id=live-session")],
    )
    sent = _run_middleware(middleware, scope)

    assert sync_called["n"] == 0
    assert ensure_called["n"] == 1
    assert sent[0]["status"] == 200


def test_middleware_recoverable_error_is_swallowed(monkeypatch):
    """ensure_mod_api_ready raising a RECOVERABLE error -> warning, host stays 200 (lines 214-219)."""
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )

    recoverable_exc = RECOVERABLE_ERRORS[0]

    def fake_ensure(mod_id, session_id=None):
        raise recoverable_exc("boom-recoverable")

    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", fake_ensure)

    middleware = ModContextMiddleware(_ok_downstream)
    scope = _build_scope(
        "/api/mod/recover-mod/status",
        headers=[(b"cookie", b"session_id=live-session")],
    )
    sent = _run_middleware(middleware, scope)
    assert sent[0]["status"] == 200


def test_middleware_generic_exception_is_swallowed(monkeypatch):
    """A non-recoverable Exception in the bootstrap block -> generic except, host stays 200 (lines 220-226)."""
    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        lambda: False,
    )

    def fake_ensure(mod_id, session_id=None):
        raise RuntimeError("simulated generic bootstrap failure")

    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", fake_ensure)

    middleware = ModContextMiddleware(_ok_downstream)
    scope = _build_scope(
        "/api/mod/explode-mod/status",
        headers=[(b"cookie", b"session_id=live-session")],
    )
    sent = _run_middleware(middleware, scope)
    assert sent[0]["status"] == 200


def test_middleware_no_session_cookie_skips_entitlement_block(monkeypatch):
    """No session cookie -> the `if sid:` block is skipped, ensure still runs."""
    filter_called = {"n": 0}

    def fake_filter():
        filter_called["n"] += 1
        return True

    monkeypatch.setattr(
        "app.enterprise.mod_entitlements.enterprise_mod_filter_active",
        fake_filter,
    )

    ensure_called = {"n": 0, "sid": "unset"}

    def fake_ensure(mod_id, session_id=None):
        ensure_called["n"] += 1
        ensure_called["sid"] = session_id

    monkeypatch.setattr("app.infrastructure.mods.mod_manager.ensure_mod_api_ready", fake_ensure)

    middleware = ModContextMiddleware(_ok_downstream)
    scope = _build_scope("/api/mod/no-cookie-mod/status")
    sent = _run_middleware(middleware, scope)

    # entitlement filter is only evaluated inside `if sid:` -> never called here.
    assert filter_called["n"] == 0
    assert ensure_called["n"] == 1
    assert ensure_called["sid"] is None
    assert sent[0]["status"] == 200
