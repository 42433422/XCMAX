"""知识库问答的 LLM 合成通道与安全回退。"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.application.dataset_rag_app_service import DatasetRagApplicationService
from app.infrastructure.llm import structured_output
from app.infrastructure.llm.knowledge_answer import (
    SYSTEM_PROMPT,
    get_kb_answer_llm_call,
)


def _service(tmp_path) -> DatasetRagApplicationService:
    return DatasetRagApplicationService(
        storage_path=tmp_path / "datasets.json",
        embedder=lambda text: [float(len(text)), 1.0],
        rebuild_workers_enabled=False,
        vector_index_backend_name="none",
    )


def test_message_text_handles_string_and_parts() -> None:
    plain = {"choices": [{"message": {"content": " 答案 [1] "}}]}
    parts = {
        "choices": [
            {
                "message": {
                    "content": [{"type": "text", "text": "合成"}, {"type": "text", "text": "答案"}]
                }
            }
        ]
    }
    assert structured_output.message_text(plain) == "答案 [1]"
    assert structured_output.message_text(parts) == "合成答案"
    assert structured_output.message_text(None) == ""


def test_complete_text_uses_shared_invoke_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_invoke(messages, **kwargs):
        captured["messages"] = messages
        captured["kwargs"] = kwargs
        return {"choices": [{"message": {"content": "依据资料 [1]"}}]}

    monkeypatch.setattr(structured_output.invoke, "chat_completion_openai_format", fake_invoke)
    text = asyncio.run(
        structured_output.complete_text([{"role": "user", "content": "hi"}], temperature=0.1)
    )
    assert text == "依据资料 [1]"
    assert captured["kwargs"]["temperature"] == 0.1


def test_answer_call_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XCAGI_KB_ANSWER_LLM", "0")
    assert get_kb_answer_llm_call() is None


def test_answer_call_none_when_provider_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_ANSWER_LLM", raising=False)
    with patch(
        "app.infrastructure.llm.providers.registry.get_active_provider",
        return_value=None,
    ):
        assert get_kb_answer_llm_call() is None


def test_answer_call_builds_grounded_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XCAGI_KB_ANSWER_LLM", raising=False)
    seen: dict = {}

    def fake_complete(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return "按资料 [1]，七天内可退。"

    with (
        patch(
            "app.infrastructure.llm.providers.registry.get_active_provider",
            return_value=object(),
        ),
        patch(
            "app.infrastructure.llm.structured_output.complete_text_sync",
            side_effect=fake_complete,
        ),
    ):
        call = get_kb_answer_llm_call()
        assert call is not None
        answer = call("几天内可退款？", "[1] 签收后七天内可申请")

    assert answer == "按资料 [1]，七天内可退。"
    assert seen["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert "签收后七天内可申请" in seen["messages"][1]["content"]
    assert "几天内可退款？" in seen["messages"][1]["content"]


def test_answer_falls_back_when_llm_returns_empty(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="refund.md",
        text="退款政策：签收后七天内可申请无理由退款。" * 5,
        tenant_id="t1",
        chunk_strategy="fixed",
    )
    with patch(
        "app.infrastructure.llm.knowledge_answer.get_kb_answer_llm_call",
        return_value=lambda _q, _p: "",
    ):
        result = service.answer(dataset_id="kb", query="退款政策", tenant_id="t1")
    assert result["answer"].startswith("根据知识库资料")
    assert result["citations"][0]["index"] == 1


def test_answer_uses_synthesized_text_with_citations(tmp_path) -> None:
    service = _service(tmp_path)
    service.ingest_document(
        dataset_id="kb",
        source="refund.md",
        text="退款政策：签收后七天内可申请无理由退款。" * 5,
        tenant_id="t1",
        chunk_strategy="fixed",
    )
    result = service.answer(
        dataset_id="kb",
        query="退款政策",
        tenant_id="t1",
        llm_call=lambda _q, _p: "签收后七天内可以申请 [1]。",
    )
    assert "签收后七天内可以申请" in result["answer"]
    assert result["citations"] and result["citations"][0]["index"] == 1
