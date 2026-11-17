"""Tests for self-maintenance local/proxy routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.fastapi_routes import xcmax_admin as admin_routes


@pytest.fixture
def controller(monkeypatch):
    from app.fastapi_routes.admin_control.maintenance import SelfMaintenance

    errors = MagicMock()
    errors.recoverable.return_value = (OSError, ValueError)
    proxy = AsyncMock(return_value={"ok": True})
    gate = MagicMock(return_value=None)
    monkeypatch.delenv("MODSTORE_LOCAL_AUTOMATION", raising=False)
    return SelfMaintenance(errors=errors, proxy=proxy, gate=gate), proxy, gate


@pytest.mark.asyncio
async def test_status_alias_reads_configured_market_by_default(controller):
    service, proxy, _ = controller
    req = MagicMock()
    result = await service.local_self_maintenance_status(req, 40)
    proxy.assert_awaited_once_with(
        req, "GET", "/api/ops/self-maintenance/status?limit=40", json_body=None
    )
    assert result["control_plane"]["target"] == "market"


@pytest.mark.asyncio
async def test_explicit_local_status_passes_limit_and_provenance(controller, monkeypatch):
    service, proxy, _ = controller
    monkeypatch.setenv("MODSTORE_LOCAL_AUTOMATION", "1")
    with patch(
        "app.application.self_maintenance_app_service.get_runtime_status_local",
        new=AsyncMock(return_value={"ok": True}),
    ) as local:
        result = await service.local_self_maintenance_status(MagicMock(), 40)
    assert local.await_args.kwargs["limit"] == 40
    assert result["control_plane"]["target"] == "local"
    proxy.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path,fn",
    [
        ("GET", "status", "get_runtime_status_local"),
        ("POST", "run", "force_run_local"),
        ("POST", "governance-review", "governance_review_local"),
    ],
)
async def test_local_failure_never_replays_on_remote(controller, monkeypatch, method, path, fn):
    service, proxy, _ = controller
    monkeypatch.setenv("MODSTORE_LOCAL_AUTOMATION", "1")
    with patch(
        f"app.application.self_maintenance_app_service.{fn}",
        new=AsyncMock(side_effect=OSError("offline")),
    ):
        result = await service._self_maintenance_local_or_proxy(
            MagicMock(), method, f"/api/ops/self-maintenance/{path}"
        )
    assert result.status_code == 502
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_upstream_404_does_not_fall_back_to_another_environment(controller):
    service, proxy, _ = controller
    proxy.return_value = JSONResponse({}, status_code=404)
    with patch(
        "app.application.self_maintenance_app_service.get_runtime_status_local", new=AsyncMock()
    ) as local:
        result = await service.local_self_maintenance_status(MagicMock(), 80)
    assert result.status_code == 404
    local.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_admin_gate_precedes_status_and_commands(controller, status):
    service, proxy, gate = controller
    gate.return_value = JSONResponse({}, status_code=status)
    assert (await service.local_self_maintenance_status(MagicMock(), 80)).status_code == status
    assert (
        await service.local_self_maintenance_governance_review(MagicMock(), {})
    ).status_code == status
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_ignores_non_matching_path(controller):
    service, proxy, _ = controller
    assert (
        await service._self_maintenance_local_or_proxy(
            MagicMock(), "GET", "/api/admin/duty-graph/health"
        )
        is None
    )
    proxy.assert_not_awaited()


@pytest.mark.asyncio
async def test_market_admin_proxy_routes_yuangon_run_to_local_modstore():
    req = MagicMock()
    payload = {"dry_run": False, "force": False, "pkg_ids": ""}
    expected = {"ok": True, "onboard_summary": {"skipped": 52, "failed": 0}}
    with (
        patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=None,
        ),
        patch(
            "app.application.modstore_local_client.prefer_local_modstore",
            return_value=True,
        ),
        patch(
            "app.application.self_maintenance_app_service.run_yuangon_onboard_local",
            new=AsyncMock(return_value=expected),
        ) as mock_local,
    ):
        result = await admin_routes._market_admin_proxy(
            req,
            "POST",
            "/api/admin/yuangon-onboard/run",
            json_body=payload,
        )

    assert result == expected
    mock_local.assert_awaited_once_with(payload)


@pytest.mark.asyncio
async def test_market_admin_proxy_does_not_fallback_remote_when_local_yuangon_fails():
    req = MagicMock()
    with (
        patch(
            "app.fastapi_routes.xcmax_admin._require_market_admin_session",
            return_value=None,
        ),
        patch(
            "app.application.modstore_local_client.prefer_local_modstore",
            return_value=True,
        ),
        patch(
            "app.application.self_maintenance_app_service.run_yuangon_onboard_local",
            new=AsyncMock(side_effect=OSError("offline")),
        ),
        patch(
            "app.fastapi_routes.market_account._proxy_json",
            new=AsyncMock(),
        ) as mock_remote,
    ):
        result = await admin_routes._market_admin_proxy(
            req,
            "POST",
            "/api/admin/yuangon-onboard/run",
            json_body={},
        )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 502
    mock_remote.assert_not_awaited()
