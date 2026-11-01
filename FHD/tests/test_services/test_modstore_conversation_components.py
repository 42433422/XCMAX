"""Credential, cache and stream ownership across the market LLM boundary."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.db_base import Base
from app.db.models.user import Session, User
from app.domain.shared_services.conversation import modstore_adapter as facade
from app.fastapi_routes import market_account as market
from app.utils.time import utc_now_naive


@pytest.fixture(autouse=True)
def isolate_credentials(monkeypatch):
    monkeypatch.delenv("MODSTORE_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("MODSTORE_USER_ID", raising=False)
    monkeypatch.delenv("XCAGI_MARKET_BASE_URL", raising=False)
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "0")
    monkeypatch.setattr(facade, "_CATALOG_CACHE", {})
    monkeypatch.setattr(market, "_MARKET_SESSION_TOKENS", {})
    monkeypatch.setattr(market, "_MARKET_SESSION_REFRESH_TOKENS", {})


def adapter():
    return facade.ModstorePlatformAdapter(
        platform_url="https://market.invalid", auth_token="synthetic-old"
    )


def mock_async_transport(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


@pytest.mark.asyncio
async def test_refresh_credential_reaches_existing_async_connection(monkeypatch):
    sent = []

    def respond(request):
        sent.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"configured": True})

    mock_async_transport(monkeypatch, respond)
    current = adapter()
    monkeypatch.setattr(market, "session_market_token", lambda sid: "synthetic-new")
    try:
        await current.get_credential_status()
        connection = current._client
        assert current.refresh_token_from_session("synthetic-session") is True
        await current.get_credential_status()
        assert current._client is connection
        assert sent == ["Bearer synthetic-old", "Bearer synthetic-new"]
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_cleared_credential_is_not_retained_by_pooled_http_headers(monkeypatch):
    sent = []

    def respond(request):
        sent.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"providers": []})

    mock_async_transport(monkeypatch, respond)
    current = adapter()
    try:
        await current.get_available_providers()
        current.auth_token = ""
        await current.get_available_providers()
        assert sent == ["Bearer synthetic-old", None]
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_late_catalog_response_keeps_its_original_credential_cache_key(monkeypatch):
    entered, resume = asyncio.Event(), asyncio.Event()

    async def respond(request):
        assert request.headers["Authorization"] == "Bearer synthetic-old"
        entered.set()
        await resume.wait()
        return httpx.Response(
            200,
            json={
                "providers": [
                    {
                        "provider": "fixture",
                        "models_detailed": [{"id": "visible", "category": "vlm"}],
                    }
                ]
            },
        )

    mock_async_transport(monkeypatch, respond)
    current = adapter()
    query = asyncio.create_task(current._model_vision_support("fixture", "visible"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        current.auth_token = "synthetic-new"
        resume.set()
        assert await query is True
        assert current._cached_catalog() is None
        current.auth_token = "synthetic-old"
        assert current._cached_catalog()["providers"][0]["provider"] == "fixture"
    finally:
        resume.set()
        await query
        await current.close()


@pytest.fixture
def session_database(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions.begin() as db:
        for uid in (71, 72, 73):
            db.add(User(id=uid, username=f"synthetic-{uid}", password="unused", is_active=True))
            db.add(
                Session(
                    session_id=f"synthetic-session-{uid}",
                    user_id=uid,
                    created_at=utc_now_naive() + timedelta(seconds=uid),
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    market_access_token=f"synthetic-owned-{uid}" if uid != 73 else None,
                )
            )
        db.add(
            Session(
                session_id="synthetic-session-empty",
                user_id=71,
                expires_at=utc_now_naive() + timedelta(hours=1),
            )
        )

    @contextmanager
    def database():
        with sessions() as db:
            yield db

    monkeypatch.setattr("app.db.session.get_db", database)
    monkeypatch.setattr("app.db.session.get_host_db", database)
    monkeypatch.setattr("app.db.HostSessionLocal", sessions)
    monkeypatch.setattr("app.infrastructure.session.session_manager.get_host_db", database)
    monkeypatch.setattr("app.application.session_account_meta.get_host_db", database)
    try:
        yield
    finally:
        engine.dispose()


def test_unknown_session_cannot_borrow_another_accounts_latest_token(session_database):
    current = facade.ModstorePlatformAdapter.from_session(session_id="synthetic-unknown-session")

    assert current.auth_token == ""


def test_known_session_fallback_remains_scoped_to_its_owner(session_database):
    current = facade.ModstorePlatformAdapter.from_session(session_id="synthetic-session-empty")

    assert current.auth_token == "synthetic-owned-71"


@pytest.mark.asyncio
async def test_async_stream_accepts_compact_sse_and_stops_at_done(monkeypatch):
    def respond(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream"},
            text='data:{"delta":"first"}\n\ndata: [DONE]\n\ndata: never\n\n',
        )

    mock_async_transport(monkeypatch, respond)
    current = adapter()
    try:
        chunks = [chunk async for chunk in current.stream_chat_completion([])]
        assert chunks == ['{"delta":"first"}']
    finally:
        await current.close()


def test_new_sse_event_resets_metadata_filter_after_blank_separator():
    response = httpx.Response(
        200,
        text='event: meta\ndata: {"provider":"fixture"}\n\ndata: {"delta":"visible"}\n\n',
    )

    assert list(facade._iter_market_sse_data_payloads(response)) == ['{"delta":"visible"}']


@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize(
    "status,message",
    [
        (400, "模型服务未接受请求，请查看模型状态；平台模型配置请联系管理员核对。"),
        (401, "模型服务鉴权失败，请查看模型状态；平台模型授权请联系管理员核对。"),
        (503, "模型服务暂不可用，请查看模型状态后重试。"),
        (None, "模型服务请求失败，请查看模型状态后重试。"),
    ],
)
@pytest.mark.asyncio
async def test_named_gateway_error_preserves_diagnosis_and_never_retries(
    monkeypatch, mode, status, message
):
    from app.fastapi_routes.xcagi_compat_chat_helpers import _xcagi_chat_http_exc
    from app.infrastructure.modstore_transport import MarketModelError

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            text=f"event: error\ndata: {json.dumps({'ok': False, 'error': message, 'status': status})}\n\n",
        )

    sync_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: sync_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    mock_async_transport(monkeypatch, respond)
    current = adapter()
    try:
        with pytest.raises(MarketModelError) as failure:
            if mode == "sync":
                list(
                    facade.ModstoreOpenAICompatibleClient(current).chat.completions.create(
                        messages=[], stream=True
                    )
                )
            else:
                [chunk async for chunk in current.stream_chat_completion([])]
        projected = _xcagi_chat_http_exc(failure.value)
        assert (projected.status_code, projected.detail) == (status or 502, message)
        assert len(requests) == 1
    finally:
        await current.close()


def test_closing_openai_stream_closes_retained_upstream_generator(monkeypatch):
    released = []

    def upstream():
        try:
            yield '{"delta":"first"}'
            yield '{"delta":"second"}'
        finally:
            released.append(True)

    source = upstream()
    current = adapter()
    monkeypatch.setattr(current, "stream_chat_completion_sync", lambda **kwargs: source)
    stream = facade.ModstoreOpenAICompatibleClient(current).chat.completions.create(
        messages=[], stream=True
    )
    try:
        assert next(stream).choices[0].delta.role == "assistant"
        assert next(stream).choices[0].delta.content == "first"
        stream.close()
        assert released == [True]
    finally:
        source.close()


@pytest.mark.parametrize("mode", ["sync", "async", "sync-stream", "async-stream"])
@pytest.mark.asyncio
async def test_each_completion_transport_uses_current_credential_and_payload(monkeypatch, mode):
    sent = []

    def respond(request):
        sent.append((request.headers.get("authorization"), json.loads(request.content)))
        if request.url.path.endswith("/stream"):
            return httpx.Response(200, text='data: {"delta":"reply"}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, json={"content": "reply", "usage": {"total_tokens": 3}})

    sync_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: sync_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    mock_async_transport(monkeypatch, respond)
    monkeypatch.setattr(facade, "neuro_notify_ai_model_roundtrip", lambda **kwargs: None)
    current = adapter()
    current.user_id = 71
    messages = [{"role": "user", "content": "synthetic request"}]
    try:
        for token in ("synthetic-old", "synthetic-new", ""):
            current.auth_token = token
            if mode == "sync":
                response = current.chat_completion_sync(messages, model="fixture/model")
                assert response["choices"][0]["message"]["content"] == "reply"
            elif mode == "async":
                response = await current.chat_completion(messages, model="fixture/model")
                assert response["choices"][0]["message"]["content"] == "reply"
            elif mode == "sync-stream":
                assert list(
                    current.stream_chat_completion_sync(messages, model="fixture/model")
                ) == ['{"delta":"reply"}']
            else:
                assert [
                    chunk
                    async for chunk in current.stream_chat_completion(
                        messages, model="fixture/model"
                    )
                ] == ['{"delta":"reply"}']
        assert [auth for auth, _ in sent] == ["Bearer synthetic-old", "Bearer synthetic-new", None]
        assert all(
            payload["provider"] == "fixture"
            and payload["model"] == "model"
            and payload["user_id"] == 71
            and payload["messages"] == messages
            for _, payload in sent
        )
    finally:
        await current.close()


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.asyncio
async def test_failover_uses_real_discovery_and_preserves_attempt_policy(monkeypatch, asynchronous):
    monkeypatch.setenv("XCAGI_LLM_CHAT_FAILOVER", "1")
    calls = []

    def respond(request):
        if request.method == "GET":
            if request.url.path.endswith("/status"):
                return httpx.Response(
                    200, json={"providers": [{"provider": "backup", "available": True}]}
                )
            if request.url.path.endswith("/catalog"):
                return httpx.Response(
                    200, json={"providers": [{"provider": "backup", "models": ["second"]}]}
                )
            assert request.url.path.endswith("/resolve-chat-default")
            return httpx.Response(200, json={"provider": "backup", "model": "second"})
        payload = json.loads(request.content)
        calls.append((payload["provider"], payload["model"], payload["allow_failover"]))
        assert request.headers["Authorization"] == "Bearer synthetic-old"
        if payload["provider"] == "primary":
            return httpx.Response(429, text="synthetic quota exhausted")
        return httpx.Response(200, json={"content": "backup reply"})

    sync_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: sync_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    mock_async_transport(monkeypatch, respond)
    monkeypatch.setattr(facade, "neuro_notify_ai_model_roundtrip", lambda **kwargs: None)
    current = adapter()
    try:
        result = (
            await current.chat_completion([], provider="primary", model="first")
            if asynchronous
            else current.chat_completion_sync([], provider="primary", model="first")
        )
        assert result["choices"][0]["message"]["content"] == "backup reply"
        assert calls == [("primary", "first", True), ("backup", "second", False)]
    finally:
        await current.close()


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_async_stream_closes_http_body_on_close_or_cancellation(monkeypatch, cancel):
    waiting = asyncio.Event()

    class Body(httpx.AsyncByteStream):
        closed = 0

        async def __aiter__(self):
            yield b'data: {"delta":"first"}\n\n'
            waiting.set()
            await asyncio.Event().wait()

        async def aclose(self):
            self.closed += 1

    body = Body()
    mock_async_transport(monkeypatch, lambda request: httpx.Response(200, stream=body))
    current = adapter()
    source = current.stream_chat_completion([])
    try:
        assert await anext(source) == '{"delta":"first"}'
        if cancel:
            pending = asyncio.create_task(anext(source))
            await asyncio.wait_for(waiting.wait(), 2)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            await source.aclose()
        assert body.closed == 1
    finally:
        await source.aclose()
        await current.close()


def test_partial_sync_stream_is_closed_without_retrying_another_model(monkeypatch):
    calls = []

    class Body(httpx.SyncByteStream):
        closed = 0

        def __iter__(self):
            yield b'data: {"delta":"first"}\n\n'
            raise httpx.ReadError("synthetic interrupted body")

        def close(self):
            self.closed += 1

    body = Body()

    def respond(request):
        calls.append(json.loads(request.content)["provider"])
        return httpx.Response(200, stream=body)

    sync_type = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: sync_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    current = adapter()
    monkeypatch.setattr(
        current,
        "_list_chat_failover_candidates_sync",
        lambda *args: [("primary", "first"), ("backup", "second")],
    )
    source = current.stream_chat_completion_sync([])

    assert next(source) == '{"delta":"first"}'
    with pytest.raises(httpx.ReadError, match="interrupted body"):
        next(source)
    assert calls == ["primary"]
    assert body.closed == 1


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("supports_images", [False, True])
@pytest.mark.asyncio
async def test_image_preparation_keeps_vision_or_converts_through_local_ocr(
    monkeypatch, asynchronous, supports_images
):
    from app.application.workflow import multimodal_user_content

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read this synthetic image"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        }
    ]
    converted = [{"role": "user", "content": "synthetic local OCR result"}]
    ocr = Mock(return_value=converted)
    monkeypatch.setattr(multimodal_user_content, "replace_image_parts_with_ocr_text", ocr)
    current = adapter()
    if asynchronous:
        vision = AsyncMock(return_value=supports_images)
        monkeypatch.setattr(current, "_model_vision_support", vision)
        result = await current._prepare_messages(messages, "fixture", "selected")
        vision.assert_awaited_once_with("fixture", "selected")
    else:
        vision = Mock(return_value=supports_images)
        monkeypatch.setattr(current, "_model_vision_support_sync", vision)
        result = current._prepare_messages_sync(messages, "fixture", "selected")
        vision.assert_called_once_with("fixture", "selected")
    if supports_images:
        assert result is messages
        ocr.assert_not_called()
    else:
        assert result is converted
        ocr.assert_called_once_with(
            messages, model_label="fixture/selected", model_confirmed_text_only=True
        )


def test_capabilities_import_without_importing_public_adapter():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib, sys; prefix='app.application.'; "
            "[importlib.import_module(prefix+'market_llm.'+name) for name in "
            "('protocols','authentication','catalog','multimodal','responses','routing',"
            "'completions','streaming','account_queries')]; "
            "importlib.import_module('app.legacy.market_llm.openai_compat'); assert 'app.domain.shared_services.conversation.modstore_adapter' not in sys.modules",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout


@pytest.fixture
def request_market(monkeypatch):
    """Real request adapter with synthetic account credentials and HTTP transport."""
    monkeypatch.setenv("MODSTORE_PLATFORM_URL", "https://market.invalid")
    monkeypatch.setenv("LLM_PROVIDER", "stale-local")
    monkeypatch.setenv("LLM_MODEL", "stale-model")
    monkeypatch.setattr(
        facade.authentication,
        "resolve_credential",
        lambda *args: facade.authentication.Credential("synthetic-account", "session"),
    )
    sync_type = httpx.Client

    def build(handler):
        monkeypatch.setattr(
            httpx,
            "Client",
            lambda **kwargs: sync_type(transport=httpx.MockTransport(handler), **kwargs),
        )
        mock_async_transport(monkeypatch, handler)
        return facade.create_modstore_openai_client_from_request(Mock())

    return build


@pytest.mark.parametrize("source", ["platform_configuration", "byok", "preference"])
def test_main_chat_auto_uses_server_route_before_local_fallback(
    request_market, monkeypatch, source
):
    from app.legacy.chat import legacy_chat_adapter as planner

    requests = []

    def respond(request):
        requests.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer synthetic-account"
        if request.method == "GET":
            assert request.url.path == "/api/llm/resolve-chat-default"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "provider": "openai",
                    "model": "server-default",
                    "source": source,
                },
            )
        body = json.loads(request.content)
        assert (body["provider"], body["model"]) == ("openai", "server-default")
        return httpx.Response(
            200,
            text='event: delta\ndata: {"delta":"测试成功"}\n\nevent: done\ndata: {"ok":true,"content":"测试成功"}\n\n',
        )

    client = request_market(respond)
    assert requests == []
    monkeypatch.setattr(planner, "_get_workflow_tool_registry", lambda: [])
    events = list(
        planner.chat_stream_sse_events(
            "UX体验测试：只回复‘测试成功’，不要执行任何业务操作。", client=client
        )
    )
    assert [event["type"] for event in events] == ["token", "done"]
    assert events[0]["text"] == "测试成功"
    assert requests == [("GET", "/api/llm/resolve-chat-default"), ("POST", "/api/llm/chat/stream")]


@pytest.mark.parametrize("stream", [False, True])
def test_explicit_model_bypasses_unavailable_server_default(request_market, stream):
    requests = []

    def respond(request):
        requests.append(request.method)
        assert request.method == "POST", "Explicit selection must not depend on default discovery"
        payload = json.loads(request.content)
        assert (payload["provider"], payload["model"]) == ("byok", "chosen")
        return (
            httpx.Response(200, text='data: {"delta":"selected"}\n\n')
            if stream
            else httpx.Response(200, json={"content": "selected"})
        )

    client = request_market(respond)
    result = client.chat.completions.create(messages=[], model="byok/chosen", stream=stream)
    if stream:
        assert list(result)[-1].choices[0].delta.content == "selected"
    else:
        assert result.choices[0].message.content == "selected"
    assert requests == ["POST"]


@pytest.mark.parametrize(
    "status,payload",
    [
        (400, {"detail": "synthetic-private"}),
        (503, {}),
        (200, {"ok": False}),
        (200, {"ok": True, "provider": "openai"}),
    ],
)
def test_unresolved_default_never_sends_stale_local_model(request_market, status, payload):
    requests = []

    def respond(request):
        requests.append(request.method)
        assert request.method == "GET"
        return httpx.Response(status, json=payload)

    client = request_market(respond)
    with pytest.raises(ValueError) as failure:
        list(client.chat.completions.create(messages=[], stream=True))
    assert "synthetic-private" not in str(failure.value)
    assert requests == ["GET"]


def test_server_default_cache_does_not_cross_account_credentials(request_market):
    accounts = []

    def respond(request):
        account = request.headers["Authorization"]
        accounts.append(account)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "provider": "openai",
                "model": "first" if account.endswith("synthetic-account") else "second",
            },
        )

    client = request_market(respond)
    assert client.default_model == "first"
    assert client.default_provider == "openai"
    client.adapter.auth_token = "synthetic-next-account"
    assert client.default_model == "second"
    assert accounts == ["Bearer synthetic-account", "Bearer synthetic-next-account"]


def test_explicit_session_defaults_override_host_environment(request_market):
    request_market(
        lambda request: pytest.fail("Explicit session selection must not discover defaults")
    )
    selected = facade.ModstorePlatformAdapter.from_request(
        Mock(), default_provider="explicit", default_model="selected"
    )
    client = facade.ModstoreOpenAICompatibleClient(selected)
    assert (client.default_provider, client.default_model) == ("explicit", "selected")
    # Process-configured direct adapters retain their existing environment route.
    assert facade.ModstorePlatformAdapter().resolve_default_route() == (
        "stale-local",
        "stale-model",
    )


@pytest.mark.parametrize("mode", ["async", "async-stream"])
@pytest.mark.asyncio
async def test_async_adapter_uses_account_default(request_market, mode):
    methods = []

    def respond(request):
        methods.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"ok": True, "provider": "openai", "model": "server"})
        payload = json.loads(request.content)
        assert (payload["provider"], payload["model"]) == ("openai", "server")
        return (
            httpx.Response(200, text='data: {"delta":"reply"}\n\n')
            if mode == "async-stream"
            else httpx.Response(200, json={"content": "reply"})
        )

    current = request_market(respond).adapter
    try:
        if mode == "async":
            assert (await current.chat_completion([]))["choices"][0]["message"][
                "content"
            ] == "reply"
        else:
            assert [value async for value in current.stream_chat_completion([])] == [
                '{"delta":"reply"}'
            ]
        assert methods == ["GET", "POST"]
    finally:
        await current.close()


@pytest.mark.asyncio
async def test_async_default_route_and_chat_keep_the_same_credential_snapshot(request_market):
    observed = []

    def respond(request):
        observed.append((request.method, request.headers["Authorization"]))
        if request.method == "GET":
            return httpx.Response(
                200, json={"ok": True, "provider": "openai", "model": "owned-model"}
            )
        assert json.loads(request.content)["model"] == "owned-model"
        return httpx.Response(200, json={"content": "reply"})

    current = request_market(respond).adapter
    current._default_route_lock.acquire()
    task = asyncio.create_task(current.chat_completion([]))
    # Let the async request capture its credential, then hold model discovery
    # until another session refresh changes the adapter's mutable token.
    await asyncio.sleep(0)
    current.auth_token = "synthetic-next-account"
    current._default_route_lock.release()
    try:
        assert (await task)["choices"][0]["message"]["content"] == "reply"
        assert observed == [
            ("GET", "Bearer synthetic-account"),
            ("POST", "Bearer synthetic-account"),
        ]
    finally:
        await current.close()


@pytest.mark.parametrize("stream", [False, True])
def test_sync_default_route_and_chat_keep_the_same_credential_snapshot(request_market, stream):
    observed = []

    def respond(request):
        observed.append((request.method, request.headers["Authorization"]))
        if request.method == "GET":
            current.auth_token = "synthetic-next-account"
            return httpx.Response(
                200, json={"ok": True, "provider": "openai", "model": "owned-model"}
            )
        assert json.loads(request.content)["model"] == "owned-model"
        return (
            httpx.Response(200, text='data: {"delta":"reply"}\n\n')
            if stream
            else httpx.Response(200, json={"content": "reply"})
        )

    current = request_market(respond).adapter
    if stream:
        assert list(current.stream_chat_completion_sync([])) == ['{"delta":"reply"}']
    else:
        assert current.chat_completion_sync([])["choices"][0]["message"]["content"] == "reply"
    assert observed == [("GET", "Bearer synthetic-account"), ("POST", "Bearer synthetic-account")]


@pytest.fixture
def desktop_model_status_client(session_database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.legacy.routes.legacy_compat import _register_xcagi_compat_routes
    from app.utils.deployment import is_desktop_mode

    monkeypatch.setenv("XCAGI_DESKTOP_MODE", "1")
    monkeypatch.setenv("MODSTORE_PLATFORM_URL", "https://market.invalid")
    assert is_desktop_mode()
    application = FastAPI()
    _register_xcagi_compat_routes(application)
    with TestClient(application) as client:
        yield client


def test_desktop_status_and_chat_keep_account_route_through_failure_and_retry(
    desktop_model_status_client, monkeypatch, caplog
):
    from app.legacy.chat import legacy_chat_adapter as planner

    seen = []
    failed_once = False

    def respond(request):
        nonlocal failed_once
        token = request.headers["Authorization"]
        uid = 71 if token == "Bearer synthetic-owned-71" else 72
        assert token == f"Bearer synthetic-owned-{uid}"
        seen.append((request.method, request.url.path, uid))
        if request.method == "GET":
            assert request.url.path == "/api/llm/resolve-chat-default"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "provider": "openai",
                    "model": f"model-{uid}",
                    "api_key": "synthetic-secret",
                    "base_url": "https://private.invalid",
                },
            )
        assert request.method == "POST" and request.url.path == "/api/llm/chat/stream"
        payload = json.loads(request.content)
        assert (payload["provider"], payload["model"]) == ("openai", f"model-{uid}")
        assert payload["messages"][-1]["content"] == "只回复：会话验证成功。"
        if uid == 71 and not failed_once:
            failed_once = True
            return httpx.Response(
                200,
                text='event: error\ndata: {"ok":false,"status":503,"error":"synthetic-secret https://private.invalid"}\n\n',
            )
        return httpx.Response(
            200,
            text=f'event: delta\ndata: {{"delta":"会话{uid}验证成功"}}\n\nevent: done\ndata: {{"ok":true}}\n\n',
        )

    monkeypatch.setenv("LLM_PROVIDER", "stale-local")
    monkeypatch.setenv("LLM_MODEL", "stale-model")
    monkeypatch.setattr(planner, "_get_workflow_tool_registry", lambda: [])
    monkeypatch.setattr(
        facade,
        "_httpx_sync_client",
        lambda **kwargs: httpx.Client(transport=httpx.MockTransport(respond), **kwargs),
    )
    client = desktop_model_status_client
    forged = {"Authorization": "Bearer synthetic-foreign-market-token", "X-User-ID": "999"}
    for attempt, uid in enumerate((71, 72, 71)):
        client.cookies.set("session_id", f"synthetic-session-{uid}")
        status = client.get(
            "/api/conversation/model-status?user_id=999&session_id=synthetic-session-other",
            headers=forged,
        )
        assert status.status_code == 200
        assert status.json() == {"ok": True, "provider": "openai", "model": f"model-{uid}"}
        assert status.headers["Cache-Control"] == "no-store"
        response = client.post(
            "/api/ai/chat/stream",
            headers=forged,
            json={
                "message": "只回复：会话验证成功。",
                "system_prompt": "只回答用户文本，不执行工具。",
                "context": {"user_id": "999", "tenant_id": 999},
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        if attempt == 0:
            errors = [event for event in events if event["type"] == "error"]
            assert len(errors) == 1
            assert errors[0].get("status_code") == 503, errors
            assert errors[0]["message"] == "模型服务暂不可用，请查看模型状态后重试。"
            assert not any(event["type"] in {"token", "done"} for event in events)
        else:
            assert not any(event["type"] == "error" for event in events)
            assert (
                "".join(event.get("text", "") for event in events if event["type"] == "token")
                == f"会话{uid}验证成功"
            )
            done = [event for event in events if event["type"] == "done"]
            assert len(done) == 1
            assert done[0]["result"]["success"] is True
            assert done[0]["result"]["response"] == f"会话{uid}验证成功"
        assert "synthetic-secret" not in status.text + response.text + caplog.text
        assert "private.invalid" not in status.text + response.text + caplog.text
    assert seen == [
        (method, path, uid)
        for uid in (71, 72, 71)
        for method, path in (
            ("GET", "/api/llm/resolve-chat-default"),
            ("GET", "/api/llm/resolve-chat-default"),
            ("POST", "/api/llm/chat/stream"),
        )
    ]


@pytest.mark.parametrize("session_id", [None, "synthetic-unknown", "synthetic-session-73"])
def test_model_status_requires_real_session_and_its_market_binding(
    desktop_model_status_client, monkeypatch, session_id
):
    outbound = Mock(
        side_effect=AssertionError(
            "No discovery without both local identity and its market binding"
        )
    )
    monkeypatch.setattr(facade, "_httpx_sync_client", outbound)
    monkeypatch.setenv("MODSTORE_AUTH_TOKEN", "synthetic-host-token")
    if session_id:
        desktop_model_status_client.cookies.set("session_id", session_id)
    response = desktop_model_status_client.get(
        "/api/conversation/model-status", headers={"X-User-ID": "71"}
    )
    assert response.status_code == 401
    outbound.assert_not_called()


@pytest.mark.parametrize("status", [400, 401, 503])
def test_model_status_failure_never_exposes_upstream_error_body(
    desktop_model_status_client, monkeypatch, status
):
    monkeypatch.setattr(
        facade,
        "_httpx_sync_client",
        lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status,
                    json={"message": "synthetic-secret", "endpoint": "https://private.invalid"},
                )
            ),
            **kwargs,
        ),
    )
    desktop_model_status_client.cookies.set("session_id", "synthetic-session-71")
    response = desktop_model_status_client.get("/api/conversation/model-status")
    assert response.status_code == status
    assert "synthetic-secret" not in response.text
    assert "private.invalid" not in response.text
    assert "模型" in response.json()["detail"]
