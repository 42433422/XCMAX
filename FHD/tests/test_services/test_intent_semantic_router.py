"""语义意图兜底路由的单元测试（不加载真实模型）。"""

from __future__ import annotations

import pytest

from app.domain.shared_services import intent_semantic_router as mod


def test_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_ENABLED", "0")
    mod.reload_semantic_router()
    assert mod.semantic_enabled() is False
    assert mod.route_intent("帮我开单") is None


def test_unavailable_router_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_ENABLED", "1")
    mod.reload_semantic_router()
    monkeypatch.setattr(mod, "_router", None)
    monkeypatch.setattr(mod, "_router_error", "encoder unavailable")
    assert mod.route_intent("帮我开单") is None
    assert mod.semantic_router_status()["error"] == "encoder unavailable"


def test_thresholds_are_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_THRESHOLD", "0.61")
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_OVERRIDE_THRESHOLD", "0.88")
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_OVERRIDE_MAX_PRIORITY", "9")
    assert mod.semantic_threshold() == 0.61
    assert mod.semantic_override_threshold() == 0.88
    assert mod.semantic_override_max_priority() == 9


def test_route_returns_choice_above_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Choice:
        name = "shipment_generate"
        confidence = 0.88

    class _Router:
        routes = []

        def __call__(self, text: str, limit: int = 1):
            return _Choice()

    monkeypatch.setenv("FHD_INTENT_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_THRESHOLD", "0.55")
    mod.reload_semantic_router()
    monkeypatch.setattr(mod, "_router", _Router())
    monkeypatch.setattr(mod, "_intent_by_tool", {"shipment_generate": "shipment_generate"})

    result = mod.route_intent("安排发货")
    assert result is not None
    assert result.tool_key == "shipment_generate"
    assert result.intent_id == "shipment_generate"
    assert result.score == 0.88


def test_route_below_threshold_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Choice:
        name = "products"
        confidence = 0.30

    class _Router:
        routes = []

        def __call__(self, text: str, limit: int = 1):
            return _Choice()

    monkeypatch.setenv("FHD_INTENT_SEMANTIC_ENABLED", "1")
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_THRESHOLD", "0.60")
    mod.reload_semantic_router()
    monkeypatch.setattr(mod, "_router", _Router())
    assert mod.route_intent("随便问问") is None


def test_corpus_merges_config_keywords(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mod,
        "_load_corpus",
        lambda: {"shipment_generate": ["给客户安排发货"]},
    )
    routes, intent_by_tool = mod._build_routes()
    shipment = next(route for route in routes if route.name == "shipment_generate")
    assert "给客户安排发货" in shipment.utterances
    assert len(shipment.utterances) >= 2
    assert intent_by_tool["shipment_generate"] == "shipment_generate"
