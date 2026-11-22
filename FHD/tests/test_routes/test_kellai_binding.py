from __future__ import annotations

import json
import urllib.request
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.shared_services import kellai_binding_store
from app.fastapi_routes import kellai_binding

PAIRING_HEADERS = {"X-Kellai-Local-Pairing": "1"}
XCMAX_HEADERS = {**PAIRING_HEADERS, "X-XCMAX-Client-Shell": "enterprise"}
CLIENT_HEADERS = {"X-XCMAX-Client-Shell": "enterprise"}

NATIVE_BACKEND_SELECTOR = kellai_binding_store._credential_backend

MODULE_SCOPES = [
    "channels.read",
    "messages.read",
    "messages.send",
]


def approve_module(client: TestClient, scopes: list[str] | None = None) -> dict:
    started = client.post(
        "/api/kellai/binding/start",
        headers=XCMAX_HEADERS,
        json={"requested_scopes": scopes or MODULE_SCOPES},
    )
    assert started.status_code == 200
    pending = client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS).json()["data"]
    response = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "protocol_version": 2,
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
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(kellai_binding.router)
    return application


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch: pytest.MonkeyPatch, tmp_path):
    store_path = tmp_path / "kellai-binding.json"
    monkeypatch.setattr(kellai_binding_store, "_store_path", lambda: store_path)
    secrets = {}
    native = SimpleNamespace(
        set_password=lambda _s, k, v: secrets.__setitem__(k, v),
        get_password=lambda _s, k: secrets.get(k),
        delete_password=lambda _s, k: secrets.pop(k, None),
    )
    monkeypatch.setattr(kellai_binding_store, "_credential_backend", lambda: native)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _r: 7)
    monkeypatch.setattr(kellai_binding, "_client_tenant", lambda _r: "team-a")
    from app.infrastructure import kellai_client

    @contextmanager
    def ready_probe(request, *, timeout):
        assert request.full_url.endswith("/grant-status")
        connection = kellai_binding_store.connection_metadata()
        payload = {
            "success": True,
            "data": {"connection_id": connection["connection_id"], "protocol_version": 2},
        }
        yield SimpleNamespace(read=lambda: json.dumps(payload).encode())

    monkeypatch.setattr(kellai_client._OPENER, "open", ready_probe)
    return store_path


def local_client(app: FastAPI) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 50000), base_url="http://127.0.0.1:5001")


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


def test_scopes_require_real_actor_and_do_not_silently_expand(app, monkeypatch):
    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: None)
    assert client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS).status_code == 400
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
    approve_module(client, ["channels.read"])
    assert client.get("/api/kellai/binding/contacts", headers=CLIENT_HEADERS).status_code == 403
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 403
    )


def send_input() -> dict:
    return {
        "client_request_id": "message-request-12345",
        "customer_id": 8,
        "connection_id": "account-chatwoot-a",
        "channel_type": "chatwoot",
        "contact_id": "conversation-28",
        "content": "人工确认的回复",
    }


def test_manual_send_rejects_invalid_body_before_dispatch(app, monkeypatch):
    client = local_client(app)
    approve_module(client)
    calls = []

    @contextmanager
    def accepted(request, *, timeout):
        calls.append(request)
        yield SimpleNamespace(
            read=lambda: json.dumps(
                {
                    "success": True,
                    "data": {
                        "request_id": send_input()["client_request_id"],
                        "status": "accepted",
                    },
                }
            ).encode()
        )

    monkeypatch.setattr(kellai_binding, "_open_kellai_request", accepted)
    assert (
        client.post(
            "/api/kellai/binding/messages/send",
            headers=XCMAX_HEADERS,
            json={**send_input(), "content": "字" * 8000},
        ).status_code
        == 200
    )
    response = client.post(
        "/api/kellai/binding/messages/send",
        headers=XCMAX_HEADERS,
        json={**send_input(), "content": "字" * 8001},
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "content"]
    assert len(calls) == 1


def test_manual_send_denied_scope_is_explicitly_not_dispatched(app, monkeypatch):
    client = local_client(app)
    approve_module(client, ["channels.read"])
    monkeypatch.setattr(
        kellai_binding,
        "_open_kellai_request",
        lambda *_args, **_kwargs: pytest.fail("denied scope reached tool"),
    )
    response = client.post(
        "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
    )
    assert response.status_code == 403
    assert response.json()["detail"]["request_not_dispatched"] is True


