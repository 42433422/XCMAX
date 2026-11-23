"""Owned conversation history and summary persistence outside retired planning."""

import copy
import json
import re
import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator import context_window_manager as windows
from app.application.ai_chat import dialogue_memory as memory


class RecordingProvider:
    provider_id = "test"
    model_name = "test"

    def __init__(self):
        self.summaries, self.requests = [], []

    async def chat_completion(self, **request):
        text = json.dumps(request["messages"], ensure_ascii=False)
        if "<message type=" in text:
            self.summaries.append(copy.deepcopy(request))
            facts = sorted(set(re.findall(r"FACT_\d+", text)))
            content = "已确认事实：" + " ".join(facts)
        else:
            self.requests.append(copy.deepcopy(request))
            content = json.dumps({"mode": "reply", "reply": "收到"}, ensure_ascii=False)
        return {
            "choices": [{"finish_reason": "stop", "message": {"content": content}}],
            "model": "test",
        }

    async def stream_chat_completion(self, **request):
        self.requests.append(copy.deepcopy(request))
        yield '{"mode":"reply","reply":"收到"}'


@pytest.fixture
def model_boundary(monkeypatch):
    provider = RecordingProvider()
    manager = windows.ContextWindowManager(token_budget=18_000, recent_keep=6)
    monkeypatch.setattr(windows, "get_context_window_manager", lambda: manager)
    monkeypatch.setattr(windows.ContextWindowManager, "_record_summary_usage", lambda *_: None)
    monkeypatch.setattr(
        "app.infrastructure.llm.providers.registry.get_active_provider", lambda **_: provider
    )
    return provider, manager


