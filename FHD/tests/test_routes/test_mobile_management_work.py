from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

import app.db.session as session_module
from app.db.models.mobile_notification import MobileNotificationOutbox
from app.services.mobile_push import enqueue_outbox


@pytest.fixture(scope="module")
def mobile_ext():
    if "app.fastapi_routes.mobile_api_extensions" not in sys.modules:
        from app.fastapi_routes import mobile_api  # noqa: F401
    return sys.modules["app.fastapi_routes.mobile_api_extensions"]


@pytest.fixture
def admin_user():
    return SimpleNamespace(id=7, role="admin", is_active=True, tenant_id=8)


@pytest.mark.asyncio
async def test_mobile_management_work_list_uses_shared_ledger(
    monkeypatch,
    mobile_ext,
    admin_user,
):
    monkeypatch.setattr(
        mobile_ext,
        "_require_mobile_admin",
        lambda _request, _user: ({"account_kind": "admin"}, None),
    )
    seen: dict[str, str] = {}

    async def fake_get(path: str, *, query: str = ""):
        seen.update(path=path, query=query)
        return {"items": [{"task_id": "mwi_same"}], "summary": {"active": 1}}

    monkeypatch.setattr(mobile_ext, "_mobile_management_work_get", fake_get)
    result = await mobile_ext.mobile_admin_management_work_list(
        request=object(),
        status="waiting_decision,delivered",
        owner_employee_id="task-router-officer",
        limit=50,
        user=admin_user,
    )

    assert result["success"] is True
    assert result["data"]["items"][0]["task_id"] == "mwi_same"
    assert seen["path"] == "/api/admin/employee-autonomy/work-items"
    assert "waiting_decision%2Cdelivered" in seen["query"]


@pytest.mark.asyncio
async def test_mobile_management_work_action_records_authenticated_admin(
    monkeypatch,
    mobile_ext,
    admin_user,
):
    monkeypatch.setattr(
        mobile_ext,
        "_require_mobile_admin",
        lambda _request, _user: ({"account_kind": "admin"}, None),
    )
    monkeypatch.setattr(
        mobile_ext,
        "_mobile_request_user_id",
        lambda _request, _user: 7,
    )
    seen = {}

    async def fake_post(path: str, body: dict, *, user_id: int, tenant_id: int):
        seen.update(path=path, body=body, user_id=user_id, tenant_id=tenant_id)
        return {"task_id": "mwi_same", "status": "accepted"}

    monkeypatch.setattr(mobile_ext, "_mobile_management_work_post", fake_post)
    result = await mobile_ext.mobile_admin_management_work_review(
        task_id="mwi_same",
        request=object(),
        body={"accepted": True, "feedback": "证据通过"},
        user=admin_user,
    )

    assert result["data"]["status"] == "accepted"
    assert seen == {
        "path": "/api/admin/employee-autonomy/work-items/mwi_same/review",
        "body": {"accepted": True, "feedback": "证据通过"},
        "user_id": 7,
        "tenant_id": 8,
    }


@pytest.mark.asyncio
async def test_mobile_management_bridge_uses_external_actor_and_strict_internal_auth(
    monkeypatch,
    mobile_ext,
):
    import app.application.modstore_local_client as client_module

    seen = {}

    async def fake_post(path, **kwargs):
        seen.update(path=path, **kwargs)
        return {"task_id": "mwi_same", "status": "accepted"}

    monkeypatch.setattr(client_module, "modstore_post", fake_post)
    monkeypatch.setattr(
        client_module,
        "modstore_management_base_url",
        lambda: "http://127.0.0.1:8788",
    )
    result = await mobile_ext._mobile_management_work_post(
        "/api/admin/employee-autonomy/work-items/mwi_same/review",
        {"accepted": True, "user_id": 99, "created_by_user_id": 98},
        user_id=7,
        tenant_id=8,
    )

    assert result["status"] == "accepted"
    assert seen["strict_internal_auth"] is True
    assert seen["json_body"] == {
        "accepted": True,
        "external_actor_ref": "fhd:user:7:tenant:8",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "args", "expected_message"),
    [
        (
            "_mobile_management_work_get",
            ("/api/admin/employee-autonomy/work-items",),
            "管理端员工任务服务暂时不可用，请稍后重试",
        ),
        (
            "_mobile_management_work_post",
            ("/api/admin/employee-autonomy/work-items", {}, 7, 8),
            "管理端员工任务服务暂时不可用，请稍后重试",
        ),
    ],
)
async def test_mobile_management_bridge_never_exposes_exception_details(
    monkeypatch,
    mobile_ext,
    method,
    args,
    expected_message,
):
    import app.application.modstore_local_client as client_module

    secret = "authorization=Bearer private-token"

    async def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(client_module, "modstore_get", fail)
    monkeypatch.setattr(client_module, "modstore_post", fail)
    if method.endswith("_post"):
        path, body, user_id, tenant_id = args
        response = await getattr(mobile_ext, method)(
            path,
            body,
            user_id=user_id,
            tenant_id=tenant_id,
        )
    else:
        response = await getattr(mobile_ext, method)(*args)
    payload = json.loads(response.body)

    assert response.status_code == 502
    assert payload["message"] == expected_message
    assert secret not in response.body.decode("utf-8")


