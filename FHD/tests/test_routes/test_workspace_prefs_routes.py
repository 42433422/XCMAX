from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.fastapi_routes.workspace_prefs_routes import (
    WorkspacePrefsPatch,
    patch_workspace_prefs_endpoint,
)


@pytest.mark.asyncio
async def test_patch_workspace_prefs_keeps_success_when_market_sync_fails(monkeypatch):
    user = SimpleNamespace(id=7)

    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.get_logged_in_user",
        lambda _request: user,
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.resolve_workspace_owner_id",
        lambda _request, _user: "tenant:42",
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.session_id_from_request",
        lambda _request: "sid-42",
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.patch_workspace_prefs",
        lambda _owner_id, partial: dict(partial),
    )
    monkeypatch.setattr(
        "app.fastapi_routes.workspace_prefs_routes.bind_selected_industry_for_user",
        lambda _user, industry_id, *, industry_mod_id="", owner_id=None: {
            "selected_industry_id": industry_id,
            "industry_mod_id": industry_mod_id,
            "owner_id": owner_id,
        },
    )

    async def fail_market_sync(_session_id: str, _industry_id: str):
        return {"success": False, "message": "market failed"}

    monkeypatch.setattr(
        "app.fastapi_routes.market_account.grant_market_enterprise_entitlements_for_session",
        fail_market_sync,
    )

    result = await patch_workspace_prefs_endpoint(
        WorkspacePrefsPatch(
            selected_industry_id="涂料",
            industry_mod_id="coating-industry",
        ),
        MagicMock(),
    )

    assert result["success"] is True
    assert result["owner_id"] == "tenant:42"
    assert result["data"]["selected_industry_id"] == "涂料"
    assert result["market_entitlements"]["success"] is False
