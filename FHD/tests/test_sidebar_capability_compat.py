"""侧栏能力兼容门面 + 客户 GET 同源列表。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def compat_app_client() -> TestClient:
    from app.legacy.routes.conversation import compat_extra, compat_routes
    from app.legacy.routes.sidebar_capability_compat import router as sidebar_router

    app = FastAPI()
    app.include_router(compat_routes.router, prefix="/api")
    app.include_router(compat_extra.router, prefix="/api")
    app.include_router(sidebar_router)
    return TestClient(app, raise_server_exceptions=False)


def test_chat_send_alias_registered(compat_app_client: TestClient) -> None:
    with patch(
        "app.legacy.routes.conversation.compat_routes.execute_compat_chat",
        new=MagicMock(return_value={"success": True, "reply": "ok"}),
    ) as mock_chat:
        # execute_compat_chat is async — patch with AsyncMock-like
        async def _ok(*_a, **_k):
            return {"success": True, "reply": "ok"}

        mock_chat.side_effect = _ok
        r = compat_app_client.post("/api/chat/send", json={"message": "闭环探测"})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_conversation_messages_post(compat_app_client: TestClient) -> None:
    sid = "closedloop-session-1"
    r = compat_app_client.post(
        f"/api/conversations/{sid}/messages",
        json={"content": "闭环探测消息", "role": "user"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("success") is True
    assert body.get("saved") is True
    listed = compat_app_client.get(f"/api/conversations/{sid}")
    assert listed.status_code == 200
    msgs = listed.json().get("messages") or []
    assert any("闭环探测消息" in str(m.get("content") or "") for m in msgs)


def test_knowledge_and_employee_aliases(compat_app_client: TestClient) -> None:
    with patch(
        "app.fastapi_routes.knowledge_v1.health",
        return_value={"success": True, "rag_enabled": False},
    ):
        r = compat_app_client.get("/api/knowledge")
    assert r.status_code == 200
    assert r.json()["success"] is True

    with patch(
        "app.fastapi_routes.knowledge_v1.dataset_status",
        return_value={"success": True, "dataset_id": "persy-knowledge"},
    ):
        r2 = compat_app_client.get("/api/persy/knowledge")
    assert r2.status_code == 200

    with patch(
        "app.fastapi_routes.system_routes.get_workflow_employee_catalog",
        new=MagicMock(return_value={"success": True, "data": {"catalog": []}}),
    ) as mock_cat:

        async def _cat():
            return {"success": True, "data": {"catalog": []}}

        mock_cat.side_effect = _cat
        r3 = compat_app_client.get("/api/employees")
    assert r3.status_code == 200
    assert r3.json()["success"] is True
    assert "deprecation" not in r3.headers


def test_data_sources_and_print_templates_aliases(compat_app_client: TestClient) -> None:
    r = compat_app_client.get("/api/data-sources")
    assert r.status_code == 200
    assert r.json()["total"] >= 1

    with patch(
        "app.fastapi_routes.template_api.templates_list_compat",
        return_value={"success": True, "templates": []},
    ):
        r2 = compat_app_client.get("/api/print/templates")
    assert r2.status_code == 200
    assert r2.json()["success"] is True
    assert r2.headers["deprecation"].startswith("@")
    assert r2.headers["link"] == '</api/templates>; rel="successor-version"'


def test_customers_all_delegates_to_list() -> None:
    from app.fastapi_routes.domains.customer import routes as customer_routes

    app = FastAPI()
    app.include_router(customer_routes.router)
    client = TestClient(app, raise_server_exceptions=False)

    with (
        patch(
            "app.mod_sdk.erp_customers_facade.is_erp_customers_via_service_enabled",
            return_value=False,
        ),
        patch(
            "app.mod_sdk.client_primary_erp.try_invoke_client_mod_customers_list",
            return_value=None,
        ),
        patch(
            "app.mod_sdk.client_primary_erp.resolve_client_erp_mod_for_request",
            return_value=None,
        ),
        patch(
            "app.mod_sdk.erp_domain_dispatch.try_invoke_erp_domain_handler",
            return_value=None,
        ),
        patch.object(
            customer_routes,
            "_load_customers_rows",
            return_value=[{"id": 9, "customer_name": "闭环组织"}],
        ),
        patch(
            "app.fastapi_routes.domains.customer.customer_routes.verify_db_read_token_header",
            return_value=None,
        ),
    ):
        r = client.get("/customers")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["total"] == 1
    assert data["data"][0]["customer_name"] == "闭环组织"


@pytest.mark.parametrize(
    "path,replacement",
    [
        ("/api/knowledge/base", "/api/knowledge/v1/health"),
        ("/api/workflow-employee-space/overview", "/api/system/workflow-employee-catalog"),
        ("/api/workflow/employees", "/api/system/workflow-employee-catalog"),
        ("/api/core-workflow/employees", "/api/system/workflow-employee-catalog"),
        ("/api/datasources", "/api/private-db-assistant/sources"),
        ("/api/erp/data-sources", "/api/private-db-assistant/sources"),
        ("/api/print/templates", "/api/templates"),
        ("/api/label/templates", "/api/templates"),
    ],
)
def test_legacy_probes_keep_data_and_advertise_real_successors(
    compat_app_client, path, replacement
):
    from unittest.mock import AsyncMock

    from fastapi.responses import JSONResponse

    with (
        patch("app.fastapi_routes.knowledge_v1.health", return_value={"success": True}),
        patch(
            "app.fastapi_routes.system_routes.get_workflow_employee_catalog",
            new=AsyncMock(return_value={"success": True, "data": {"catalog": []}}),
        ),
        patch(
            "app.fastapi_routes.template_api.templates_list_compat",
            return_value=JSONResponse({"success": True, "templates": [{"id": "T1"}]}),
        ),
    ):
        response = compat_app_client.get(path)
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.headers["deprecation"].startswith("@")
    assert response.headers["link"] == f'<{replacement}>; rel="successor-version"'
    assert compat_app_client.app.openapi()["paths"][path]["get"]["deprecated"] is True
    if path.endswith("/templates"):
        assert response.json()["templates"] == [{"id": "T1"}]


@pytest.mark.parametrize(
    "path",
    [
        "/api/knowledge",
        "/api/persy/knowledge",
        "/api/employees",
        "/api/data-sources",
    ],
)
def test_runtime_aliases_are_not_retired(compat_app_client, path):
    operation = compat_app_client.app.openapi()["paths"][path]["get"]
    assert not operation.get("deprecated")
