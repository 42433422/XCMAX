from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.desktop_runtime.asset_install_scheduler import poll_asset_install_commands_once
from app.fastapi_routes.mod_store_routes import ModStoreInstallResult


@pytest.mark.asyncio
async def test_desktop_claims_installs_and_reports_paid_asset_command() -> None:
    async def proxy(method: str, path: str, **kwargs):
        if method == "GET":
            return {"items": [{"id": 12}]}
        if path.endswith("/claim"):
            return {
                "command": {
                    "asset": {
                        "pkg_id": "paid-mod",
                        "version": "1.2.3",
                        "sha256": "b" * 64,
                        "download_path": (
                            "/api/asset-installations/commands/12/download"
                            "?installation_id=desktop-installation-1"
                        ),
                    }
                }
            }
        assert path.endswith("/result")
        assert kwargs["json_body"]["status"] == "installed"
        return {"ok": True}

    install = AsyncMock(return_value=ModStoreInstallResult(success=True, message="installed", data={"id": "paid-mod"}))
    with (
        patch("app.desktop_runtime.paths.is_desktop_mode", return_value=True),
        patch("app.application.desktop_delivery_receipt.desktop_installation_id", return_value="desktop-installation-1"),
        patch("app.fastapi_routes.market_account.latest_session_market_token", return_value="market-token"),
        patch("app.fastapi_routes.market_account._proxy_json", new=proxy),
        patch("app.fastapi_routes.mod_store_routes._install_from_catalog", new=install),
    ):
        result = await poll_asset_install_commands_once()

    assert result["processed"] == 1
    assert result["outcomes"] == [{"command_id": 12, "status": "installed", "reported": True}]
    install.assert_awaited_once_with(
        "paid-mod",
        "1.2.3",
        activate=True,
        authorization="Bearer market-token",
        download_path=(
            "/api/asset-installations/commands/12/download"
            "?installation_id=desktop-installation-1"
        ),
        expected_sha256="b" * 64,
    )


@pytest.mark.asyncio
async def test_asset_install_poll_is_desktop_only() -> None:
    with patch("app.desktop_runtime.paths.is_desktop_mode", return_value=False):
        result = await poll_asset_install_commands_once()
    assert result == {"processed": 0, "reason": "not_desktop"}
