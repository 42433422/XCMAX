from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.security.lan_cidr_guard import LanCidrGuard, _authenticated_public_admin, _scope_host
from app.security.lan_config import LanConfig, lan_guard_path_is_bypassed
from app.security.license_guard import LanLicenseGuard


def _cfg(*, enabled: bool = True, public_admin_hosts: tuple[str, ...] = ()) -> LanConfig:
    return LanConfig(
        enabled=enabled,
        allowed_cidrs=("10.0.0.0/8",),
        trusted_proxies=(),
        admin_host_ips=(),
        bypass_paths=(),
        license_secret="test-secret",
        token_ttl_seconds=3600,
        admin_bootstrap_key="",
        license_db_path=Path("/tmp/lan-test.db"),
        cookie_name="lan",
        cookie_secure=False,
        cookie_samesite="Lax",
        cookie_domain="",
        static_prefixes=(),
        public_admin_hosts=public_admin_hosts,
    )


def test_im_websocket_paths_are_fixed_lan_bypass() -> None:
    cfg = _cfg()
    assert lan_guard_path_is_bypassed("/ws/im", cfg)
    assert lan_guard_path_is_bypassed("/fhd-api/ws/im", cfg)
    assert lan_guard_path_is_bypassed("//fhd-api//ws//im?session_id=x", cfg)


def test_im_rest_paths_are_fixed_lan_bypass() -> None:
    cfg = _cfg()
    assert lan_guard_path_is_bypassed("/api/im/contacts", cfg)
    assert lan_guard_path_is_bypassed("/api/im/conversations/1/messages?limit=50", cfg)


def test_token_authenticated_autonomy_callback_is_fixed_lan_bypass() -> None:
    cfg = _cfg()
    assert lan_guard_path_is_bypassed("/api/ops/autonomy/github-approval", cfg)
    assert lan_guard_path_is_bypassed("/fhd-api/api/ops/autonomy/actions/pending", cfg)


def test_founder_cockpit_public_shell_and_admin_api_are_fixed_lan_bypass() -> None:
    cfg = _cfg()
    assert lan_guard_path_is_bypassed("/admin/founder-autonomy", cfg)
    assert lan_guard_path_is_bypassed("/admin/assets/js/index-hash.js", cfg)
    assert lan_guard_path_is_bypassed("/admin/vite.svg", cfg)
    assert lan_guard_path_is_bypassed("/api/xcmax/ops/founder-autonomy", cfg)


@pytest.mark.asyncio
async def test_cidr_guard_allows_im_websocket_handshake_path() -> None:
    app = AsyncMock()
    guard = LanCidrGuard(app)
    send = AsyncMock()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/fhd-api/ws/im",
        "headers": [],
        "client": ("8.8.8.8", 12345),
    }

    with patch("app.security.lan_cidr_guard.get_lan_config", return_value=_cfg()):
        await guard(scope, MagicMock(), send)

    app.assert_called_once()
    send.assert_not_called()


def test_scope_host_normalizes_port_and_case() -> None:
    assert _scope_host({"headers": [(b"host", b"WWW.XIU-CI.COM:443")]}) == "www.xiu-ci.com"


def test_public_admin_helper_requires_allowlisted_host_and_live_admin(monkeypatch) -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/xcmax/admin/deploy/check",
        "headers": [(b"host", b"www.xiu-ci.com"), (b"cookie", b"session_id=s-live")],
        "client": ("8.8.8.8", 12345),
    }
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.session_id_from_request",
        lambda request: "s-live",
    )
    monkeypatch.setattr(
        "app.infrastructure.auth.dependencies.resolve_session_user",
        lambda request: MagicMock(is_active=True),
    )
    monkeypatch.setattr(
        "app.application.session_account_meta.load_session_account_meta",
        lambda sid: {"account_kind": "admin", "market_is_admin": True},
    )

    assert _authenticated_public_admin(
        scope,
        _cfg(public_admin_hosts=("www.xiu-ci.com",)),
    )
    assert not _authenticated_public_admin(scope, _cfg(public_admin_hosts=()))


@pytest.mark.asyncio
async def test_cidr_guard_allows_live_admin_only_on_public_admin_host(monkeypatch) -> None:
    app = AsyncMock()
    guard = LanCidrGuard(app)
    send = AsyncMock()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/xcmax/admin/deploy/check",
        "headers": [(b"host", b"www.xiu-ci.com")],
        "client": ("8.8.8.8", 12345),
    }
    monkeypatch.setattr("app.security.lan_cidr_guard._authenticated_public_admin", lambda *_: True)

    with patch(
        "app.security.lan_cidr_guard.get_lan_config",
        return_value=_cfg(public_admin_hosts=("www.xiu-ci.com",)),
    ):
        await guard(scope, MagicMock(), send)

    app.assert_called_once()
    send.assert_not_called()
    assert scope["state"]["lan_public_admin_session"] is True
    assert scope["state"]["lan_is_admin"] is True


@pytest.mark.asyncio
async def test_license_guard_honors_cidr_validated_public_admin_session() -> None:
    app = AsyncMock()
    guard = LanLicenseGuard(app)
    send = AsyncMock()
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/xcmax/admin/deploy/check",
        "headers": [(b"host", b"www.xiu-ci.com")],
        "client": ("8.8.8.8", 12345),
        "state": {"lan_public_admin_session": True},
    }

    with patch(
        "app.security.license_guard.get_lan_config",
        return_value=_cfg(public_admin_hosts=("www.xiu-ci.com",)),
    ):
        await guard(scope, MagicMock(), send)

    app.assert_called_once()
    send.assert_not_called()
