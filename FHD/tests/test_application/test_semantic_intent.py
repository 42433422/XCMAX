"""语义意图层（semantic-router + fastembed）的契约与降级行为。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application import intent as intent_pkg
from app.application.intent import semantic_intent


class _FakeRouter:
    def __init__(self, choices):
        self._choices = choices
        self.queries: list[str] = []

    def __call__(self, query, limit=None, threshold=None):
        self.queries.append(query)
        return list(self._choices)


@pytest.fixture()
def semantic_on(monkeypatch):
    monkeypatch.setenv("XCAGI_INTENT_ENGINE", "on")
    semantic_intent.reset_for_tests()
    yield
    semantic_intent.reset_for_tests()


def test_engine_is_off_inside_tests_unless_explicitly_enabled(monkeypatch):
    monkeypatch.delenv("XCAGI_INTENT_ENGINE", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "x")
    assert semantic_intent.engine_enabled() is False
    monkeypatch.setenv("XCAGI_INTENT_ENGINE", "on")
    assert semantic_intent.engine_enabled() is True
    monkeypatch.setenv("XCAGI_INTENT_ENGINE", "off")
    assert semantic_intent.engine_enabled() is False


def test_classify_returns_sorted_matches_from_the_router(semantic_on, monkeypatch):
    router = _FakeRouter(
        [
            SimpleNamespace(name="customer", confidence=0.61),
            SimpleNamespace(name="product_issue", confidence=0.83),
            SimpleNamespace(name="", confidence=0.99),
        ]
    )
    monkeypatch.setattr(semantic_intent, "_load_router", lambda: router)
    matches = semantic_intent.classify_intents("主页按键不明显", limit=2)
    assert [(m.intent, m.confidence) for m in matches] == [
        ("product_issue", 0.83),
        ("customer", 0.61),
    ]
    assert router.queries == ["主页按键不明显"]


def test_unavailable_model_degrades_to_no_matches(semantic_on, monkeypatch):
    monkeypatch.setattr(semantic_intent, "_load_router", lambda: None)
    assert semantic_intent.classify_intents("主页按键不明显") == []
    assert semantic_intent.best_intent("主页按键不明显") is None


def test_router_failure_is_swallowed(semantic_on, monkeypatch):
    class _Boom:
        def __call__(self, *args, **kwargs):
            raise RuntimeError("onnx exploded")

    monkeypatch.setattr(semantic_intent, "_load_router", lambda: _Boom())
    assert semantic_intent.classify_intents("主页按键不明显") == []


@pytest.mark.parametrize(
    "choices,min_confidence,expected",
    [
        (
            [("product_issue", 0.64), ("customer", 0.58), ("employee", 0.56)],
            None,
            ("product_issue", 0.64),
        ),
        ([("customer", 0.52), ("sales", 0.73)], None, ("sales", 0.73)),
        ([("product_issue", 0.54)], None, None),
        ([("product_issue", 0.55)], None, ("product_issue", 0.55)),
        ([("product_issue", 0.64)], 0.7, None),
        ([("product_issue", 0.64)], 0.64, ("product_issue", 0.64)),
    ],
)
def test_best_intent_returns_only_the_highest_match_above_threshold(
    semantic_on, monkeypatch, choices, min_confidence, expected
):
    monkeypatch.setenv("XCAGI_INTENT_THRESHOLD", "0.55")
    router = _FakeRouter(
        [SimpleNamespace(name=name, confidence=confidence) for name, confidence in choices]
    )
    monkeypatch.setattr(semantic_intent, "_load_router", lambda: router)
    match = semantic_intent.best_intent("当前请求", min_confidence=min_confidence)
    assert (None if match is None else (match.intent, match.confidence)) == expected
    assert router.queries == ["当前请求"]


def test_ticket_resolution_accepts_semantic_product_issue(monkeypatch):
    from app.application import client_product_issue_intake as intake

    monkeypatch.setattr(
        intent_pkg,
        "best_intent",
        lambda text, min_confidence=None: SimpleNamespace(intent="product_issue", confidence=0.8),
    )
    context = {
        "recent_messages": [
            {"role": "user", "content": "主页那个电话按键很不清楚"},
            {"role": "user", "content": "确认"},
        ]
    }
    resolved = intake.resolve_issue_report_message("那你去提交一下呀。", context)
    assert "电话按键" in resolved
