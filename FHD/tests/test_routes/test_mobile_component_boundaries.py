"""Mobile HTTP composition, resource ownership, and scoped data regressions."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.application.im_app_service import ImApplicationService
from app.db.base import Base
from app.db.models.ai import AIConversation, AIConversationSession
from app.db.models.approval import ApprovalFlow, ApprovalFlowNode, ApprovalRequest
from app.db.models.customer import Customer
from app.db.models.mobile_device import MobileDeviceToken
from app.db.models.shipment import ShipmentRecord
from app.db.models.user import Session as HostSession
from app.db.models.user import User
from app.fastapi_routes import mobile_api
from app.fastapi_routes import mobile_api_extensions as routes
from app.fastapi_routes.mobile_extensions.read_models import MobileReadModels, MobileReadModelsPorts
from app.fastapi_routes.mobile_extensions.routes_admin import AdminRoutes
from app.fastapi_routes.mobile_extensions.routes_cs_contacts import (
    ContactRoutes,
    ContactRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_devices import DeviceRoutes
from app.fastapi_routes.mobile_extensions.routes_employee_chat import (
    EmployeeChatRoutes,
    EmployeeChatRoutesPorts,
)
from app.fastapi_routes.mobile_extensions.routes_worklists import (
    WorklistRoutes,
    WorklistRoutesPorts,
)
from app.infrastructure.tenant_scope import tenant_scope
from app.security.mobile_jwt import issue_mobile_tokens
from app.utils.time import utc_now_naive


@dataclass
class Principal:
    id: int = 71
    username: str = "synthetic-mobile-user"
    is_active: bool = True


async def _principal() -> Principal:
    return Principal()


def _request() -> Request:
    return Request({"type": "http", "headers": [], "method": "POST", "path": "/"})


def _payload(response: object) -> dict[str, Any]:
    if isinstance(response, JSONResponse):
        return cast("dict[str, Any]", json.loads(bytes(response.body)))
    assert isinstance(response, dict)
    return response


def _events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


@pytest.mark.asyncio
async def test_anonymous_employee_stream_never_starts_executor(monkeypatch):
    execute = MagicMock(return_value={"success": True, "result": {"response": "fake reply"}})
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", execute
    )
    app = FastAPI()
    app.include_router(routes.extension_router, prefix="/api/mobile/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://mobile.test"
    ) as client:
        response = await client.post(
            "/api/mobile/v1/employees/fake-employee/chat/stream", json={"message": "fake message"}
        )
    assert response.status_code == 401
    assert response.json()["success"] is False
    execute.assert_not_called()


@pytest.fixture
def super_stream(monkeypatch):
    service = SimpleNamespace(invoke_stream=MagicMock())
    monkeypatch.setattr(routes, "CodexSuperEmployeeService", lambda: service)
    monkeypatch.setattr(routes, "_require_mobile_admin", lambda request, user: ({}, None))
    monkeypatch.setattr(routes, "_mobile_request_user_id", lambda request, user: 71)
    monkeypatch.setattr(routes, "_mobile_session_meta", lambda request: {})
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["close", "cancel"])
async def test_super_employee_stream_closes_owned_iterator(super_stream, ending):
    closed = asyncio.Event()

    async def events() -> AsyncGenerator[dict[str, Any], None]:
        try:
            yield {"type": "token", "text": "fake"}
            yield {"type": "done"}
        finally:
            await asyncio.sleep(0)
            closed.set()

    source = events()
    super_stream.invoke_stream.return_value = source
    response = await routes._stream_super_employee_invoke(
        _request(), "codex", {"message": "fake"}, Principal()
    )
    assert isinstance(response, StreamingResponse)
    outer = cast("AsyncGenerator[bytes, None]", response.body_iterator)
    try:
        assert b'"type": "token"' in await anext(outer)
        if ending == "close":
            await outer.aclose()
        else:
            with pytest.raises(asyncio.CancelledError):
                await outer.athrow(asyncio.CancelledError())
        assert closed.is_set()
    finally:
        await outer.aclose()
        await source.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [False, True])
async def test_service_completion_and_failure_close_before_http_end(super_stream, failure):
    closed = asyncio.Event()

    async def events() -> AsyncGenerator[dict[str, Any], None]:
        try:
            yield {"type": "token", "text": "synthetic"}
            if failure:
                raise RuntimeError("synthetic service error")
            yield {"type": "done", "result": {"response": "synthetic"}}
        finally:
            closed.set()

    super_stream.invoke_stream.side_effect = lambda **kwargs: events()
    response = await routes._stream_super_employee_invoke(
        _request(), "codex", {"message": "fake"}, Principal()
    )
    assert isinstance(response, StreamingResponse)
    text = b"".join([cast("bytes", chunk) async for chunk in response.body_iterator]).decode()
    assert [event["type"] for event in _events(text)] == ["token", "error" if failure else "done"]
    assert closed.is_set()


@pytest.mark.asyncio
async def test_actual_streaming_response_disconnect_closes_service(super_stream):
    sent = asyncio.Event()
    closed = asyncio.Event()
    pending = asyncio.Event()
    read_tasks: list[asyncio.Task | None] = []

    async def events() -> AsyncGenerator[dict[str, Any], None]:
        try:
            read_tasks.append(asyncio.current_task())
            yield {"type": "token", "text": "synthetic"}
            read_tasks.append(asyncio.current_task())
            await pending.wait()
        finally:
            # Multiple checkpoints expose repeated AnyIO cancellation during cleanup.
            for _ in range(3):
                await asyncio.sleep(0)
            closed.set()

    super_stream.invoke_stream.side_effect = lambda **kwargs: events()
    response = await routes._stream_super_employee_invoke(
        _request(), "codex", {"message": "fake"}, Principal()
    )
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)
        if message["type"] == "http.response.body" and message.get("body"):
            sent.set()

    async def receive() -> dict[str, Any]:
        await sent.wait()
        return {"type": "http.disconnect"}

    await asyncio.wait_for(
        response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), 5
    )
    assert closed.is_set()
    assert all(task is not None and task.done() for task in read_tasks)
    assert len([message for message in messages if message.get("body")]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["complete", "error", "close"])
async def test_stream_reads_on_demand_and_reaps_every_read_task(super_stream, ending):
    read_tasks: list[asyncio.Task | None] = []
    closed = asyncio.Event()

    async def events() -> AsyncGenerator[dict[str, Any], None]:
        try:
            read_tasks.append(asyncio.current_task())
            yield {"type": "token", "text": "synthetic"}
            read_tasks.append(asyncio.current_task())
            if ending == "error":
                raise RuntimeError("synthetic read failure")
            yield {"type": "done"}
            read_tasks.append(asyncio.current_task())
        finally:
            await asyncio.sleep(0)
            closed.set()

    super_stream.invoke_stream.return_value = events()
    response = await routes._stream_super_employee_invoke(
        _request(), "codex", {"message": "fake"}, Principal()
    )
    assert isinstance(response, StreamingResponse)
    outer = cast("AsyncGenerator[bytes, None]", response.body_iterator)
    assert b'"type": "token"' in await anext(outer)
    await asyncio.sleep(0)
    assert len(read_tasks) == 1
    if ending == "close":
        await outer.aclose()
    else:
        remainder = b"".join([chunk async for chunk in outer]).decode()
        assert [event["type"] for event in _events(remainder)] == [
            "error" if ending == "error" else "done"
        ]
    assert closed.is_set()
    assert all(task is not None and task.done() for task in read_tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["complete", "close", "cancel"])
async def test_source_factory_reads_and_close_share_one_context(super_stream, ending):
    current = ContextVar("mobile_stream_scope", default="request")
    owned_tasks: list[asyncio.Task | None] = []
    closed = asyncio.Event()

    def source_factory(**kwargs):
        factory_token = current.set("factory")
        owned_tasks.append(asyncio.current_task())

        async def events() -> AsyncGenerator[dict[str, Any], None]:
            token = current.set("source")
            try:
                owned_tasks.append(asyncio.current_task())
                yield {"type": "token", "text": current.get()}
                owned_tasks.append(asyncio.current_task())
                yield {"type": "done", "scope": current.get()}
            finally:
                await asyncio.sleep(0)
                current.reset(token)
                assert current.get() == "factory"
                current.reset(factory_token)
                owned_tasks.append(asyncio.current_task())
                closed.set()

        return events()

    super_stream.invoke_stream.side_effect = source_factory
    response = await routes._stream_super_employee_invoke(
        _request(), "codex", {"message": "fake"}, Principal()
    )
    assert isinstance(response, StreamingResponse)
    outer = cast("AsyncGenerator[bytes, None]", response.body_iterator)
    first = await anext(outer)
    assert _events(first.decode()) == [{"type": "token", "text": "source"}]
    if ending == "complete":
        remaining = b"".join([chunk async for chunk in outer]).decode()
        assert _events(remaining) == [{"type": "done", "scope": "source"}]
    elif ending == "close":
        await outer.aclose()
    else:
        with pytest.raises(asyncio.CancelledError):
            await outer.athrow(asyncio.CancelledError())
    assert closed.is_set()
    assert current.get() == "request"
    assert len(set(owned_tasks)) == 1
    assert all(task is not None and task.done() for task in owned_tasks)


@pytest.mark.asyncio
async def test_independent_employee_component_streams_configured_executor():
    execute = MagicMock(return_value={"success": True})
    component = EmployeeChatRoutes(
        EmployeeChatRoutesPorts(
            extract_employee_failure_text=lambda result: "failure",
            chunk_employee_reply=lambda text: [text],
            extract_employee_reply_text=lambda result: "configured reply",
            sse_line=lambda payload: ("data: " + json.dumps(payload) + "\n\n").encode(),
            execute_employee=execute,
        ),
        _principal,
    )
    app = FastAPI()
    app.include_router(component.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://mobile.test"
    ) as client:
        response = await client.post(
            "/employees/fixture/chat/stream",
            json={"message": "hello", "conversation_id": "c-71", "mod_id": "fixture-mod"},
        )
    assert response.status_code == 200
    assert [event["type"] for event in _events(response.text)] == ["token", "token", "done"]
    assert _events(response.text)[-1]["result"]["response"] == "configured reply"
    assert execute.call_args.kwargs == {
        "user_id": 71,
        "workspace_root": None,
        "session_id": "mobile_chat_71",
    }
    assert execute.call_args.args[2]["conversation_id"] == "c-71"


@pytest.mark.asyncio
async def test_employee_stream_close_before_work_does_not_start_thread(monkeypatch):
    execute = MagicMock()
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", execute
    )
    response = await routes.mobile_employee_chat_stream(
        "fixture", _request(), Principal(), {"message": "fake"}
    )
    assert isinstance(response, StreamingResponse)
    stream = cast("AsyncGenerator[bytes, None]", response.body_iterator)
    assert b'"type": "token"' in await anext(stream)
    await stream.aclose()
    execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method",
    [
        "mobile_admin_codex_super_employee_stream",
        "mobile_admin_claude_super_employee_stream",
        "mobile_admin_cursor_super_employee_stream",
        "mobile_admin_trae_super_employee_stream",
    ],
)
async def test_stream_route_uses_later_replacement_of_shared_callback(monkeypatch, method):
    response = JSONResponse({"replacement": True})
    invoke = AsyncMock(return_value=response)
    monkeypatch.setattr(routes, "_stream_super_employee_invoke", invoke)
    actual = await getattr(routes, method)(_request(), {"message": "fake"}, Principal())
    assert actual is response
    invoke.assert_awaited_once()


@pytest.fixture
def database(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'mobile.sqlite3'}")
    tables = [
        Base.metadata.tables[model.__tablename__]
        for model in (
            Customer,
            ApprovalFlow,
            ApprovalFlowNode,
            ApprovalRequest,
            ShipmentRecord,
            AIConversationSession,
            AIConversation,
            MobileDeviceToken,
            User,
            HostSession,
        )
    ]
    Base.metadata.create_all(engine, tables=tables)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    yield sessions
    engine.dispose()


def _database_port(sessions: sessionmaker[Session]):
    @contextmanager
    def open_database() -> Iterator[Session]:
        with sessions.begin() as db:
            yield db

    return open_database


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant", [11, 22, None])
async def test_independent_worklists_preserve_real_tenant_filter(database, tenant):
    with database.begin() as db:
        db.add(User(id=71, username="synthetic-owner", password="unused"))
        db.add(ApprovalFlow(id=1, flow_key="synthetic", flow_name="synthetic"))
    for tid in (11, 22):
        with tenant_scope(tid), database.begin() as db:
            db.add(Customer(id=tid, customer_name=f"customer-{tid}"))
            db.add(
                ApprovalRequest(
                    id=tid,
                    request_no=f"approval-{tid}",
                    flow_id=1,
                    business_type="synthetic",
                    applicant_id=71,
                    title=f"approval-{tid}",
                )
            )
            db.add(
                ShipmentRecord(
                    id=tid,
                    purchase_unit="synthetic",
                    product_name=f"product-{tid}",
                    quantity_kg=1,
                    quantity_tins=1,
                )
            )
    port = _database_port(database)
    queries = MobileReadModels(MobileReadModelsPorts(database=port))
    component = WorklistRoutes(
        WorklistRoutesPorts(database=port, employee_ssot_payload=lambda: {}), _principal
    )
    with tenant_scope(tenant):
        customers = _payload(await component.mobile_customers(1, 20, Principal()))
        approvals = _payload(
            await component.mobile_approval_list(_request(), None, 1, 20, Principal())
        )
        shipments = _payload(await component.mobile_shipments(1, 20, Principal()))
        expected = [] if tenant is None else [tenant]
        for result in (customers, approvals, shipments):
            assert [row["id"] for row in result["data"]["items"]] == expected
            assert result["data"]["pagination"]["total"] == len(expected)
        assert [row["id"] for row in queries._approval_items()] == expected
        assert [row["id"] for row in queries._shipment_items()] == expected


def test_conversation_projection_uses_session_owner_even_if_message_claims_another(database):
    with database.begin() as db:
        db.add_all(
            [
                User(id=71, username="synthetic-owner", password="unused"),
                User(id=72, username="synthetic-other", password="unused"),
            ]
        )
    with database.begin() as db:
        db.add_all(
            [
                AIConversationSession(session_id="own", user_id=71),
                AIConversationSession(session_id="other", user_id=72),
            ]
        )
        db.add_all(
            [
                AIConversation(
                    session_id="own", user_id="72", role="assistant", content="own-session"
                ),
                AIConversation(
                    session_id="other", user_id="71", role="assistant", content="other-session"
                ),
            ]
        )
    queries = MobileReadModels(MobileReadModelsPorts(database=_database_port(database)))
    assert [item["content"] for item in queries._ai_conversation_changes(Principal())] == [
        "own-session"
    ]
    assert queries._ai_conversation_changes(Principal(id=0)) == []


@pytest.mark.asyncio
async def test_device_update_persists_scoped_row_and_leaves_other_user_token(database):
    with database.begin() as db:
        db.add_all(
            [
                MobileDeviceToken(user_id=71, fcm_token="fixture-token", device_label="old"),
                MobileDeviceToken(user_id=72, fcm_token="other-token", device_label="other"),
            ]
        )
    now = utc_now_naive()
    component = DeviceRoutes(
        replace(
            routes._devices.ports,
            database=_database_port(database),
            now=lambda: now,
            ensure_mobile_device_table=lambda: None,
        ),
        _principal,
    )
    result = await component.mobile_device_register(
        routes.DeviceRegisterBody(
            fcm_token="fixture-token", push_token="new-push", device_label="new"
        ),
        Principal(),
    )
    assert _payload(result)["success"] is True
    with database() as db:
        rows = db.query(MobileDeviceToken).order_by(MobileDeviceToken.user_id).all()
        assert [(row.user_id, row.device_label) for row in rows] == [(71, "new"), (72, "other")]
        assert rows[0].push_token == "new-push"
        assert rows[0].updated_at == now


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_employee_http_rechecks_real_host_session(database, monkeypatch, revoked):
    import app.db as database_module

    monkeypatch.setenv("SECRET_KEY", "synthetic-mobile-stream-session-key")
    monkeypatch.setattr(database_module, "HostSessionLocal", database)
    monkeypatch.setattr("app.db.session.SessionLocal", database)
    with database.begin() as db:
        db.add(
            User(
                id=71,
                username="synthetic-admin",
                password="unused",
                role="admin",
                tier="admin",
                is_active=True,
            )
        )
        db.add(
            HostSession(
                session_id="synthetic-session",
                user_id=71,
                account_kind="admin",
                market_is_admin=True,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )
    token = issue_mobile_tokens(
        user_id=71, session_id="synthetic-session", account_kind="admin", username="synthetic-admin"
    )["access_token"]
    if revoked:
        with database.begin() as db:
            db.query(HostSession).filter_by(session_id="synthetic-session").delete()
    execute = MagicMock(return_value={"success": True, "result": {"response": "synthetic reply"}})
    monkeypatch.setattr(
        "app.application.employee_runtime.executor.execute_employee_task_local", execute
    )
    app = FastAPI()
    app.include_router(routes.extension_router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://mobile.test"
    ) as client:
        response = await client.post(
            "/employees/fixture/chat/stream",
            json={"message": "fake"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == (401 if revoked else 200)
    assert execute.call_count == (0 if revoked else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 503])
async def test_admin_proxy_owns_client_and_resolves_later_base_url(monkeypatch, status):
    requests: list[httpx.Request] = []
    clients: list[httpx.AsyncClient] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, json={"detail": "fixture"})

    def client(timeout: float) -> httpx.AsyncClient:
        instance = httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=timeout)
        clients.append(instance)
        return instance

    component = AdminRoutes(replace(routes._admin.ports, client=client), _principal)
    monkeypatch.setattr(routes, "_modstore_platform_base", lambda: "https://synthetic.invalid")
    monkeypatch.setattr(routes, "_modstore_admin_token", lambda: "synthetic-token")
    result = await component._modstore_admin_proxy("GET", "/fixture")
    assert result["ok"] is (status == 200)
    assert str(requests[0].url) == "https://synthetic.invalid/fixture"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-token"
    assert clients[0].is_closed


@pytest.mark.asyncio
async def test_admin_proxy_cancel_closes_client_and_propagates():
    entered = asyncio.Event()
    pending = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        entered.set()
        await pending.wait()
        return httpx.Response(200)

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    component = AdminRoutes(
        replace(
            routes._admin.ports,
            client=lambda timeout: client,
            modstore_platform_base=lambda: "https://synthetic.invalid",
        ),
        _principal,
    )
    task = asyncio.create_task(component._modstore_admin_proxy("GET", "/fixture"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.is_closed
    finally:
        task.cancel()
        await client.aclose()


@pytest.mark.asyncio
async def test_contact_background_task_awaits_injected_async_processor():
    db = MagicMock()
    service = MagicMock(spec=ImApplicationService)
    service._ensure_enterprise_dedicated_cs_user.return_value = SimpleNamespace(id=72)
    service.get_or_create_direct.return_value = {"id": 9}
    service.send_message.return_value = {"message": {"id": 18, "created_at": "synthetic"}}
    process = AsyncMock()
    component = ContactRoutes(
        ContactRoutesPorts(
            mobile_group_mode=lambda request: "enterprise",
            fixed_contacts=lambda mode: {},
            mobile_request_user_id=lambda request, user: 71,
            im_service=lambda db: service,
            database=lambda: db,
            process_cs_message=process,
        ),
        _principal,
    )
    background = BackgroundTasks()
    response = await component.post_cs_message(
        _request(), {"body": "synthetic"}, background, Principal()
    )
    assert _payload(response)["data"]["message_id"] == "18"
    process.assert_not_awaited()
    await background()
    process.assert_awaited_once_with(9, 71, 18, "synthetic")


@pytest.mark.parametrize("first", ["mobile_api", "mobile_api_extensions"])
def test_either_cold_import_order_registers_complete_api_once(first):
    code = f"""
