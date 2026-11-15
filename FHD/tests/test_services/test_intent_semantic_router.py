"""语义意图兜底路由的单元测试（不加载真实模型）。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

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


def test_missing_optional_backend_fails_closed_without_disabling_rule_support(monkeypatch):
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_ENABLED", "1")
    monkeypatch.setitem(sys.modules, "semantic_router", None)
    mod.reload_semantic_router()
    routes, _ = mod._build_routes()
    assert routes
    assert mod.get_semantic_router() is None
    assert "ModuleNotFoundError" in mod.semantic_router_status()["error"]


@pytest.mark.parametrize(
    "payload",
    ["[]", "utterances: invalid", "utterances: {shipment_generate: invalid}", "utterances: ["],
)
def test_invalid_corpus_keeps_keyword_routes(monkeypatch, tmp_path, payload):
    corpus = tmp_path / "corpus.yaml"
    corpus.write_text(payload)
    monkeypatch.setattr(mod, "_CORPUS_RELATIVE_PATH", str(corpus))
    assert mod._load_corpus() == {}
    assert mod._build_routes()[0]


def test_optional_backend_receives_converted_routes_and_real_thresholds(monkeypatch):
    backend = SimpleNamespace(Route=SimpleNamespace, IndexedRouter=SimpleNamespace)
    monkeypatch.setitem(sys.modules, "semantic_router", backend)
    monkeypatch.setitem(
        sys.modules, "semantic_router.encoders", SimpleNamespace(FastEmbedEncoder=SimpleNamespace)
    )
    monkeypatch.setattr(mod, "_resolve_model_dir", lambda: "")
    monkeypatch.setenv("FHD_INTENT_SEMANTIC_THRESHOLD", "0.67")
    router, intent_by_tool = mod._build_router()
    assert router.encoder.name == mod.semantic_model_name()
    assert router.confidence_threshold == 0.67
    assert router.top_k == 4
    assert router.routes
    assert all(isinstance(route, SimpleNamespace) for route in router.routes)
    assert all(intent_by_tool[route.name] and len(route.utterances) >= 2 for route in router.routes)
