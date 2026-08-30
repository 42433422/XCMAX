from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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
async def test_desktop_login_finalize_reports_delivery_receipt():
    from app.application.enterprise_login_finalize import finalize_enterprise_login

    receipt = {"reported": True, "duplicate": False, "source": "desktop_login"}
    with (
        patch("app.fastapi_routes.market_account.save_session_market_token"),
        patch(
            "app.fastapi_routes.market_account.fetch_market_membership_tier",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.application.enterprise_login_flow.extract_market_user_blob",
            return_value={"id": 29, "username": "SUNBIRD"},
        ),
        patch(
            "app.application.enterprise_login_flow.company_brand_from_user_blob",
            return_value="SUNBIRD",
        ),
        patch(
            "app.application.enterprise_login_flow.bind_tenant_for_login",
            return_value={"tenant_id": None, "tenant_name": "SUNBIRD"},
        ),
        patch(
            "app.application.enterprise_login_flow._derive_and_heal_account_kind",
            return_value="enterprise",
        ),
        patch("app.application.enterprise_login_flow.persist_session_account_meta"),
        patch(
            "app.application.enterprise_login_flow._reject_admin_on_desktop",
            return_value=None,
        ),
        patch(
            "app.application.enterprise_login_flow._is_desktop_runtime",
            return_value=True,
        ),
        patch(
            "app.application.desktop_delivery_receipt.report_desktop_login_delivery_receipt",
            new_callable=AsyncMock,
            return_value=receipt,
        ) as report,
    ):
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
        )

    report.assert_awaited_once_with("market-token")
    assert result["delivery_receipt"] == receipt
