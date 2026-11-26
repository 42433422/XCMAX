from __future__ import annotations

import json
import urllib.request

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.fastapi_routes import kellai_binding
from app.services import kellai_binding_store
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

PAIRING_HEADERS = {"X-Kellai-Local-Pairing": "1"}
XCMAX_HEADERS = {**PAIRING_HEADERS, "X-XCMAX-Client-Shell": "enterprise"}
CLIENT_HEADERS = {"X-XCMAX-Client-Shell": "enterprise"}

MODULE_SCOPES = [
    "customer_profiles.read",
    "customer_conversations.read",
    "channels.read",
    "messages.send",
]


def approve_module(client: TestClient, scopes: list[str] | None = None) -> dict:
    started = client.post(
        "/api/kellai/binding/start",
        headers=XCMAX_HEADERS,
        json={"requested_scopes": scopes or MODULE_SCOPES},
    )
    assert started.status_code == 200
    pending = client.get("/api/kellai/binding/pending", headers=PAIRING_HEADERS).json()["data"]
    response = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "request_id": pending["request_id"],
            "authorization_secret": pending["authorization_secret"],
            "accepted_scopes": [scope["id"] for scope in pending["requested_scopes"]],
            "access_token": "private-local-token-" + "x" * 40,
            "authorized_by": {"id": "kellai-owner"},
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


@pytest.fixture()
def app(trusted_actor) -> FastAPI:
    actor = trusted_actor(permissions=[])
    application = FastAPI()
    application.include_router(kellai_binding.router)
    application.state.test_session_headers = actor.headers
    application.state.test_actor_id = actor.user_id
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
    return TestClient(
        app, client=("127.0.0.1", 50000), headers=getattr(app.state, "test_session_headers", {})
    )


def test_kellai_loopback_requests_bypass_environment_proxies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from io import BytesIO

    from app.infrastructure import kellai_client

    calls: list[tuple[urllib.request.Request, float]] = []

    class DirectOpener:
        def open(self, opened_request, *, timeout):
            calls.append((opened_request, timeout))
            return BytesIO(b'{"success":true,"data":{}}')

    monkeypatch.setattr(kellai_client, "_OPENER", DirectOpener())
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("fixed loopback traffic must not use global urlopen"),
    )

    assert kellai_client.request_kellai("channels", {"access_token": "test-token"}) == {
        "success": True,
        "data": {},
    }
    assert calls[0][0].full_url == "http://127.0.0.1:8793/api/kellai/integrations/xcmax/channels"
    assert calls[0][1] == 5


def test_optional_scopes_require_real_actor_and_never_upgrade_legacy(
    app, monkeypatch, isolated_store
):
    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: None)
    assert client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS).status_code == 401
    assert (
        client.post(
            "/api/kellai/binding/start",
            headers=XCMAX_HEADERS,
            json={"requested_scopes": MODULE_SCOPES},
        ).status_code
        == 401
    )
    assert kellai_binding_store.pending_for_kellai() is None
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    connection = approve_module(client, MODULE_SCOPES[:2])
    assert connection["authorized_scopes"] == MODULE_SCOPES[:2]
    monkeypatch.setattr(
        kellai_binding,
        "_open_kellai_request",
        lambda *_a, **_kw: pytest.fail("read-only binding must not send or read channels"),
    )
    assert client.get("/api/kellai/binding/channels", headers=CLIENT_HEADERS).status_code == 403
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 403
    )
    legacy = json.loads(isolated_store.read_text())
    legacy["connection"].pop("xcmax_user_id")
    isolated_store.write_text(json.dumps(legacy))
    before = isolated_store.read_bytes()
    assert client.get("/api/kellai/binding/channels", headers=CLIENT_HEADERS).status_code == 403
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 403
    )
    assert isolated_store.read_bytes() == before


def send_input() -> dict:
    return {
        "client_request_id": "message-request-12345",
        "customer_id": 8,
        "channel_type": "chatwoot",
        "contact_id": "conversation-28",
        "content": "人工确认的回复",
    }


def test_owned_scope_checks_account_tenant_and_revocation(app, monkeypatch):
    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    monkeypatch.setattr(kellai_binding, "_client_tenant", lambda _request: "team-a")
    connection = approve_module(client)
    assert connection["authorized_scopes"] == MODULE_SCOPES
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 8)
    assert client.get("/api/kellai/binding/customers", headers=CLIENT_HEADERS).status_code == 403
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 403
    )
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    monkeypatch.setattr(kellai_binding, "_client_tenant", lambda _request: "team-b")
    assert client.get("/api/kellai/binding/channels", headers=CLIENT_HEADERS).status_code == 403
    monkeypatch.setattr(kellai_binding, "_client_tenant", lambda _request: "team-a")
    assert client.post("/api/kellai/binding/disconnect", headers=XCMAX_HEADERS).status_code == 200
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 409
    )


