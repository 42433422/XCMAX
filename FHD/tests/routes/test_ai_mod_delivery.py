from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.fastapi_routes.mod_store_routes as routes


def _request() -> MagicMock:
    request = MagicMock()
    request.headers = {}
    return request


@pytest.mark.asyncio
async def test_ai_mod_delivery_starts_existing_authenticated_workbench() -> None:
    with (
        patch("app.fastapi_routes.market_account.session_id_from_request", return_value="sid-1"),
        patch(
            "app.fastapi_routes.market_account._authorization_from_request",
            return_value="Bearer market-token",
        ),
        patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(return_value={"session_id": "wb-1", "status": "running"}),
        ) as proxy,
    ):
        result = await routes.ai_mod_delivery_start(
            _request(),
            routes.AiModDeliveryStartBody(brief="帮我做一个请假审批流"),
        )

    assert result.success is True
    assert result.data == {"session_id": "wb-1", "status": "running"}
    sent = proxy.await_args.kwargs["json_body"]
    assert sent["intent"] == "mod"
    assert sent["generate_full_suite"] is True
    assert sent["generate_frontend"] is True


@pytest.mark.asyncio
async def test_ai_mod_delivery_installs_only_completed_valid_owned_export() -> None:
    snapshot = {
        "status": "done",
        "artifact": {"mod_id": "leave-approval", "validation_summary": {"ok": True}},
    }
    installed = routes.ModStoreInstallResult(
        success=True, message="installed", data={"id": "leave-approval"}
    )
    with (
        patch("app.fastapi_routes.market_account.session_id_from_request", return_value="sid-1"),
        patch(
            "app.fastapi_routes.market_account._authorization_from_request",
            return_value="Bearer market-token",
        ),
        patch(
            "app.fastapi_routes.market_account._proxy_json", new=AsyncMock(return_value=snapshot)
        ),
        patch.object(
            routes, "_install_from_catalog", new=AsyncMock(return_value=installed)
        ) as install,
    ):
        result = await routes.ai_mod_delivery_install(_request(), "wb-1")

    assert result.success is True
    install.assert_awaited_once_with(
        "leave-approval",
        "",
        activate=True,
        authorization="Bearer market-token",
        download_path="/v1/mod-sync/export-zip/leave-approval",
        verify_signature=False,
    )


@pytest.mark.asyncio
async def test_ai_mod_delivery_blocks_failed_validation() -> None:
    snapshot = {
        "status": "done",
        "artifact": {"mod_id": "unsafe", "validation_summary": {"ok": False}},
    }
    with (
        patch("app.fastapi_routes.market_account.session_id_from_request", return_value="sid-1"),
        patch(
            "app.fastapi_routes.market_account._authorization_from_request",
            return_value="Bearer market-token",
        ),
        patch(
            "app.fastapi_routes.market_account._proxy_json", new=AsyncMock(return_value=snapshot)
        ),
    ):
        with pytest.raises(routes.HTTPException, match="质量校验未通过"):
            await routes.ai_mod_delivery_install(_request(), "wb-2")


@pytest.mark.asyncio
async def test_ai_mod_delivery_blocks_missing_validation_evidence() -> None:
    snapshot = {"status": "done", "artifact": {"mod_id": "unverified"}}
    with (
        patch("app.fastapi_routes.market_account.session_id_from_request", return_value="sid-1"),
        patch(
            "app.fastapi_routes.market_account._authorization_from_request",
            return_value="Bearer market-token",
        ),
        patch(
            "app.fastapi_routes.market_account._proxy_json", new=AsyncMock(return_value=snapshot)
        ),
    ):
        with pytest.raises(routes.HTTPException, match="质量校验未通过"):
            await routes.ai_mod_delivery_install(_request(), "wb-3")
