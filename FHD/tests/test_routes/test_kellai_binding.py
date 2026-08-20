# mypy: disable-error-code="index"
from __future__ import annotations

import json
import urllib.request

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import kellai_binding
from app.services import kellai_binding_store

PAIRING_HEADERS = {"X-Kellai-Local-Pairing": "1"}
XCMAX_HEADERS = {**PAIRING_HEADERS, "X-XCMAX-Client-Shell": "enterprise"}
CLIENT_HEADERS = {"X-XCMAX-Client-Shell": "enterprise"}


@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(kellai_binding.router)
    return application


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path):
    from app.services import kellai_customer_copilot

    store_path = tmp_path / "kellai-binding.json"
    monkeypatch.setattr(kellai_binding_store, "_store_path", lambda: store_path)
    monkeypatch.setattr(
        kellai_customer_copilot,
        "_store_path",
        lambda: tmp_path / "kellai-copilot-drafts.json",
    )
    return store_path


def local_client(app: FastAPI) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 50000))


def test_kellai_loopback_requests_bypass_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = urllib.request.Request("http://127.0.0.1:8793/health")
    sentinel = object()
    calls: list[tuple[urllib.request.Request, float]] = []

    class DirectOpener:
        def open(self, opened_request, *, timeout):
            calls.append((opened_request, timeout))
            return sentinel

    monkeypatch.setattr(kellai_binding, "_DIRECT_LOOPBACK_OPENER", DirectOpener())
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("fixed loopback traffic must not use global urlopen"),
    )

    assert kellai_binding._open_kellai_request(request, timeout=3) is sentinel
    assert calls == [(request, 3)]


def test_infrastructure_mount_registers_kellai_binding_routes() -> None:
    from app.fastapi_routes.mounts.infrastructure import register_infrastructure_routes

    application = FastAPI()
    register_infrastructure_routes(application)

    response = local_client(application).get(
        "/api/kellai/binding/status",
        headers=CLIENT_HEADERS,
    )
    assert response.status_code == 200


def test_binding_routes_reject_remote_and_unmarked_mutations(app: FastAPI) -> None:
    remote = TestClient(app, client=("203.0.113.7", 50000))
    assert remote.get("/api/kellai/binding/status", headers=CLIENT_HEADERS).status_code == 403

    client = local_client(app)
    assert client.post("/api/kellai/binding/start").status_code == 403
    assert client.get("/api/kellai/binding/status").status_code == 403
    assert (
        client.get(
            "/api/kellai/binding/status",
            headers={"X-XCMAX-Client-Shell": "admin"},
        ).status_code
        == 403
    )
    status = client.get("/api/kellai/binding/status", headers=CLIENT_HEADERS)
    assert status.status_code == 200
    assert status.json()["data"]["state"] == "not_connected"


def test_admin_account_is_denied_even_if_it_spoofs_the_enterprise_shell(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application import session_account_meta
    from app.infrastructure.auth import client_shell_session

    monkeypatch.setattr(
        client_shell_session, "resolve_session_id_from_request", lambda _request: "admin-session"
    )
    monkeypatch.setattr(
        session_account_meta,
        "load_session_account_meta",
        lambda _session_id: {"account_kind": "admin", "market_is_admin": True},
    )

    response = local_client(app).get(
        "/api/kellai/binding/customers",
        headers=CLIENT_HEADERS,
    )

    assert response.status_code == 403
    assert "管理账号" in response.json()["detail"]


def test_pairing_secrets_never_appear_in_public_status(app: FastAPI) -> None:
    client = local_client(app)
    started = client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS)
    assert started.status_code == 200
    started_payload = started.json()["data"]
    assert "authorization_secret" not in started_payload

    pending = client.get("/api/kellai/binding/pending", headers=PAIRING_HEADERS).json()["data"]
    approved = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "request_id": pending["request_id"],
            "authorization_secret": pending["authorization_secret"],
            "accepted_scopes": [scope["id"] for scope in pending["requested_scopes"]],
            "access_token": "local-token-" + "x" * 40,
            "authorized_by": {"id": "owner-1", "display_name": "企业负责人"},
        },
    )
    assert approved.status_code == 200

    status = client.get("/api/kellai/binding/status", headers=CLIENT_HEADERS).json()["data"]
    serialized_status = json.dumps(status, ensure_ascii=False)
    assert status["state"] == "connected"
    assert status["connection"]["authorized_by"]["display_name"] == "企业负责人"
    assert "access_token" not in serialized_status
    assert "authorization_secret" not in serialized_status

    credentials = kellai_binding_store.connection_credentials()
    assert credentials is not None
    assert credentials["access_token"].startswith("local-token-")

    disconnected = client.post("/api/kellai/binding/disconnect", headers=XCMAX_HEADERS)
    assert disconnected.status_code == 200
    assert (
        client.get(
            "/api/kellai/binding/status",
            headers=CLIENT_HEADERS,
        ).json()["data"]["state"]
        == "not_connected"
    )


