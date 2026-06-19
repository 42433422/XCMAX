"""Tests for self-maintenance local/proxy routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.responses import JSONResponse

from app.fastapi_routes import xcmax_admin as admin_routes


@pytest.mark.asyncio
async def test_self_maintenance_local_or_proxy_prefers_local_when_enabled():
    req = MagicMock()
    payload = {"schema_version": "self_maintenance_runtime.v1", "contract": {}}
    with patch(
        "app.application.modstore_local_client.prefer_local_modstore",
        return_value=True,
    ), patch(
        "app.application.self_maintenance_app_service.get_runtime_status_local",
        new=AsyncMock(return_value=payload),
    ) as mock_local:
        result = await admin_routes._self_maintenance_local_or_proxy(
            req,
            "GET",
            "/api/ops/self-maintenance/status?limit=40",
        )
    assert result == payload
    mock_local.assert_awaited_once()


@pytest.mark.asyncio
async def test_self_maintenance_local_or_proxy_falls_back_after_upstream_404():
    req = MagicMock()
    payload = {"schema_version": "self_maintenance_runtime.v1", "contract": {}}
    with patch(
        "app.application.modstore_local_client.prefer_local_modstore",
        return_value=False,
    ), patch(
        "app.fastapi_routes.xcmax_admin._market_admin_proxy",
        new=AsyncMock(return_value=JSONResponse({"message": "Not Found"}, status_code=404)),
    ), patch(
        "app.application.self_maintenance_app_service.get_runtime_status_local",
        new=AsyncMock(return_value=payload),
    ) as mock_local:
        result = await admin_routes._self_maintenance_local_or_proxy(
            req,
            "GET",
            "/api/ops/self-maintenance/status?limit=80",
        )
    assert result == payload
    mock_local.assert_awaited_once()


@pytest.mark.asyncio
async def test_self_maintenance_local_or_proxy_ignores_non_matching_path():
    req = MagicMock()
    result = await admin_routes._self_maintenance_local_or_proxy(
        req,
        "GET",
        "/api/admin/duty-graph/health",
    )
    assert result is None


@pytest.mark.asyncio
async def test_market_admin_proxy_routes_yuangon_run_to_local_modstore():
    req = MagicMock()
    payload = {"dry_run": False, "force": False, "pkg_ids": ""}
    expected = {"ok": True, "onboard_summary": {"skipped": 52, "failed": 0}}
    with patch(
        "app.fastapi_routes.xcmax_admin._require_market_admin_session",
        return_value=None,
    ), patch(
        "app.application.modstore_local_client.prefer_local_modstore",
        return_value=True,
    ), patch(
        "app.application.self_maintenance_app_service.run_yuangon_onboard_local",
        new=AsyncMock(return_value=expected),
    ) as mock_local:
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
    with patch(
        "app.fastapi_routes.xcmax_admin._require_market_admin_session",
        return_value=None,
    ), patch(
        "app.application.modstore_local_client.prefer_local_modstore",
        return_value=True,
    ), patch(
        "app.application.self_maintenance_app_service.run_yuangon_onboard_local",
        new=AsyncMock(side_effect=OSError("offline")),
    ), patch(
        "app.fastapi_routes.market_account._proxy_json",
        new=AsyncMock(),
    ) as mock_remote:
        result = await admin_routes._market_admin_proxy(
            req,
            "POST",
            "/api/admin/yuangon-onboard/run",
            json_body={},
        )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 502
    mock_remote.assert_not_awaited()