from fastapi import FastAPI
from app.fastapi_routes import {first}
from app.fastapi_routes import mobile_api, mobile_api_extensions
app = FastAPI()
app.include_router(mobile_api.router)
schema = app.openapi()
operations = [op for path in schema["paths"].values() for verb, op in path.items() if verb in {{"get", "post", "put", "delete", "patch"}}]
assert len(operations) == 100
assert len({{op["operationId"] for op in operations}}) == 100
assert mobile_api_extensions.get_mobile_user is mobile_api.get_mobile_user
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=45
    )
    assert result.returncode == 0, result.stderr


def test_components_import_without_loading_http_composition_root():
    code = """
import importlib
import importlib.abc
import sys
class RejectRoot(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {"app.fastapi_routes.mobile_api", "app.fastapi_routes.mobile_api_extensions"}:
            raise AssertionError("component tried to load its composition root")
sys.meta_path.insert(0, RejectRoot())
for module in ("access", "read_models", "employee_catalog", "routes_worklists", "routes_devices", "routes_pairing", "routes_relay", "routes_support", "routes_workspace", "routes_admin", "routes_circle", "routes_employee_chat", "routes_ai_groups", "routes_cs_contacts", "routes_payment", "routes_super_employee", "routes_sync"):
    importlib.import_module("app.fastapi_routes.mobile_extensions." + module)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=45
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_original_dependency_object_still_overrides_registered_endpoints():
    app = FastAPI()
    app.include_router(routes.extension_router)
    app.dependency_overrides[mobile_api.get_mobile_user] = lambda: None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://mobile.test"
    ) as client:
        for path in (
            "/customers",
            "/shipments",
            "/approval/requests",
            "/cs/info",
            "/sync/status",
            "/payment/plans",
        ):
            response = await client.get(path)
            assert response.status_code == 401