def test_mobile_extension_has_no_exception_detail_serialization(mobile_ext):
    source = open(mobile_ext.__file__, encoding="utf-8").read()

    for forbidden in (
        "str(exc)",
        "str(ae)",
        "{exc}",
        "_compact_text(exc)",
        "logger.exception(",
        "exc_info=True",
    ):
        assert forbidden not in source


@pytest.mark.asyncio
async def test_mobile_management_work_rejects_non_admin(
    monkeypatch,
    mobile_ext,
    admin_user,
):
    denied = JSONResponse({"success": False}, status_code=403)
    monkeypatch.setattr(
        mobile_ext,
        "_require_mobile_admin",
        lambda _request, _user: ({"account_kind": "enterprise"}, denied),
    )
    result = await mobile_ext.mobile_admin_management_work_detail(
        task_id="mwi_hidden",
        request=object(),
        user=admin_user,
    )
    assert result is denied


def test_mobile_management_work_route_contract(mobile_ext):
    paths = {route.path for route in mobile_ext.extension_router.routes}
    assert "/admin/employee-work" in paths
    assert "/admin/employee-work/{task_id}" in paths
    assert "/admin/employee-work/{task_id}/review" in paths
    assert "/admin/employee-work/{task_id}/retry" in paths
    assert "/admin/employee-work/{task_id}/cancel" in paths
    assert "/admin/employee-work/{task_id}/reassign" in paths
    assert "/admin/employee-work/employees" in paths
    assert "/admin/employee-work/decisions/{decision_id}/resolve" in paths


@pytest.mark.asyncio
async def test_mobile_management_work_cancel_and_reassign_use_admin_identity(
    monkeypatch,
    mobile_ext,
    admin_user,
):
    monkeypatch.setattr(
        mobile_ext,
        "_require_mobile_admin",
        lambda _request, _user: ({"account_kind": "admin"}, None),
    )
    monkeypatch.setattr(mobile_ext, "_mobile_request_user_id", lambda *_args: 7)
    seen = []

    async def fake_post(path: str, body: dict, *, user_id: int, tenant_id: int):
        seen.append((path, body, user_id, tenant_id))
        return {"task_id": "mwi_same", "status": "assigned"}

    monkeypatch.setattr(mobile_ext, "_mobile_management_work_post", fake_post)
    await mobile_ext.mobile_admin_management_work_cancel(
        task_id="mwi_same",
        request=object(),
        body={"reason": "停止"},
        user=admin_user,
    )
    await mobile_ext.mobile_admin_management_work_reassign(
        task_id="mwi_same",
        request=object(),
        body={"new_employee_id": "fhd-core-maintainer"},
        user=admin_user,
    )
    assert seen == [
        (
            "/api/admin/employee-autonomy/work-items/mwi_same/cancel",
            {"reason": "停止"},
            7,
            8,
        ),
        (
            "/api/admin/employee-autonomy/work-items/mwi_same/reassign",
            {"new_employee_id": "fhd-core-maintainer"},
            7,
            8,
        ),
    ]


@pytest.mark.asyncio
async def test_mobile_notification_requires_explicit_ack_and_deduplicates_event(
    monkeypatch,
    mobile_ext,
    admin_user,
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    MobileNotificationOutbox.__table__.create(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def fake_get_db():
        db = factory()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    monkeypatch.setattr(session_module, "get_db", fake_get_db)
    monkeypatch.setattr(mobile_ext, "_ensure_outbox_table", lambda: None)
    payload = {
        "event_id": "management_work.delivered:mwi_same:delivered:1",
        "task_id": "mwi_same",
        "route": "management_work/mwi_same",
        "channel": "management_work",
    }
    assert (
        enqueue_outbox(
            7,
            "员工已交付",
            "等待验收",
            payload,
            audience="management",
            tenant_id=8,
        )
        is True
    )
    assert (
        enqueue_outbox(
            7,
            "员工已交付",
            "等待验收",
            payload,
            audience="management",
            tenant_id=8,
        )
        is True
    )

    pending = await mobile_ext.mobile_notifications_pending(limit=50, user=admin_user)
    assert len(pending["data"]["notifications"]) == 1
    notification_id = pending["data"]["notifications"][0]["id"]
    with fake_get_db() as db:
        assert db.query(MobileNotificationOutbox).one().delivered is False

    acked = await mobile_ext.mobile_notification_ack(notification_id, user=admin_user)
    assert acked["data"]["acked"] is True
    with fake_get_db() as db:
        assert db.query(MobileNotificationOutbox).one().delivered is True