@pytest.mark.parametrize("status", ["accepted", "failed", "unknown"])
def test_send_preserves_idempotency_and_provider_receipt(app, monkeypatch, status):
    import io

    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    approve_module(client)
    requests = []
    receipt = {
        "request_id": "message-request-12345",
        "status": status,
        "provider_message_id": "provider-9",
        "persisted": False,
        "replayed": False,
    }

    def fake_open(request, *, timeout):
        requests.append(request)
        return io.BytesIO(json.dumps({"success": status == "accepted", "data": receipt}).encode())

    monkeypatch.setattr(kellai_binding, "_open_kellai_request", fake_open)
    sent = client.post(
        "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
    )
    assert sent.status_code == 200
    assert sent.json()["data"] == receipt
    assert sent.json()["success"] is (status == "accepted")
    assert json.loads(requests[0].data) == send_input()
    assert (
        requests[0].full_url == "http://127.0.0.1:8793/api/kellai/integrations/xcmax/messages/send"
    )
    assert requests[0].get_header("Authorization").startswith("Bearer private-local-token-")
    assert "private-local-token" not in sent.text
    queried = client.get(
        "/api/kellai/binding/messages/requests/message-request-12345", headers=CLIENT_HEADERS
    )
    assert queried.json()["data"]["persisted"] is False
    assert requests[1].method == "GET"


def test_send_timeout_never_retries_and_validates_transport_input(app, monkeypatch):
    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    approve_module(client)
    calls = []

    def timeout(request, **_kwargs):
        calls.append(request)
        raise TimeoutError("secret upstream detail")

    monkeypatch.setattr(kellai_binding, "_open_kellai_request", timeout)
    response = client.post(
        "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
    )
    assert response.status_code == 503
    assert len(calls) == 1
    assert "原请求回执" in response.text and "secret upstream" not in response.text
    for field, bad in [
        ("content", "   "),
        ("customer_id", 0),
        ("channel_type", "../evil"),
        ("client_request_id", "../../evil/receipt"),
    ]:
        assert (
            client.post(
                "/api/kellai/binding/messages/send",
                headers=XCMAX_HEADERS,
                json={**send_input(), field: bad},
            ).status_code
            == 422
        )
    assert len(calls) == 1