def long_history(count=180):
    return [
        {
            "role": "user" if index % 2 == 0 else "assistant",
            "content": (f"FACT_{index} " if index in {0, 85} else f"ROW_{index} ") + "中" * 100,
            "at": time.time(),
            "turn_id": str(index // 2),
        }
        for index in range(count)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("turn_count", [100, 220])
async def test_conversation_provider_uses_full_owned_history_once(
    monkeypatch, model_boundary, turn_count
):
    from app.domain.shared_services.conversation.api import ApiMixin
    from app.domain.shared_services.conversation.context import ConversationContext

    provider, _ = model_boundary
    rows = long_history(turn_count * 2)
    for index, row in enumerate(rows):
        row["content"] = f"EXACT_MESSAGE_{index:04d}"
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": rows[-400:], "summary": None})
    request_context = {
        "local_user_id": 1,
        "tenant_id": "tenant",
        "session_id": "full-transcript",
        "_chat_evidence_authorized": True,
        "_chat_history_messages": rows,
    }
    context = ConversationContext(
        user_id="scoped-user",
        conversation_history=[{"role": "assistant", "content": "STALE_LOCAL_ONLY"}],
        metadata={"request_context": request_context},
    )
    service = ApiMixin()
    service.model = "test"
    service._metadata_cache_hash = lambda _: ""
    service._build_context_prompt = lambda _: ""
    service.add_to_history = lambda *_: None

    assert (await service._call_ai("根据原文继续", context, {}))["action"] == "ai_response"
    wire = json.dumps(provider.requests[-1]["messages"], ensure_ascii=False)
    assert "STALE_LOCAL_ONLY" not in wire
    assert all(wire.count(row["content"]) == 1 for row in rows)
    assert not provider.summaries


def test_conversation_enrichment_does_not_accept_unowned_history(monkeypatch):
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": [], "summary": None})
    context = {
        "local_user_id": 1,
        "session_id": "owned",
        "_chat_history_messages": [{"role": "user", "content": "CLIENT_INJECTED_HISTORY"}],
    }
    current = {"role": "user", "content": [{"type": "text", "text": "分析图片"}]}
    result = memory.enrich_model_messages([current], "分析图片", context)
    assert result[-1] is current
    assert "CLIENT_INJECTED_HISTORY" not in json.dumps(result)


@pytest.mark.parametrize("authorized", [False, True])
@pytest.mark.parametrize("message", ["A", " A "])
def test_enrichment_excludes_current_turn_by_identity_not_equal_text(
    monkeypatch, authorized, message
):
    rows = [
        {"role": "user", "content": "A", "turn_id": "before", "at": time.time()},
        {"role": "assistant", "content": "A", "turn_id": "before", "at": time.time()},
        {"role": "user", "content": message, "turn_id": "current", "at": time.time()},
    ]
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": rows})
    context = {
        "local_user_id": 1,
        "session_id": "same",
        "turn_id": "current",
        "_chat_evidence_authorized": authorized,
        "_chat_history_messages": rows[:-1],
    }
    current = {"role": "user", "content": message}
    result = memory.enrich_model_messages([current], message, context)
    assert result[1:] == [
        {"role": "user", "content": "A"},
        {"role": "assistant", "content": "A"},
        current,
    ]


@pytest.mark.asyncio
async def test_conversation_rejects_stale_history_before_cached_reply(monkeypatch, model_boundary):
    from app.domain.shared_services.conversation import api
    from app.domain.shared_services.conversation.context import ConversationContext
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    provider, _ = model_boundary
    monkeypatch.setattr(memory, "_read", lambda *_: {"turns": [], "revision": 4})
    context = ConversationContext(
        user_id="owner",
        metadata={
            "request_context": {
                "local_user_id": 1,
                "session_id": "recalled",
                "_chat_evidence_authorized": True,
                "_chat_history_source": "sql",
                "_chat_history_revision": 3,
                "_chat_history_messages": [{"role": "user", "content": "RECALLED_FACT"}],
            }
        },
    )
    service = api.ApiMixin()
    service.model = "test"
    service._metadata_cache_hash = lambda _: "cached-key"
    monkeypatch.setattr(api, "_ai_response_cache", SimpleNamespace(get=lambda _: "RECALLED_FACT"))
    with pytest.raises(ConversationRevisionError):
        await service._call_ai("继续", context, {})
    assert not provider.requests


@pytest.mark.parametrize("count", [60, 120, 121, 240])
def test_old_excerpt_cache_never_discards_unsummarized_middle_or_120_boundary(count):
    rows = long_history(count)
    rows[count // 2]["content"] = "MIDDLE_ORIGINAL_FACT"
    legacy = {
        "text": "only the start",
        "count": count - 12,
        "fingerprint": memory._turns_fingerprint(rows[:-12]),
    }
    messages = memory._model_messages({"turns": rows, "summary": legacy}, "")
    assert "MIDDLE_ORIGINAL_FACT" in json.dumps(messages)
    assert len(messages) == count + 1
    assert memory._build_summary(rows, legacy) is None


def test_sql_projection_reads_only_uncovered_suffix_and_keeps_whole_long_messages(monkeypatch):
    from app.application import task_conversation_store
    from app.application.ai_chat import chat_evidence

    monkeypatch.setattr(
        task_conversation_store, "ConversationRevisionError", ValueError, raising=False
    )
    saved = {
        "kind": "langchain",
        "source": "sql",
        "revision": 3,
        "covered_through_id": 80,
        "count": 80,
        "text": "FACT_0",
    }
    monkeypatch.setattr(memory, "conversation_summary", lambda _: saved)
    calls = []

    def page(**request):
        calls.append(request)
        first = request["after_id"] == 80
        return {
            "session": {"revision": 3},
            "snapshot_latest_id": 84,
            "has_more": first,
            "next_after_id": 82 if first else None,
            "messages": [
                {"id": value, "role": "user" if value % 2 else "assistant", "content": "长" * 4000}
                for value in ([81, 82] if first else [83, 84])
            ],
        }

    result = chat_evidence._prepare_history(SimpleNamespace(get_conversation=page), {}, "s", 1)
    assert calls[0]["after_id"] == 80 and calls[1]["through_id"] == 84
    assert result["_chat_history_ids"] == [None, 81, 82, 83, 84]
    assert all("长" * 4000 in row["content"] for row in result["_chat_history_messages"][1:])
    assert result["_chat_history_messages"][0]["content"].endswith("FACT_0")


def test_later_finishing_old_summary_cannot_move_sql_cursor_backwards(monkeypatch):
    from contextlib import nullcontext

    previous = {
        "kind": "langchain",
        "source": "sql",
        "revision": 3,
        "covered_through_id": 90,
        "count": 90,
        "text": "newer",
    }
    data = {"revision": 3, "summary": previous}
    writes = []
    monkeypatch.setattr(memory, "_read", lambda *_: data)
    monkeypatch.setattr(memory, "_write", lambda *args: writes.append(args))
    monkeypatch.setattr(memory, "_lock", lambda _: nullcontext())
    context = {
        "local_user_id": 1,
        "session_id": "same",
        "_chat_history_source": "sql",
        "_chat_history_revision": 3,
        "_chat_history_ids": [None, 81, 82],
        "_chat_history_prior_summary": {"count": 80, "covered_through_id": 80},
    }
    history = [{"role": "user", "content": str(index)} for index in range(3)]
    memory.save_conversation_summary(context, history, 3, "older computation finished later")
    assert not writes and data["summary"] is previous
