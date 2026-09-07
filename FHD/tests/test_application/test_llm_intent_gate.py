"""LLM 意图闸单测：分类命中/低置信/失败/写操作/离线开关 全路径。"""

from __future__ import annotations

import pytest

from app.application import llm_intent_gate as gate


@pytest.fixture(autouse=True)
def _clear_cache():
    gate._cache.clear()
    yield
    gate._cache.clear()


class _Structured:
    def __init__(self, data):
        self.data = data


def _patch_llm(monkeypatch, data=None, exc=None):
    def fake_sync(messages, **kwargs):
        if exc is not None:
            raise exc
        return _Structured(data)

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync", fake_sync
    )


def test_gate_on_when_env_forced(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    assert gate._gate_enabled() is True


def test_gate_off_env_and_pytest_default(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "0")
    assert gate._gate_enabled() is False
    monkeypatch.delenv("XCAGI_LLM_INTENT_GATE")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
    assert gate._gate_enabled() is False


def test_hit_customers_query(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(
        monkeypatch, {"intent": "customers", "confidence": 0.9, "slots": {"keyword": "王总"}}
    )
    result = gate.llm_route_message("王总那家公司电话多少")
    assert result is not None
    assert result["intent"] == "customers_query"
    assert result["slots"]["keyword"] == "王总"
    assert result["llm_routed"] is True


def test_hit_shipment_generate_maps_to_shipment(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(
        monkeypatch,
        {
            "intent": "shipment_generate",
            "confidence": 0.85,
            "slots": {"unit_name": "太阳鸟", "quantity_tins": "30"},
        },
    )
    result = gate.llm_route_message("太阳鸟那边要28的规格来30桶")
    assert result is not None and result["intent"] == "shipment"


def test_label_print_slot_normalization(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(
        monkeypatch,
        {
            "intent": "print_label",
            "confidence": 0.9,
            "slots": {"model_number": "a-100", "quantity_tins": "50张"},
        },
    )
    result = gate.llm_route_message("把A-100的商标打50张")
    assert result is not None
    assert result["intent"] == "label_print"
    assert result["slots"] == {"model_number": "A-100", "quantity": 50}


def test_low_confidence_returns_none(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(monkeypatch, {"intent": "customers", "confidence": 0.4, "slots": {}})
    assert gate.llm_route_message("随便说点什么奇怪的话") is None


def test_low_confidence_band_returns_clarify(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(
        monkeypatch,
        {
            "intent": "products",
            "confidence": 0.55,
            "candidates": ["products", "materials"],
            "slots": {},
        },
    )
    result = gate.llm_route_message("那个二十升的还有没有")
    assert result is not None
    assert result["intent"] == "clarify"
    assert result["slots"]["candidates"] == ["products", "materials"]
    assert "查产品" in result["slots"]["question"]
    assert "查物料" in result["slots"]["question"]


def test_clarify_single_candidate(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(monkeypatch, {"intent": "customers", "confidence": 0.5, "slots": {}})
    result = gate.llm_route_message("王总那边情况怎么样")
    assert result is not None and result["intent"] == "clarify"
    assert "您是想查客户" in result["slots"]["question"]


def test_clarify_candidates_filtered_to_whitelist(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(
        monkeypatch,
        {
            "intent": "delete_customer",
            "confidence": 0.6,
            "candidates": ["delete_customer", "nonsense"],
            "slots": {},
        },
    )
    # 主意图与候选都不在白名单内 → 无话可问，回退 unknown（None）。
    assert gate.llm_route_message("随便说点什么业务外的话") is None


def test_unknown_intent_returns_none(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(monkeypatch, {"intent": "none", "confidence": 0.9, "slots": {}})
    assert gate.llm_route_message("给我讲个笑话") is None


def test_mutation_message_never_calls_llm(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")

    def boom(*a, **k):
        raise AssertionError("写操作消息不应调用 LLM")

    monkeypatch.setattr("app.infrastructure.llm.structured_output.complete_structured_sync", boom)
    assert gate.llm_route_message("删除侯雪梅这条记录") is None


def test_llm_failure_fails_open(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    _patch_llm(monkeypatch, exc=RuntimeError("network down"))
    assert gate.llm_route_message("老规矩给七彩乐园出一单") is None


def test_cache_prevents_second_llm_call(monkeypatch):
    monkeypatch.setenv("XCAGI_LLM_INTENT_GATE", "1")
    calls = {"n": 0}

    def counting(messages, **kwargs):
        calls["n"] += 1
        return _Structured({"intent": "products", "confidence": 0.9, "slots": {}})

    monkeypatch.setattr(
        "app.infrastructure.llm.structured_output.complete_structured_sync", counting
    )
    msg = "有没有20升装的产品"
    assert gate.llm_route_message(msg) is not None
    assert gate.llm_route_message(msg) is not None
    assert calls["n"] == 1
