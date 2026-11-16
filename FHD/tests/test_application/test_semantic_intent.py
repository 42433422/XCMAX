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


def test_planner_intents_only_accept_a_clear_winner(monkeypatch):
    from app.application.workflow import planner_prompt_profile as profile

    monkeypatch.setattr(
        intent_pkg,
        "classify_intents",
        lambda text, limit=3: [
            SimpleNamespace(intent="product_issue", confidence=0.64),
            SimpleNamespace(intent="customer", confidence=0.58),
            SimpleNamespace(intent="employee", confidence=0.56),
        ],
    )
    # 模糊的「那你去提交一下呀」不能顺带注入员工/客户规则。
    assert profile.detect_intents("那你去提交一下呀。") == set()

    monkeypatch.setattr(
        intent_pkg,
        "classify_intents",
        lambda text, limit=3: [
            SimpleNamespace(intent="sales", confidence=0.73),
            SimpleNamespace(intent="customer", confidence=0.52),
        ],
    )
    assert profile.detect_intents("这个月出了多少货") == {"sales"}


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