@pytest.mark.parametrize("lookup", ["absent", "accepted", "unknown", "unavailable"])
def test_desktop_only_reply_checks_original_ledger_before_reporting_unsent(
    app, monkeypatch, lookup
):
    import io
    import urllib.error

    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    approve_module(client)
    requests = []
    request_id = send_input()["client_request_id"]

    def fake_open(request, *, timeout):
        requests.append(request)
        if request.method == "POST":
            raise urllib.error.HTTPError(
                request.full_url,
                409,
                "Conflict",
                {},
                io.BytesIO(b'{"detail":"requires_desktop_execution"}'),
            )
        if lookup == "absent":
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                {},
                io.BytesIO(b'{"detail":"missing"}'),
            )
        if lookup == "unavailable":
            raise TimeoutError("ledger unavailable")
        return io.BytesIO(
            json.dumps(
                {
                    "success": True,
                    "data": {
                        "request_id": request_id,
                        "status": lookup,
                        "persisted": False,
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(kellai_binding, "_open_kellai_request", fake_open)
    response = client.post(
        "/api/kellai/binding/messages/send",
        headers=XCMAX_HEADERS,
        json=send_input(),
    )
    assert [request.method for request in requests] == ["POST", "GET"]
    assert requests[1].full_url.endswith(f"messages/requests/{request_id}")
    if lookup == "unavailable":
        assert response.status_code == 503
    elif lookup == "absent":
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "requires_desktop_execution"
        assert response.json()["data"]["request_id"] == request_id
    else:
        assert response.status_code == 409
        assert "原请求已有发送账本" in response.json()["detail"]


@pytest.mark.parametrize("success", [True, False])
def test_message_receipt_must_match_original_request_even_with_success_flag(
    app, monkeypatch, success
):
    import io

    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: app.state.test_actor_id)
    approve_module(client)
    calls = []

    def wrong_receipt(request, *, timeout):
        calls.append(request)
        return io.BytesIO(
            json.dumps(
                {
                    "success": success,
                    "data": {
                        "request_id": "another-request-123",
                        "status": "accepted",
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(kellai_binding, "_open_kellai_request", wrong_receipt)
    response = client.post(
        "/api/kellai/binding/messages/send",
        headers=XCMAX_HEADERS,
        json=send_input(),
    )
    assert response.status_code == 502
    assert len(calls) == 1


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


@pytest.mark.parametrize(
    "account_kind,account_tier", [("personal", "normal"), ("enterprise", "personal")]
)
def test_personal_account_cannot_pair_or_read_with_enterprise_shell(
    app, trusted_actor, isolated_store, account_kind, account_tier
):
    from app.db.models.user import Session as UserSession
    from app.db.models.user import User

    actor = trusted_actor(tier="personal", permissions=[])
    with actor.factory.begin() as db:
        db.get(User, actor.user_id).account_tier = account_tier
        db.query(UserSession).filter_by(
            session_id=actor.session_id
        ).one().account_kind = account_kind
    client = TestClient(app, client=("127.0.0.1", 50000), headers=actor.headers)
    for method, path in [("GET", "status"), ("POST", "start"), ("GET", "channels")]:
        response = client.request(method, f"/api/kellai/binding/{path}", headers=XCMAX_HEADERS)
        assert response.status_code == 403
        assert "个人版" in response.json()["detail"]
    assert not isolated_store.exists()


def test_personal_plan_blocks_existing_kellai_use_but_preserves_owner_revocation(
    app, monkeypatch, isolated_store
):
    from app.db.models.user import User
    from app.db.session import get_host_db

    client = local_client(app)
    approve_module(client)
    original = isolated_store.read_bytes()
    with get_host_db() as db:
        db.get(User, app.state.test_actor_id).account_tier = "personal"
        db.commit()
    calls = []
    monkeypatch.setattr(
        kellai_binding, "_open_kellai_request", lambda *args, **kwargs: calls.append(args)
    )
    assert client.get("/api/kellai/binding/channels", headers=CLIENT_HEADERS).status_code == 403
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 403
    )
    assert calls == []
    assert isolated_store.read_bytes() == original
    assert client.post("/api/kellai/binding/disconnect", headers=XCMAX_HEADERS).status_code == 200
    assert kellai_binding_store.connection_credentials() is None


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


def test_pairing_requires_live_account_and_reads_use_unified_execution(app, monkeypatch):
    from app.infrastructure.auth.agent_mod_scope import _bound_actor

    anonymous = TestClient(app, client=("127.0.0.1", 50000))
    assert anonymous.post("/api/kellai/binding/start", headers=XCMAX_HEADERS).status_code == 401
    assert kellai_binding_store.pending_for_kellai() is None
    observed = []

    def execute(args, *, runtime_context):
        assert _bound_actor(runtime_context).id == app.state.test_actor_id
        observed.append(args)
        return json.dumps(
            {
                "success": True,
                "result": {"success": True, "data": {"customers": []}},
                "task_id": "original-task",
                "run_id": "original-run",
            }
        )

    monkeypatch.setattr(
        "app.application.tools.registered_capabilities.execute_registered_capability", execute
    )
    response = local_client(app).get(
        "/api/kellai/binding/customers?limit=2", headers=CLIENT_HEADERS
    )
    assert response.status_code == 200
    assert observed == [{"tool_id": "kellai", "action": "customers", "params": {"limit": 2}}]


def test_customer_data_proxy_clamps_limits_and_validates_customer_id(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_paths: list[str] = []

    def fake_kellai_get(request, action, params):
        requested_paths.append((action, params))
        if action == "conversations":
            return {"success": True, "data": {"messages": [{"id": "m-1"}]}}
        return {"success": True, "data": {"customers": [{"customer_id": 7}]}}

    monkeypatch.setattr(kellai_binding, "_read_kellai_capability", fake_kellai_get)
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
        ("customers", {"limit": 50}),
        ("conversations", {"customer_id": 7, "limit": 1}),
    ]
    assert invalid_customer.status_code == 422


def test_copilot_draft_uses_only_authorized_customer_conversation(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import kellai_customer_copilot

    requested_paths: list[str] = []

    def fake_kellai_get(request, action, params):
        requested_paths.append((action, params))
        if action == "conversations":
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

    monkeypatch.setattr(kellai_binding, "_read_kellai_capability", fake_kellai_get)
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
        ("customers", {"limit": 50}),
        ("conversations", {"customer_id": 7, "limit": 100}),
    ]


def test_copilot_draft_rejects_unpaired_or_unknown_customer(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        kellai_binding,
        "_read_kellai_capability",
        lambda *_args: {"success": True, "data": {"customers": []}},
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
            "actor": app.state.test_actor_id,
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
            "actor": app.state.test_actor_id,
            "outcome_result": "success",
        }
    ]