def test_pairing_requires_all_read_only_scopes(app: FastAPI) -> None:
    client = local_client(app)
    client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS)
    pending = client.get("/api/kellai/binding/pending", headers=PAIRING_HEADERS).json()["data"]

    response = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "request_id": pending["request_id"],
            "authorization_secret": pending["authorization_secret"],
            "accepted_scopes": ["customer_profiles.read"],
            "access_token": "x" * 40,
            "authorized_by": {},
        },
    )

    assert response.status_code == 400
    assert "全部只读权限" in response.json()["detail"]


def test_customer_data_proxy_clamps_limits_and_validates_customer_id(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def fake_kellai_get(path: str):
        requested_paths.append(path)
        if "conversations" in path:
            return {"success": True, "data": {"messages": [{"id": "m-1"}]}}
        return {"success": True, "data": {"customers": [{"customer_id": 7}]}}

    monkeypatch.setattr(kellai_binding, "_kellai_get", fake_kellai_get)
    client = local_client(app)

    customers = client.get("/api/kellai/binding/customers?limit=999", headers=CLIENT_HEADERS)
    conversations = client.get(
        "/api/kellai/binding/customers/7/conversations?limit=-4",
        headers=CLIENT_HEADERS,
    )
    invalid_customer = client.get(
        "/api/kellai/binding/customers/0/conversations",
        headers=CLIENT_HEADERS,
    )

    assert customers.json()["data"]["customers"][0]["customer_id"] == 7
    assert conversations.json()["data"]["messages"][0]["id"] == "m-1"
    assert requested_paths == [
        "/api/kellai/integrations/xcmax/customers?limit=50",
        "/api/kellai/integrations/xcmax/customers/7/conversations?limit=1",
    ]
    assert invalid_customer.status_code == 422


def test_copilot_draft_uses_only_authorized_customer_conversation(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import kellai_customer_copilot

    requested_paths: list[str] = []

    def fake_kellai_get(path: str):
        requested_paths.append(path)
        if path.endswith("/conversations?limit=100"):
            return {
                "success": True,
                "data": {
                    "messages": [
                        {
                            "id": "m-1",
                            "customer_id": 7,
                            "direction": "inbound",
                            "content": "请问什么时候可以交付？",
                        }
                    ]
                },
            }
        return {
            "success": True,
            "data": {
                "customers": [
                    {
                        "customer_id": 7,
                        "display_name": "已授权客户",
                        "stage_label": "意向客户",
                    }
                ]
            },
        }

    captured: dict[str, object] = {}

    async def fake_generate_draft(**kwargs):
        captured.update(kwargs)
        return {
            "draft_id": "draft-1",
            "customer_id": 7,
            "summary": "客户询问交期",
            "reply_draft": "我先为您核实。",
            "risk_level": "medium",
            "status": "pending_approval",
        }

    monkeypatch.setattr(kellai_binding, "_kellai_get", fake_kellai_get)
    monkeypatch.setattr(kellai_customer_copilot, "generate_draft", fake_generate_draft)

    response = local_client(app).post(
        "/api/kellai/binding/customers/7/copilot-drafts",
        headers=XCMAX_HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending_approval"
    assert captured["customer_id"] == 7
    assert captured["customer"]["display_name"] == "已授权客户"
    assert captured["messages"][0]["id"] == "m-1"
    assert requested_paths == [
        "/api/kellai/integrations/xcmax/customers?limit=50",
        "/api/kellai/integrations/xcmax/customers/7/conversations?limit=100",
    ]


def test_copilot_draft_rejects_unpaired_or_unknown_customer(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kellai_binding,
        "_kellai_get",
        lambda _path: {"success": True, "data": {"customers": []}},
    )
    client = local_client(app)

    unpaired = client.post(
        "/api/kellai/binding/customers/7/copilot-drafts",
        headers=CLIENT_HEADERS,
    )
    unknown = client.post(
        "/api/kellai/binding/customers/7/copilot-drafts",
        headers=XCMAX_HEADERS,
    )

    assert unpaired.status_code == 403
    assert unknown.status_code == 404
    assert "真实客户" in unknown.json()["detail"]


def test_copilot_approval_is_explicit_and_client_only(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import kellai_customer_copilot

    decisions: list[dict[str, object]] = []

    def fake_decide_draft(**kwargs):
        decisions.append(kwargs)
        return {
            "draft_id": kwargs["draft_id"],
            "customer_id": 7,
            "status": "approved_for_manual_send",
            "reply_draft": "人工确认后复制",
        }

    monkeypatch.setattr(kellai_customer_copilot, "decide_draft", fake_decide_draft)
    client = local_client(app)

    admin = client.post(
        "/api/kellai/binding/copilot-drafts/draft-1/approve",
        headers={"X-XCMAX-Client-Shell": "admin", "X-Kellai-Local-Pairing": "1"},
        json={"note": "管理端不应批准"},
    )
    approved = client.post(
        "/api/kellai/binding/copilot-drafts/draft-1/approve",
        headers=XCMAX_HEADERS,
        json={"note": "已由客户负责人核对"},
    )

    assert admin.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["data"]["status"] == "approved_for_manual_send"
    assert decisions == [
        {
            "draft_id": "draft-1",
            "decision": "approve",
            "actor": None,
            "note": "已由客户负责人核对",
        }
    ]


def test_follow_up_task_routes_stay_in_client_plane(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import kellai_customer_copilot

    task = {
        "task_id": "task-1",
        "customer_id": 7,
        "source_draft_id": "draft-1",
        "title": "客户跟进 · 交期咨询",
        "description": "核实交期并回访",
        "priority": "normal",
        "status": "open",
    }
    decisions: list[dict[str, object]] = []
    monkeypatch.setattr(
        kellai_customer_copilot,
        "list_follow_up_tasks",
        lambda customer_id: [task] if customer_id == 7 else [],
    )
    monkeypatch.setattr(
        kellai_customer_copilot,
        "create_follow_up_task",
        lambda **_kwargs: task,
    )

    def fake_decision(**kwargs):
        decisions.append(kwargs)
        return {**task, "status": "completed"}

    monkeypatch.setattr(kellai_customer_copilot, "decide_follow_up_task", fake_decision)
    client = local_client(app)

    listed = client.get(
        "/api/kellai/binding/customers/7/follow-up-tasks",
        headers=CLIENT_HEADERS,
    )
    unpaired = client.post(
        "/api/kellai/binding/copilot-drafts/draft-1/follow-up-task",
        headers=CLIENT_HEADERS,
    )
    created = client.post(
        "/api/kellai/binding/copilot-drafts/draft-1/follow-up-task",
        headers=XCMAX_HEADERS,
    )
    completed = client.post(
        "/api/kellai/binding/follow-up-tasks/task-1/complete",
        headers=XCMAX_HEADERS,
        json={"outcome_result": "success"},
    )
    admin = client.get(
        "/api/kellai/binding/customers/7/follow-up-tasks",
        headers={"X-XCMAX-Client-Shell": "admin"},
    )

    assert listed.status_code == 200
    assert listed.json()["data"]["tasks"][0]["task_id"] == "task-1"
    assert unpaired.status_code == 403
    assert created.status_code == 200
    assert completed.json()["data"]["status"] == "completed"
    assert admin.status_code == 403
    assert decisions == [
        {
            "task_id": "task-1",
            "decision": "complete",
            "actor": None,
            "outcome_result": "success",
        }
    ]