@pytest.mark.parametrize(
    ("status", "payload", "not_dispatched"),
    [
        (
            status,
            b'{"detail":{"code":"fixture_denial","message":"denied"}}',
            status in {401, 403, 422},
        )
        for status in [401, 403, 422, 404, 409, 503]
    ]
    + [
        (401, b"invalid-response", False),
        (422, b'{"detail":[null]}', False),
        (422, b'{"detail":[{"loc":["body","content"],"type":"string_too_long"}]}', True),
    ],
)
def test_tool_http_rejection_does_not_claim_history_or_transport_outcome(
    app, monkeypatch, status, payload, not_dispatched
):
    import io
    from urllib.error import HTTPError

    client = local_client(app)
    approve_module(client)
    calls = []

    def denied(request, *, timeout):
        calls.append(request)
        raise HTTPError(
            request.full_url,
            status,
            "Refused",
            {},
            io.BytesIO(payload),
        )

    monkeypatch.setattr(kellai_binding, "_open_kellai_request", denied)
    response = client.post(
        "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
    )
    assert response.status_code == status
    detail = response.json()["detail"]
    assert (
        isinstance(detail, dict) and detail.get("request_not_dispatched", False)
    ) is not_dispatched
    assert len(calls) == 1
    # Rejecting a read of an existing request cannot prove the original send absent.
    queried = client.get(
        "/api/kellai/binding/messages/requests/message-request-12345", headers=CLIENT_HEADERS
    )
    assert queried.status_code == status
    detail = queried.json()["detail"]
    assert not (isinstance(detail, dict) and detail.get("request_not_dispatched"))


def test_owned_scope_checks_account_tenant_and_revocation(app, monkeypatch):
    client = local_client(app)
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
    monkeypatch.setattr(kellai_binding, "_client_tenant", lambda _request: "team-a")
    connection = approve_module(client)
    assert connection["authorized_scopes"] == MODULE_SCOPES
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 8)
    assert client.get("/api/kellai/binding/contacts", headers=CLIENT_HEADERS).status_code == 403
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=send_input()
        ).status_code
        == 403
    )
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
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
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
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
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
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
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
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
    monkeypatch.setattr(kellai_binding, "_client_actor", lambda _request: 7)
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
        "/api/kellai/binding/contacts",
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

    pending = client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS).json()["data"]
    approved = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "protocol_version": 2,
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


def test_pairing_accepts_a_smaller_grant_without_expanding_requested_scopes(app: FastAPI) -> None:
    client = local_client(app)
    client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS)
    pending = client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS).json()["data"]

    response = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "protocol_version": 2,
            "request_id": pending["request_id"],
            "authorization_secret": pending["authorization_secret"],
            "accepted_scopes": ["channels.read"],
            "access_token": "x" * 40,
            "authorized_by": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["authorized_scopes"] == ["channels.read"]
    assert client.get("/api/kellai/binding/contacts", headers=CLIENT_HEADERS).status_code == 403


@pytest.mark.parametrize("scopes", [[], ["messages.send"], ["channels.read", "messages.send"]])
def test_pairing_rejects_empty_or_expanded_grants(app, scopes):
    client = local_client(app)
    client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS)
    pending = client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS).json()["data"]
    response = client.post(
        "/api/kellai/binding/approve",
        headers=PAIRING_HEADERS,
        json={
            "protocol_version": 2,
            "request_id": pending["request_id"],
            "authorization_secret": pending["authorization_secret"],
            "accepted_scopes": scopes,
            "access_token": "x" * 40,
        },
    )
    assert response.status_code == 400
    assert kellai_binding_store.connection_metadata() is None


def test_handoff_is_single_use_and_rejects_cross_site_origin_and_host(app):
    client = local_client(app)
    assert client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS).status_code == 200
    assert client.get("/api/kellai/binding/pending", headers=PAIRING_HEADERS).status_code == 404
    for headers in (
        {**PAIRING_HEADERS, "Origin": "https://evil.example"},
        {**PAIRING_HEADERS, "Origin": "null"},
        {**PAIRING_HEADERS, "Host": "evil.example"},
    ):
        assert client.post("/api/kellai/binding/handoff", headers=headers).status_code == 403
    pending = client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS)
    assert pending.status_code == 200
    assert pending.json()["data"]["protocol_version"] == 2
    assert client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS).status_code == 409


def test_plaintext_legacy_grant_is_retired_without_scope_expansion(app, isolated_store):
    isolated_store.write_text(
        json.dumps({"version": 1, "connection": {"access_token": "old-secret"}})
    )
    response = local_client(app).get("/api/kellai/binding/status", headers=CLIENT_HEADERS)
    assert response.json()["data"]["requires_reauthorization"] is True
    assert response.json()["data"]["state"] == "not_connected"
    assert "old-secret" not in isolated_store.read_text()


def test_pending_and_access_secrets_live_only_in_keychain(app, isolated_store):
    client = local_client(app)
    approve_module(client)
    state = json.loads(isolated_store.read_text())
    assert "access_token" not in state["connection"]
    assert state["connection"]["access_token_ref"]
    assert "private-local-token" not in isolated_store.read_text()
    assert state["pending"] is None


