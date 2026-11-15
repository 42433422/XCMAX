"""语义兜底接入识别管线的行为测试（不加载真实模型）。"""

from __future__ import annotations

import pytest

from app.domain.shared_services import intent_recognition_pipeline as pipeline
from app.domain.shared_services import intent_semantic_router as semantic
from app.domain.shared_services.intent_service import reload_intent_service


@pytest.fixture(autouse=True)
def _clear_intent_cache():
    reload_intent_service()
    yield
    reload_intent_service()


def _patch_semantic(monkeypatch: pytest.MonkeyPatch, tool_key: str, score: float) -> None:
    monkeypatch.setattr(
        semantic,
        "route_intent",
        lambda text: semantic.SemanticIntent(
            intent_id=tool_key, tool_key=tool_key, score=score
        ),
    )
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_OVERRIDE_THRESHOLD", "0.74")


def test_semantic_fills_when_rule_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_semantic(monkeypatch, "price_list", 0.80)
    result = pipeline.recognize_intents_impl("那个东西现在什么行情")
    assert result["tool_key"] == "price_list"
    assert result["intent_source"] == "semantic"
    assert result["confidence"] == 0.80


def test_semantic_overrides_low_confidence_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_semantic(monkeypatch, "price_list", 0.90)
    result = pipeline.recognize_intents_impl("查一下产品")
    assert result["intent_source"] == "semantic_override"
    assert result["tool_key"] == "price_list"


def test_semantic_does_not_override_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_semantic(monkeypatch, "price_list", 0.60)
    result = pipeline.recognize_intents_impl("查一下产品")
    assert result["intent_source"] == "rule"
    assert result["tool_key"] != "price_list"


def test_semantic_skipped_for_negated_write(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def _explode(text: str):
        nonlocal called
        called = True
        return semantic.SemanticIntent("shipment_generate", "shipment_generate", 0.99)

    monkeypatch.setattr(semantic, "route_intent", _explode)
    result = pipeline.recognize_intents_impl("不要开发货单")
    assert called is False
    assert result["is_negated"] is True
