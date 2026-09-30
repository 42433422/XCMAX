from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse

from app.application.desktop_delivery_receipt import (
    desktop_installation_id,
    report_desktop_login_delivery_receipt,
)


def test_desktop_installation_id_prefers_electron_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    (tmp_path / "installation-id").write_text(
        "37793b37f088431583f1b275f844d680\n", encoding="utf-8"
    )

    assert desktop_installation_id() == "37793b37f088431583f1b275f844d680"


@pytest.mark.asyncio
async def test_login_reports_idempotent_desktop_install_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("XCAGI_VERSION", "1.0.0.1")
    monkeypatch.setenv("XCAGI_BUILD_SHA", "build-sha")
    (tmp_path / "installation-id").write_text("external-device-00000001\n", encoding="utf-8")
    proxy = AsyncMock(return_value={"ok": True, "duplicate": False})
    monkeypatch.setattr("app.fastapi_routes.market_account._proxy_json", proxy)

    result = await report_desktop_login_delivery_receipt("market-token")

    assert result == {"reported": True, "duplicate": False, "source": "desktop_login"}
    _, path = proxy.call_args.args
    body = proxy.call_args.kwargs["json_body"]
    assert path == "/api/update-installations/receipts"
    assert proxy.call_args.kwargs["authorization"] == "market-token"
    assert body == {
        "installation_id": "external-device-00000001",
        "idempotency_key": body["idempotency_key"],
        "channel": "stable",
        "platform": body["platform"],
        "target_version": "1.0.0.1",
        "target_build_sha": "build-sha",
        "installed_version": "1.0.0.1",
        "installed_build_sha": "build-sha",
        "status": "installed",
        "error": "",
        "source": "desktop_login",
    }
    assert len(body["idempotency_key"]) == 64


@pytest.mark.asyncio
async def test_login_receipt_does_not_block_without_market_token():
    assert await report_desktop_login_delivery_receipt("") == {
        "reported": False,
        "reason": "missing_market_token",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("background", [False, True])
@pytest.mark.parametrize("denied", [False, True])
@pytest.mark.parametrize(
    "retry_error", [None, HTTPException(401, "unavailable"), ConnectionError("offline")]
)
async def test_desktop_login_finalize_reports_delivery_receipt(background, denied, retry_error):
    from app.application.enterprise_login_finalize import finalize_enterprise_login

    receipt = {"reported": True, "duplicate": False, "source": "desktop_login"}
    tasks = BackgroundTasks() if background else None
    flow = "app.application.enterprise_login_flow."
    market = "app.fastapi_routes.market_account."
    values = {
        market + "save_session_market_token": None,
        flow + "extract_market_user_blob": {"id": 29, "username": "SUNBIRD"},
        flow + "company_brand_from_user_blob": "SUNBIRD",
        flow + "bind_tenant_for_login": {"tenant_id": None, "tenant_name": "SUNBIRD"},
        "app.application.tenant_rbac_app_service.bind_verified_market_identity": None,
        flow + "_derive_and_heal_account_kind": "enterprise",
        flow + "persist_session_account_meta": None,
        "app.application.session_account_meta.persist_session_membership_tier": None,
        flow + "_reject_admin_on_desktop": {"success": False} if denied else None,
        flow + "_is_desktop_runtime": True,
    }
    with ExitStack() as stack:
        mocks = {
            path: stack.enter_context(patch(path, return_value=value))
            for path, value in values.items()
        }
        membership = stack.enter_context(
            patch(market + "fetch_market_membership_tier", new=AsyncMock(return_value="premium"))
        )
        report = stack.enter_context(
            patch(
                "app.application.desktop_delivery_receipt.report_desktop_login_delivery_receipt",
                new=AsyncMock(return_value=receipt),
            )
        )
        retry = stack.enter_context(
            patch(
                "app.application.mod_delivery_receipt_outbox.retry_delivery_receipts_for_session",
                new=AsyncMock(return_value={}, side_effect=retry_error),
            )
        )
        result = await finalize_enterprise_login(
            result={"success": True, "user": {"id": 25}},
            session_id="session-id",
            market_result={
                "success": True,
                "token": "market-token",
                "is_enterprise": True,
                "is_market_admin": False,
            },
            account_kind="enterprise",
            username="SUNBIRD",
            sku="personal",
            background_tasks=tasks,
        )
        if background:
            membership.assert_not_awaited()
            report.assert_not_awaited()
            assert len(tasks.tasks) == (0 if denied else 2)
            sent = []

            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body":
                    membership.assert_not_awaited()
                    report.assert_not_awaited()

            await JSONResponse(result, background=tasks)({"type": "http"}, AsyncMock(), send)
            assert sent[-1]["type"] == "http.response.body"
        if denied:
            report.assert_not_awaited()
            assert result["success"] is False
        else:
            membership.assert_awaited_once_with("market-token")
            mocks[
                "app.application.session_account_meta.persist_session_membership_tier"
            ].assert_called_once_with("session-id", "premium")
            report.assert_awaited_once_with("market-token")
            retry.assert_awaited_once_with("session-id", "market-token")
            assert result["delivery_receipt"] == receipt
            assert result["success"] is True
