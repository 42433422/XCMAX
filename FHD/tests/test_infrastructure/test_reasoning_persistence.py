"""推理文本持久化：作为思考步骤下发，且绝不混入正文。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.domain.shared_services.conversation.modstore_adapter import (
    ModstorePlatformAdapter,
)
from app.infrastructure import chat_stream_lifetime as life
from app.infrastructure.llm.providers.modstore_provider import ModstoreProvider
from app.infrastructure.llm.reasoning_stream import (
    REASONING_NOTE_LIMIT,
    REASONING_NOTE_PREFIX,
    publish_reasoning,
)


class _Adapter:
    def __init__(self, chunks: list[dict]) -> None:
        self.chunks = chunks

    async def stream_chat_completion(self, messages, **kwargs):
        for chunk in self.chunks:
            yield json.dumps(chunk, ensure_ascii=False)
        yield "[DONE]"


@pytest.mark.asyncio
async def test_reasoning_is_published_as_thinking_note_not_body():
    lifetime = life.StreamLifetime()
    notes: list[str] = []
    lifetime.observe_notes(notes.append)
    provider = ModstoreProvider(
        _Adapter(
            [
                {"choices": [{"delta": {"reasoning_content": "先核对文件"}}]},
                {"choices": [{"delta": {"content": "导入完成"}}]},
            ]
        )
    )
    token = life.current_lifetime.set(lifetime)
    try:
        body = [chunk async for chunk in provider.stream_chat_completion([])]
    finally:
        life.current_lifetime.reset(token)
    assert body == ["导入完成"]
    assert notes == [f"{REASONING_NOTE_PREFIX}先核对文件"]


@pytest.mark.asyncio
async def test_reasoning_without_stream_context_is_silent():
    provider = ModstoreProvider(_Adapter([{"choices": [{"delta": {"reasoning_content": "想一下"}}]}]))
    body = [chunk async for chunk in provider.stream_chat_completion([])]
    assert body == []


def test_full_response_keeps_reasoning_out_of_content():
    adapter = ModstorePlatformAdapter()
    pieces: list[str] = []
    reasoning: list[str] = []
    adapter._absorb_stream_payload(
        json.dumps({"delta": {"reasoning_content": "想一想"}}),
        None,
        pieces,
        {},
        reasoning,
    )
    adapter._absorb_stream_payload(
        json.dumps({"choices": [{"delta": {"content": "答"}}]}),
        None,
        pieces,
        {},
        reasoning,
    )
    response = adapter._normalize_collected(pieces, "provider", "model", {}, 100, "".join(reasoning))
    assert "".join(pieces) == "答"
    assert response["reasoning_content"] == "想一想"


def test_publish_reasoning_truncates_long_text():
    lifetime = life.StreamLifetime()
    notes: list[str] = []
    lifetime.observe_notes(notes.append)
    token = life.current_lifetime.set(lifetime)
    try:
        publish_reasoning("甲" * (REASONING_NOTE_LIMIT + 20))
    finally:
        life.current_lifetime.reset(token)
    assert len(notes) == 1
    assert notes[0].startswith(REASONING_NOTE_PREFIX)
    assert notes[0].endswith("…")


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["error", "close", "cancel"])
@pytest.mark.parametrize("provider_kind", ["modstore", "sdk"])
async def test_partial_reasoning_survives_interrupted_stream(ending, provider_kind, monkeypatch):
    class InterruptedAdapter:
        async def stream_chat_completion(self, messages, **kwargs):
            yield json.dumps({"choices": [{"delta": {"reasoning_content": "已核对"}}]})
            yield json.dumps({"choices": [{"delta": {"content": "部分回答"}}]})
            if ending == "cancel":
                raise asyncio.CancelledError
            raise ConnectionError("stream disconnected")

    lifetime = life.StreamLifetime()
    notes: list[str] = []
    lifetime.observe_notes(notes.append)
    token = life.current_lifetime.set(lifetime)
    if provider_kind == "sdk":
        from app.infrastructure.llm import client
        from app.infrastructure.llm.providers.openai_sdk_provider import (
            OpenAISdkProvider,
        )

        def chunks():
            yield {"choices": [{"delta": {"reasoning_content": "已核对"}}]}
            yield {"choices": [{"delta": {"content": "部分回答"}}]}
            if ending == "cancel":
                raise asyncio.CancelledError
            raise ConnectionError("stream disconnected")

        fake = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kwargs: chunks(),
                )
            )
        )
        monkeypatch.setattr(client, "require_api_key", lambda: None)
        monkeypatch.setattr(client, "get_llm_client", lambda: fake)
        stream = OpenAISdkProvider().stream_chat_completion([], model="fixture")
    else:
        stream = ModstoreProvider(InterruptedAdapter()).stream_chat_completion([])
    try:
        assert await anext(stream) == "部分回答"
        if ending == "error":
            with pytest.raises(ConnectionError, match="stream disconnected"):
                await anext(stream)
        elif ending == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await anext(stream)
        else:
            await stream.aclose()
        assert notes == [f"{REASONING_NOTE_PREFIX}已核对"]
        await stream.aclose()
        assert len(notes) == 1
    finally:
        await stream.aclose()
        life.current_lifetime.reset(token)


@pytest.mark.asyncio
async def test_note_delivery_failure_does_not_replace_stream_error(monkeypatch):
    class BrokenAdapter:
        async def stream_chat_completion(self, messages, **kwargs):
            yield json.dumps({"choices": [{"delta": {"reasoning_content": "部分思考"}}]})
            raise ConnectionError("original stream error")

    def failed_note(text):
        raise RuntimeError("note delivery failed")

    monkeypatch.setattr(life, "publish_stream_note", failed_note)
    with pytest.raises(ConnectionError, match="original stream error"):
        await anext(ModstoreProvider(BrokenAdapter()).stream_chat_completion([]))
