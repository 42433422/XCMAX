from __future__ import annotations

import json

import pytest
from fastapi.responses import JSONResponse


@pytest.mark.asyncio
async def test_employee_work_proxy_forwards_create(monkeypatch):
    import app.fastapi_routes.employee_work_proxy as proxy

    monkeypatch.setattr(proxy, "_admin_gate", lambda _request: None)
    monkeypatch.setattr(
        proxy,
        "_authenticated_admin_actor_ref",
        lambda _request: "fhd:user:42:tenant:8",
    )
    seen = {}

    async def _fake_post(path, body):
        seen["path"] = path
        seen["body"] = body
        return {"created": True, "item": {"task_id": "mwi_1"}}

    monkeypatch.setattr(proxy, "_post", _fake_post)
    result = await proxy.desktop_management_work_create(
        object(),
        {"title": "任务", "owner_employee_id": "task-router-officer"},
    )
    assert result["item"]["task_id"] == "mwi_1"
    assert seen["path"] == "/api/admin/employee-autonomy/work-items"
    assert seen["body"]["source_kind"] == "desktop"
    assert seen["body"]["external_actor_ref"] == "fhd:user:42:tenant:8"


@pytest.mark.asyncio
async def test_employee_work_proxy_rejects_missing_exact_admin_subject(monkeypatch):
    import app.fastapi_routes.employee_work_proxy as proxy

    monkeypatch.setattr(proxy, "_admin_gate", lambda _request: None)
    monkeypatch.setattr(proxy, "_authenticated_admin_actor_ref", lambda _request: "")

    async def forbidden_post(*_args, **_kwargs):
        pytest.fail("unbound work must not be created")

    monkeypatch.setattr(proxy, "_post", forbidden_post)
    result = await proxy.desktop_management_work_create(object(), {"title": "任务"})
    assert result.status_code == 401


@pytest.mark.asyncio
async def test_employee_work_proxy_bridge_requires_strict_internal_auth(monkeypatch):
    import app.application.modstore_local_client as client_module
    import app.fastapi_routes.employee_work_proxy as proxy

    seen = []

    async def fake_get(path, **kwargs):
        seen.append(("get", path, kwargs))
        return {"count": 0}

    async def fake_post(path, **kwargs):
        seen.append(("post", path, kwargs))
        return {"created": True}

    monkeypatch.setattr(client_module, "modstore_get", fake_get)
    monkeypatch.setattr(client_module, "modstore_post", fake_post)
    monkeypatch.setattr(
        client_module,
        "modstore_management_base_url",
        lambda: "http://127.0.0.1:8788",
    )

    await proxy._get("/ledger")
    await proxy._post("/ledger", {"title": "任务"})

    assert seen[0][2]["strict_internal_auth"] is True
    assert seen[1][2]["strict_internal_auth"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "args"), [("_get", ("/ledger",)), ("_post", ("/ledger", {}))])
async def test_employee_work_proxy_never_exposes_bridge_exception(monkeypatch, method, args):
    import app.application.modstore_local_client as client_module
    import app.fastapi_routes.employee_work_proxy as proxy

    secret = "database-password=do-not-return"

    async def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(client_module, "modstore_get", fail)
    monkeypatch.setattr(client_module, "modstore_post", fail)
    result = await getattr(proxy, method)(*args)
    payload = json.loads(result.body)

    assert result.status_code == 502
    assert payload == {
        "success": False,
        "message": "管理端员工任务服务暂时不可用，请稍后重试",
    }
    assert secret not in result.body.decode("utf-8")


@pytest.mark.asyncio
async def test_employee_work_proxy_requires_admin(monkeypatch):
    import app.fastapi_routes.employee_work_proxy as proxy

    denied = JSONResponse({"success": False}, status_code=403)
    monkeypatch.setattr(proxy, "_admin_gate", lambda _request: denied)
    result = await proxy.desktop_management_work_summary(object())
    assert result is denied


def test_employee_work_proxy_router_contract():
    from app.fastapi_routes.employee_work_proxy import router

    paths = {route.path for route in router.routes}
    assert "/api/xcmax/employee-work" in paths
    assert "/api/xcmax/employee-work/summary" in paths
    assert "/api/xcmax/employee-work/employees" in paths
    assert "/api/xcmax/employee-work/{task_id}/review" in paths
    assert "/api/xcmax/employee-work/{task_id}/cancel" in paths
    assert "/api/xcmax/employee-work/{task_id}/reassign" in paths
    assert "/api/xcmax/employee-work/decisions/{decision_id}/resolve" in paths


@pytest.mark.asyncio
async def test_employee_work_proxy_forwards_cancel_and_reassign(monkeypatch):
    import app.fastapi_routes.employee_work_proxy as proxy

    monkeypatch.setattr(proxy, "_admin_gate", lambda _request: None)
    seen = []

    async def _fake_post(path, body):
        seen.append((path, body))
        return {"task_id": "mwi_1", "status": "assigned"}

    monkeypatch.setattr(proxy, "_post", _fake_post)
    await proxy.desktop_management_work_cancel(object(), "mwi_1", {"reason": "停止"})
    await proxy.desktop_management_work_reassign(
        object(), "mwi_1", {"new_employee_id": "fhd-core-maintainer"}
    )
    assert seen == [
        (
            "/api/admin/employee-autonomy/work-items/mwi_1/cancel",
            {"reason": "停止"},
        ),
        (
            "/api/admin/employee-autonomy/work-items/mwi_1/reassign",
            {"new_employee_id": "fhd-core-maintainer"},
        ),
    ]