def test_contact_messages_require_explicit_connection_and_read_scope(app, monkeypatch):
    client = local_client(app)
    approve_module(client)
    calls = []
    monkeypatch.setattr(
        kellai_binding,
        "_kellai_scoped_request",
        lambda path, _c: calls.append(path) or {"success": True, "data": {"messages": []}},
    )
    assert (
        client.get("/api/kellai/binding/contacts/7/messages", headers=CLIENT_HEADERS).status_code
        == 422
    )
    response = client.get(
        "/api/kellai/binding/contacts/7/messages?connection_id=account-a", headers=CLIENT_HEADERS
    )
    assert response.status_code == 200
    assert calls == ["contacts/7/messages?connection_id=account-a&limit=100"]
    assert (
        client.get("/api/kellai/binding/contacts?limit=101", headers=CLIENT_HEADERS).status_code
        == 422
    )
    missing_account = send_input()
    del missing_account["connection_id"]
    assert (
        client.post(
            "/api/kellai/binding/messages/send", headers=XCMAX_HEADERS, json=missing_account
        ).status_code
        == 422
    )


def test_plaintext_or_missing_keyring_never_creates_a_pending_grant(
    app, monkeypatch, isolated_store
):
    class PlaintextBackend:
        priority = 1

    monkeypatch.setattr(kellai_binding_store.keyring, "get_keyring", lambda: PlaintextBackend())
    monkeypatch.setattr(kellai_binding_store, "_credential_backend", NATIVE_BACKEND_SELECTOR)
    response = local_client(app).post("/api/kellai/binding/start", headers=XCMAX_HEADERS)
    assert response.status_code == 400
    assert "安全凭据库" in response.json()["detail"]
    assert not isolated_store.exists()


def test_locked_vault_blocks_io_but_does_not_block_revoking_the_grant(
    app, monkeypatch, isolated_store
):
    client = local_client(app)
    approve_module(client)

    def locked():
        raise ValueError("系统凭据库已锁定")

    monkeypatch.setattr(kellai_binding_store, "_credential_backend", locked)
    assert client.get("/api/kellai/binding/status", headers=CLIENT_HEADERS).status_code == 200
    assert client.get("/api/kellai/binding/channels", headers=CLIENT_HEADERS).status_code == 503
    assert client.post("/api/kellai/binding/disconnect", headers=XCMAX_HEADERS).status_code == 200
    assert json.loads(isolated_store.read_text())["connection"] is None


def test_expired_handoff_secret_is_deleted_from_vault(app, monkeypatch, isolated_store):
    from datetime import timedelta

    client = local_client(app)
    assert client.post("/api/kellai/binding/start", headers=XCMAX_HEADERS).status_code == 200
    pending = json.loads(isolated_store.read_text())["pending"]
    backend = kellai_binding_store._credential_backend()
    assert backend.get_password("com.xcagi.kellai", pending["authorization_secret_ref"])
    future = kellai_binding_store._now() + timedelta(minutes=16)
    monkeypatch.setattr(kellai_binding_store, "_now", lambda: future)
    assert client.post("/api/kellai/binding/handoff", headers=PAIRING_HEADERS).status_code == 409
    assert backend.get_password("com.xcagi.kellai", pending["authorization_secret_ref"]) is None


@pytest.mark.parametrize(
    "code", ["xcmax_grant_revoked", "xcmax_grant_invalid", "xcmax_reauthorization_required"]
)
def test_explicit_tool_revocation_retires_only_the_matching_secret(app, monkeypatch, code):
    from io import BytesIO
    from urllib.error import HTTPError

    from app.infrastructure import kellai_client

    client = local_client(app)
    connection = approve_module(client)
    metadata = kellai_binding_store.connection_metadata()
    vault = kellai_binding_store._credential_backend()

    def revoked(request, *, timeout):
        payload = {"detail": {"code": code, "message": "授权已失效"}}
        raise HTTPError(request.full_url, 401, "revoked", {}, BytesIO(json.dumps(payload).encode()))

    monkeypatch.setattr(kellai_client._OPENER, "open", revoked)
    status = client.get("/api/kellai/binding/status", headers=CLIENT_HEADERS).json()["data"]
    assert status["state"] == "revoked"
    assert status["requires_reauthorization"] is True
    assert status["connection"]["connection_id"] == connection["connection_id"]
    assert vault.get_password("com.xcagi.kellai", metadata["access_token_ref"]) is None
    assert kellai_binding_store.connection_credentials() is None


@pytest.mark.parametrize("code", ["", "xcmax_scope_required"])
def test_offline_or_scope_denial_does_not_revoke_the_grant(app, monkeypatch, code):
    from app.infrastructure import kellai_client

    client = local_client(app)
    approve_module(client)
    original = kellai_binding_store.connection_metadata()

    def unavailable(*_args, **_kwargs):
        raise kellai_client.KellaiRequestError("暂不可达或该权限未授予", 403 if code else 503, code)

    monkeypatch.setattr(kellai_client, "request_kellai", unavailable)
    status = client.get("/api/kellai/binding/status", headers=CLIENT_HEADERS).json()["data"]
    assert status["state"] == "offline"
    assert kellai_binding_store.connection_metadata() == original
    assert kellai_binding_store.connection_credentials()["access_token"]
