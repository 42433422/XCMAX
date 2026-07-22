from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.security.lan_cidr_guard import LanCidrGuard
from app.security.lan_config import LanConfig, lan_guard_path_is_bypassed


def _cfg(*, enabled: bool = True) -> LanConfig:
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
