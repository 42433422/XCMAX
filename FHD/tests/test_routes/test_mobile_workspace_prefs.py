from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.fastapi_routes.mobile_extensions.routes_workspace import (
    MobileWorkspacePrefsPatch,
    WorkspaceRoutes,
)


def endpoints():
    ports = SimpleNamespace(mobile_unauthorized_response=lambda: JSONResponse({}, status_code=401))
    router = WorkspaceRoutes(ports, lambda: None).router
    return {
        next(iter(route.methods)): route.endpoint
        for route in router.routes
        if route.path == "/workspace/prefs"
    }


def request():
    return Request({"type": "http", "headers": [(b"x-session-id", b"current-account")]})


@pytest.mark.asyncio
async def test_native_workspace_uses_desktop_owner_and_merge_logic(monkeypatch):
    from app.fastapi_routes import workspace_prefs_routes as shared

    read = Mock(
        return_value={
            "success": True,
            "owner_id": "account-one",
            "data": {"workflow_ai_employees": {"a": True}},
        }
    )
    write = AsyncMock(
        return_value={
            "success": True,
            "owner_id": "account-one",
            "data": {"workflow_ai_employees": {"a": True, "b": False}},
        }
    )
    monkeypatch.setattr(shared, "get_workspace_prefs_endpoint", read)
    monkeypatch.setattr(shared, "patch_workspace_prefs_endpoint", write)
    routes, req = endpoints(), request()
    assert (await routes["GET"](req, user=object()))["owner_id"] == "account-one"
    body = MobileWorkspacePrefsPatch(workflow_ai_employees={"b": False})
    result = await routes["PATCH"](body, req, user=object())
    assert result["data"]["workflow_ai_employees"] == {"a": True, "b": False}
    read.assert_called_once_with(req)
    passed, passed_request = write.call_args.args
    assert passed.model_dump(exclude_none=True) == {"workflow_ai_employees": {"b": False}}
    assert passed_request is req


@pytest.mark.asyncio
async def test_native_workspace_denies_missing_user_or_unresolved_owner(monkeypatch):
    from app.fastapi_routes import workspace_prefs_routes as shared

    read = Mock(return_value={"success": True, "owner_id": None, "data": {}})
    monkeypatch.setattr(shared, "get_workspace_prefs_endpoint", read)
    routes, req = endpoints(), request()
    assert (await routes["GET"](req, user=None)).status_code == 401
    assert (
        await routes["PATCH"](MobileWorkspacePrefsPatch(workflow_ai_employees={}), req, user=None)
    ).status_code == 401
    read.assert_not_called()
    assert (await routes["GET"](req, user=object())).status_code == 403


def test_mobile_workspace_cannot_change_ownership_or_industry():
    for forbidden in ["owner_id", "selected_industry_id", "host_pack_acknowledged"]:
        with pytest.raises(ValidationError):
            MobileWorkspacePrefsPatch.model_validate(
                {"workflow_ai_employees": {}, forbidden: "other"}
            )


@pytest.mark.asyncio
async def test_native_workspace_forwards_optional_revision_token(monkeypatch):
    from app.fastapi_routes import workspace_prefs_routes as shared

    save = AsyncMock(return_value={"success": True, "revision": 9})
    monkeypatch.setattr(shared, "patch_workspace_prefs_endpoint", save)
    routes, req = endpoints(), request()
    result = await routes["PATCH"](
        MobileWorkspacePrefsPatch(
            workflow_ai_employees={"alpha": True}, expected_revision=8
        ),
        req,
        user=object(),
    )
    assert result["revision"] == 9
    body, passed_request = save.call_args.args
    assert passed_request is req
    assert body.model_dump(exclude_none=True) == {
        "workflow_ai_employees": {"alpha": True},
        "expected_revision": 8,
    }
    with pytest.raises(ValidationError):
        MobileWorkspacePrefsPatch.model_validate(
            {"workflow_ai_employees": {}, "expected_revision": -1}
        )
    with pytest.raises(ValidationError):
        MobileWorkspacePrefsPatch.model_validate(
            {"workflow_ai_employees": {}, "expected_revision": True}
        )
