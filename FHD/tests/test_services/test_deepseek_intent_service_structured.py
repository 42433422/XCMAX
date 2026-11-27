"""deepseek_intent_service 迁移后：坏 JSON 自动修复 + 终败降级。"""

from __future__ import annotations

from importlib import import_module
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.shared_services.deepseek_intent_service import DeepSeekIntentRecognizer


def _payload(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


@pytest.mark.asyncio
class TestStructuredRepair:
    async def test_bad_json_repaired_returns_intent(self):
        recognizer = DeepSeekIntentRecognizer(api_key="k")
        good = '{"intent": "shipment_generate", "confidence": 0.9, "slots": {}, "reasoning": "r"}'
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(side_effect=[_payload("垃圾输出"), _payload(good)]),
        ) as mock_call:
            result = await recognizer.recognize("REPAIR_UNIQUE_001 开一张发货单")
        assert result["intent"] == "shipment_generate"
        assert result["source"] == "deepseek"
        assert mock_call.await_count == 2
        # 第二次调用带上了修复 prompt
        repair_messages = mock_call.await_args_list[1].args[0]
        assert repair_messages[-1]["role"] == "user"
        assert "未通过 JSON" in repair_messages[-1]["content"]

    async def test_persistent_bad_json_falls_back(self):
        recognizer = DeepSeekIntentRecognizer(api_key="k")
        with patch(
            "app.infrastructure.llm.invoke.chat_completion_openai_format",
            new=AsyncMock(return_value=_payload("永远不是 JSON")),
        ):
            result = await recognizer.recognize("REPAIR_UNIQUE_002 开一张发货单")
        assert result["intent"] is None
        assert result["source"] == "deepseek"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entrypoint",
    [
        "app.mod_sdk.services",
        "app.services",
        "app.neuro_bus.integrations.intent_integration",
    ],
)
async def test_non_http_entrypoints_wire_structured_completion(monkeypatch, entrypoint):
    from app.domain.neuro.cognition import llm_port
    from app.domain.shared_services import unified_intent_recognizer
    from app.infrastructure.llm import invoke

    recognizer = DeepSeekIntentRecognizer(api_key="k")
    monkeypatch.setattr(
        unified_intent_recognizer, "get_unified_intent_recognizer", lambda: recognizer
    )
    complete = AsyncMock(
        return_value=_payload(
            '{"intent": "shipment_generate", "confidence": 0.9, "slots": {}, "reasoning": "r"}'
        )
    )
    monkeypatch.setattr(invoke, "chat_completion_openai_format", complete)
    module = import_module(entrypoint)
    # Exercise explicit composition even when infrastructure modules are already cached.
    monkeypatch.setattr(llm_port, "_source", None)
    if entrypoint.endswith("intent_integration"):
        entry = module.NeuroIntentRecognizer(reflex_arc=object())._base
    else:
        entry = module.get_unified_intent_recognizer()

    result = await entry.recognize(f"COLD_START_{entrypoint} 开一张发货单")

    assert result["intent"] == "shipment_generate"
    assert result["source"] == "deepseek"
    complete.assert_awaited_once()
