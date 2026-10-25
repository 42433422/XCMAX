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
        for uid in (71, 72):
            db.add(User(id=uid, username=f"synthetic-{uid}", password="unused", is_active=True))
            db.add(
                Session(
                    session_id=f"synthetic-session-{uid}",
                    user_id=uid,
                    created_at=utc_now_naive() + timedelta(seconds=uid),
                    expires_at=utc_now_naive() + timedelta(hours=1),
                    market_access_token=f"synthetic-owned-{uid}",
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
            "('ports','authentication','catalog','multimodal','responses','routing',"
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
