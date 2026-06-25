"""真实行为测试：app.neuro_bus.integrations.intent_integration。

覆盖 try_neuro_reflex_intent / NeuroIntentRecognizer.recognize 及其
_build_reflex_result / _build_conscious_result 分支、emit 的 except 兜底、
以及 integrate_with_intent_system / get_neuro_intent_recognizer 工厂。

所有外部依赖（reflex arc、intent domain、cognitive router、unified
recognizer）均被 mock，测试离线、确定性、快速。patch 站点对齐函数内/模块顶
层的实际导入路径。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.neuro_bus.integrations.intent_integration as II
from app.domain.neuro.processors.coordinator import ProcessorType
from app.domain.neuro.reflex_arc import ReflexResult, ReflexType

MOD = "app.neuro_bus.integrations.intent_integration"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _reflex(
    *,
    triggered: bool,
    rtype: ReflexType = ReflexType.GREETING,
    confidence: float = 1.0,
    response: str = "您好",
) -> ReflexResult:
    return ReflexResult(
        triggered=triggered,
        reflex_type=rtype,
        confidence=confidence,
        response=response,
        latency_us=12.0,
    )


def _recognizer_result(**over):
    """构造一个真实 RecognizerResult。"""
    from app.services.unified_intent_recognizer import RecognizerResult

    base = {
        "primary_intent": "products",
        "tool_key": "products",
        "intent_hints": ["products"],
        "is_negated": False,
        "is_greeting": False,
        "is_goodbye": False,
        "is_help": False,
        "is_confirmation": False,
        "is_negation_intent": False,
        "is_likely_unclear": False,
        "all_matched_tools": [],
        "slots": {"category": "fruit"},
        "confidence": 0.9,
        "sources_used": ["rule"],
        "raw_results": {},
    }
    base.update(over)
    return RecognizerResult(**base)


# ===========================================================================
# is_neuro_stack_enabled
# ===========================================================================
class TestNeuroStackEnabled:
    def test_default_enabled_when_unset(self, monkeypatch):
        monkeypatch.delenv("XCAGI_NEURO_INTENT", raising=False)
        assert II.is_neuro_stack_enabled() is True

    @pytest.mark.parametrize("val", ["0", "false", "off", "no", "FALSE", "Off", " NO "])
    def test_disabled_values(self, monkeypatch, val):
        monkeypatch.setenv("XCAGI_NEURO_INTENT", val)
        assert II.is_neuro_stack_enabled() is False

    @pytest.mark.parametrize("val", ["1", "yes", "true", "on", "anything"])
    def test_enabled_values(self, monkeypatch, val):
        monkeypatch.setenv("XCAGI_NEURO_INTENT", val)
        assert II.is_neuro_stack_enabled() is True


# ===========================================================================
# reflex_match_to_chat_intent_dict
# ===========================================================================
class TestReflexMatchToChatIntentDict:
    def test_greeting_flags(self):
        rr = _reflex(triggered=True, rtype=ReflexType.GREETING, response="hi")
        out = II.reflex_match_to_chat_intent_dict(rr)
        assert out["is_greeting"] is True
        assert out["is_help"] is False
        assert out["is_confirmation"] is False
        assert out["is_negated"] is False
        assert out["slots"] == {"reflex_response": "hi"}
        assert out["intent_source"] == "neuro_reflex"
        assert out["intent_hints"] == []

    def test_denial_sets_negation_flags(self):
        rr = _reflex(triggered=True, rtype=ReflexType.DENIAL, response="不要")
        out = II.reflex_match_to_chat_intent_dict(rr)
        assert out["is_negated"] is True
        assert out["is_negation_intent"] is True
        assert out["is_greeting"] is False

    def test_help_flag(self):
        rr = _reflex(triggered=True, rtype=ReflexType.HELP, response="帮助")
        out = II.reflex_match_to_chat_intent_dict(rr)
        assert out["is_help"] is True

    def test_confirmation_flag(self):
        rr = _reflex(triggered=True, rtype=ReflexType.CONFIRMATION, response="好")
        out = II.reflex_match_to_chat_intent_dict(rr)
        assert out["is_confirmation"] is True

    def test_emergency_stop_appends_hint(self):
        rr = _reflex(triggered=True, rtype=ReflexType.EMERGENCY_STOP, response="停")
        out = II.reflex_match_to_chat_intent_dict(rr)
        assert "emergency_stop" in out["intent_hints"]


# ===========================================================================
# try_neuro_reflex_intent
# ===========================================================================
class TestTryNeuroReflexIntent:
    def test_disabled_returns_none(self, monkeypatch):
        monkeypatch.setattr(II, "is_neuro_stack_enabled", lambda: False)
        assert II.try_neuro_reflex_intent("hi", "u1") is None

    def test_not_triggered_returns_none(self, monkeypatch):
        monkeypatch.setattr(II, "is_neuro_stack_enabled", lambda: True)
        arc = MagicMock()
        arc.process.return_value = _reflex(triggered=False)
        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)
        assert II.try_neuro_reflex_intent("xyz") is None

    def test_low_confidence_returns_none(self, monkeypatch):
        monkeypatch.setattr(II, "is_neuro_stack_enabled", lambda: True)
        arc = MagicMock()
        arc.process.return_value = _reflex(triggered=True, confidence=0.5)
        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)
        assert II.try_neuro_reflex_intent("maybe") is None

    def test_success_emits_and_returns_dict(self, monkeypatch):
        monkeypatch.setattr(II, "is_neuro_stack_enabled", lambda: True)
        arc = MagicMock()
        arc.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.GREETING, confidence=0.95, response="您好"
        )
        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)
        dom = MagicMock()
        monkeypatch.setattr(II, "get_intent_domain", lambda: dom)

        out = II.try_neuro_reflex_intent("你好", "user-42")

        assert out is not None
        assert out["is_greeting"] is True
        assert out["slots"]["reflex_response"] == "您好"
        # emit 被调用且带正确参数
        dom.emit_reflex_triggered.assert_called_once()
        kwargs = dom.emit_reflex_triggered.call_args.kwargs
        assert kwargs["reflex_type"] == "greeting"
        assert kwargs["user_id"] == "user-42"
        assert kwargs["latency_ms"] >= 0.0

    def test_emit_failure_is_swallowed(self, monkeypatch):
        """get_intent_domain 抛 RECOVERABLE_ERRORS（bus down）时仍返回意图字典。"""
        monkeypatch.setattr(II, "is_neuro_stack_enabled", lambda: True)
        arc = MagicMock()
        arc.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.CONFIRMATION, confidence=0.9, response="好的"
        )
        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)

        def _boom():
            raise RuntimeError("bus down")

        monkeypatch.setattr(II, "get_intent_domain", _boom)

        out = II.try_neuro_reflex_intent("是的")
        assert out is not None
        assert out["is_confirmation"] is True


# ===========================================================================
# NeuroIntentRecognizer.__init__
# ===========================================================================
class TestRecognizerInit:
    def test_uses_injected_dependencies(self, monkeypatch):
        # 若注入则不调用工厂
        sentinel_unified = MagicMock(name="should_not_be_used")
        monkeypatch.setattr(
            "app.services.unified_intent_recognizer.get_unified_intent_recognizer",
            lambda: sentinel_unified,
        )
        reflex = MagicMock(name="reflex")
        base = MagicMock(name="base")
        rec = II.NeuroIntentRecognizer(reflex_arc=reflex, base_recognizer=base)
        assert rec._reflex is reflex
        assert rec._base is base

    def test_falls_back_to_factories(self, monkeypatch):
        arc = MagicMock(name="arc")
        unified = MagicMock(name="unified")
        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)
        monkeypatch.setattr(
            "app.services.unified_intent_recognizer.get_unified_intent_recognizer",
            lambda: unified,
        )
        rec = II.NeuroIntentRecognizer()
        assert rec._reflex is arc
        assert rec._base is unified


# ---------------------------------------------------------------------------
# fixtures for recognize()
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_router(monkeypatch):
    """patch get_cognitive_router (函数内 import 自 cognitive_router 模块)。"""
    router = MagicMock()
    router.route.return_value = (None, "trace-xyz")  # 默认 MLP 未启用
    router.is_sla_hit.return_value = True
    monkeypatch.setattr(
        "app.neuro_bus.routing.cognitive_router.get_cognitive_router",
        lambda: router,
    )
    return router


@pytest.fixture
def fake_domain(monkeypatch):
    dom = MagicMock()
    monkeypatch.setattr(II, "get_intent_domain", lambda: dom)
    return dom


def _make_recognizer(reflex_mock, base_mock, monkeypatch):
    monkeypatch.setattr(
        "app.services.unified_intent_recognizer.get_unified_intent_recognizer",
        lambda: base_mock,
    )
    return II.NeuroIntentRecognizer(reflex_arc=reflex_mock, base_recognizer=base_mock)


# ===========================================================================
# NeuroIntentRecognizer.recognize — rule fallback path (decision is None)
# ===========================================================================
class TestRecognizeRuleFallback:
    def test_reflex_path_when_triggered_highconf(self, monkeypatch, fake_router, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.GREETING, confidence=0.9, response="您好"
        )
        base = MagicMock()
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("你好", user_id="u")

        assert res.processor_type == ProcessorType.REFLEX
        assert res.source == "reflex"
        assert res.intent == "greeting"
        assert res.reflex_used is True
        assert res.entities == {"response": "您好"}
        base.recognize.assert_not_called()
        fake_domain.emit_reflex_triggered.assert_called_once()
        # record_outcome 反馈闭环
        fake_router.record_outcome.assert_called_once()
        rk = fake_router.record_outcome.call_args.kwargs
        assert rk["processor_type"] == ProcessorType.REFLEX
        assert rk["success"] is True  # greeting confidence 0.9 > 0.5

    def test_conscious_path_when_reflex_not_triggered(self, monkeypatch, fake_router, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False, confidence=0.0)
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(
            primary_intent="search", confidence=0.8, slots={"q": "x"}
        )
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("搜索点什么", user_id="u2")

        assert res.processor_type == ProcessorType.CONSCIOUS
        assert res.source == "unified"
        assert res.intent == "search"
        assert res.confidence == 0.8
        assert res.ai_enhanced is True
        assert res.recognizer_result is base.recognize.return_value
        base.recognize.assert_called_once()
        fake_domain.emit_intent_recognized.assert_called_once()
        ek = fake_domain.emit_intent_recognized.call_args.kwargs
        assert ek["intent_type"] == "search"
        assert ek["processor_used"] == "conscious"
        assert ek["entities"] == {"q": "x"}

    def test_conscious_path_when_reflex_low_confidence(self, monkeypatch, fake_router, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=True, confidence=0.5)
        base = MagicMock()
        base.recognize.return_value = _recognizer_result()
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("含糊")
        assert res.processor_type == ProcessorType.CONSCIOUS
        base.recognize.assert_called_once()


# ===========================================================================
# NeuroIntentRecognizer.recognize — MLP decision path
# ===========================================================================
class TestRecognizeMlpDecision:
    def test_mlp_reflex_hit(self, monkeypatch, fake_router, fake_domain):
        fake_router.route.return_value = (
            SimpleNamespace(processor_type=ProcessorType.REFLEX),
            "t1",
        )
        reflex = MagicMock()
        reflex.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.HELP, confidence=0.85, response="帮助"
        )
        base = MagicMock()
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("怎么用")
        assert res.processor_type == ProcessorType.REFLEX
        assert res.intent == "help"
        base.recognize.assert_not_called()
        # record_outcome 用 REFLEX
        assert fake_router.record_outcome.call_args.kwargs["processor_type"] == ProcessorType.REFLEX

    def test_mlp_reflex_but_not_triggered_degrades_to_conscious(
        self, monkeypatch, fake_router, fake_domain
    ):
        fake_router.route.return_value = (
            SimpleNamespace(processor_type=ProcessorType.REFLEX),
            "t2",
        )
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False)
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(primary_intent="order", confidence=0.7)
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("下单")
        # MLP 说 reflex 但没命中 → 降级 conscious
        assert res.processor_type == ProcessorType.CONSCIOUS
        assert res.intent == "order"
        base.recognize.assert_called_once()
        assert (
            fake_router.record_outcome.call_args.kwargs["processor_type"] == ProcessorType.CONSCIOUS
        )

    def test_mlp_subconscious(self, monkeypatch, fake_router, fake_domain):
        fake_router.route.return_value = (
            SimpleNamespace(processor_type=ProcessorType.SUBCONSCIOUS),
            "t3",
        )
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False)
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(primary_intent="weather", confidence=0.6)
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("天气")
        assert res.processor_type == ProcessorType.SUBCONSCIOUS
        assert res.intent == "weather"
        # emit 用 subconscious 标记
        ek = fake_domain.emit_intent_recognized.call_args.kwargs
        assert ek["processor_used"] == "subconscious"
        assert (
            fake_router.record_outcome.call_args.kwargs["processor_type"]
            == ProcessorType.SUBCONSCIOUS
        )

    def test_mlp_conscious(self, monkeypatch, fake_router, fake_domain):
        fake_router.route.return_value = (
            SimpleNamespace(processor_type=ProcessorType.CONSCIOUS),
            "t4",
        )
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=True, confidence=0.95)
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(primary_intent="faq", confidence=0.55)
        rec = _make_recognizer(reflex, base, monkeypatch)

        res = rec.recognize("问题")
        assert res.processor_type == ProcessorType.CONSCIOUS
        assert res.intent == "faq"
        base.recognize.assert_called_once()


# ===========================================================================
# _build_reflex_result — emit except branch
# ===========================================================================
class TestBuildReflexResultEmitFailure:
    def test_emit_failure_swallowed_still_returns_result(self, monkeypatch, fake_domain):
        reflex = MagicMock()
        base = MagicMock()
        rec = _make_recognizer(reflex, base, monkeypatch)
        fake_domain.emit_reflex_triggered.side_effect = ValueError("bad")

        rr = _reflex(triggered=True, rtype=ReflexType.DENIAL, confidence=0.99, response="不")
        out = rec._build_reflex_result(rr, start_time=0.0, user_id="u")

        assert out.intent == "denial"
        assert out.confidence == 0.99
        assert out.reflex_used is True
        assert out.processor_type == ProcessorType.REFLEX
        assert out.entities == {"response": "不"}


# ===========================================================================
# _build_conscious_result — both branches + emit failures
# ===========================================================================
class TestBuildConsciousResult:
    def test_recognizer_result_branch(self, monkeypatch, fake_domain):
        reflex = MagicMock()
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(
            primary_intent="buy", confidence=0.77, slots={"item": "山竹"}
        )
        rec = _make_recognizer(reflex, base, monkeypatch)

        out = rec._build_conscious_result("买山竹", "u", None, None, 0.0, ProcessorType.CONSCIOUS)
        assert out.intent == "buy"
        assert out.confidence == 0.77
        assert out.source == "unified"
        assert out.ai_enhanced is True
        assert out.recognizer_result is base.recognize.return_value
        # entities 在 RecognizerResult 分支恒为 {}
        assert out.entities == {}
        ek = fake_domain.emit_intent_recognized.call_args.kwargs
        assert ek["entities"] == {"item": "山竹"}
        assert ek["raw_text"] == "买山竹"

    def test_recognizer_result_none_primary_intent_maps_unknown(self, monkeypatch, fake_domain):
        reflex = MagicMock()
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(primary_intent=None, confidence=0.0)
        rec = _make_recognizer(reflex, base, monkeypatch)

        out = rec._build_conscious_result("?", "u", None, None, 0.0)
        assert out.intent == "unknown"

    def test_recognizer_result_emit_failure_swallowed(self, monkeypatch, fake_domain):
        reflex = MagicMock()
        base = MagicMock()
        base.recognize.return_value = _recognizer_result(primary_intent="x", confidence=0.6)
        rec = _make_recognizer(reflex, base, monkeypatch)
        fake_domain.emit_intent_recognized.side_effect = RuntimeError("down")

        out = rec._build_conscious_result("x", "u", None, None, 0.0)
        assert out.intent == "x"
        assert out.confidence == 0.6

    def test_dict_fallback_branch(self, monkeypatch, fake_domain):
        """base.recognize 返回 dict（非 RecognizerResult）→ 走回退分支。"""
        reflex = MagicMock()
        base = MagicMock()
        base.recognize.return_value = {
            "intent": "legacy",
            "confidence": 0.42,
            "entities": {"a": 1},
            "source": "legacy_src",
        }
        rec = _make_recognizer(reflex, base, monkeypatch)

        out = rec._build_conscious_result("t", "u", None, None, 0.0, ProcessorType.SUBCONSCIOUS)
        assert out.intent == "legacy"
        assert out.confidence == 0.42
        assert out.source == "legacy_src"
        assert out.entities == {"a": 1}
        assert out.recognizer_result is None
        ek = fake_domain.emit_intent_recognized.call_args.kwargs
        assert ek["processor_used"] == "subconscious"
        assert ek["intent_type"] == "legacy"

    def test_non_dict_non_recognizer_fallback_defaults(self, monkeypatch, fake_domain):
        """base.recognize 返回非 dict 非 RecognizerResult → br={} → unknown defaults。"""
        reflex = MagicMock()
        base = MagicMock()
        base.recognize.return_value = ["not", "a", "dict"]
        rec = _make_recognizer(reflex, base, monkeypatch)

        out = rec._build_conscious_result("t", "u", None, None, 0.0)
        assert out.intent == "unknown"
        assert out.confidence == 0.0
        assert out.source == "unified"
        assert out.entities == {}

    def test_dict_fallback_emit_failure_swallowed(self, monkeypatch, fake_domain):
        reflex = MagicMock()
        base = MagicMock()
        base.recognize.return_value = {"intent": "y", "confidence": 0.3}
        rec = _make_recognizer(reflex, base, monkeypatch)
        fake_domain.emit_intent_recognized.side_effect = ValueError("nope")

        out = rec._build_conscious_result("t", "u", None, None, 0.0)
        assert out.intent == "y"
        assert out.confidence == 0.3


# ===========================================================================
# recognize_async / should_use_reflex / get_stats
# ===========================================================================
class TestSimpleDelegates:
    async def test_recognize_async_delegates(self, monkeypatch, fake_router, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.GREETING, confidence=0.9, response="hi"
        )
        base = MagicMock()
        rec = _make_recognizer(reflex, base, monkeypatch)

        out = await rec.recognize_async("你好", user_id="u")
        assert out.intent == "greeting"
        assert out.processor_type == ProcessorType.REFLEX

    def test_should_use_reflex_delegates(self, monkeypatch):
        reflex = MagicMock()
        reflex.should_handle.return_value = True
        base = MagicMock()
        rec = _make_recognizer(reflex, base, monkeypatch)
        assert rec.should_use_reflex("你好") is True
        reflex.should_handle.assert_called_once_with("你好")

    def test_get_stats_delegates(self, monkeypatch):
        reflex = MagicMock()
        reflex.get_stats.return_value = {"hits": 3}
        base = MagicMock()
        rec = _make_recognizer(reflex, base, monkeypatch)
        assert rec.get_stats() == {"reflex": {"hits": 3}}


# ===========================================================================
# integrate_with_intent_system / get_neuro_intent_recognizer
# ===========================================================================
class TestIntegrationFactory:
    def test_integrate_happy_path(self, monkeypatch):
        arc = MagicMock()
        dom = MagicMock()
        unified = MagicMock()
        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)
        monkeypatch.setattr(II, "get_intent_domain", lambda: dom)
        monkeypatch.setattr(
            "app.services.unified_intent_recognizer.get_unified_intent_recognizer",
            lambda: unified,
        )
        rec = II.integrate_with_intent_system()
        assert isinstance(rec, II.NeuroIntentRecognizer)
        assert rec._reflex is arc

    def test_integrate_reflex_init_error_swallowed(self, monkeypatch):
        dom = MagicMock()
        unified = MagicMock()
        arc_for_recognizer = MagicMock()

        calls = {"n": 0}

        def _get_reflex():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("reflex init boom")
            return arc_for_recognizer

        monkeypatch.setattr(II, "get_reflex_arc", _get_reflex)
        monkeypatch.setattr(II, "get_intent_domain", lambda: dom)
        monkeypatch.setattr(
            "app.services.unified_intent_recognizer.get_unified_intent_recognizer",
            lambda: unified,
        )
        # 不抛：第一次报错被 warning 吞掉，仍构造出 recognizer
        rec = II.integrate_with_intent_system()
        assert isinstance(rec, II.NeuroIntentRecognizer)

    def test_integrate_domain_init_error_swallowed(self, monkeypatch):
        arc = MagicMock()
        unified = MagicMock()

        def _boom_domain():
            raise ValueError("domain init boom")

        monkeypatch.setattr(II, "get_reflex_arc", lambda: arc)
        monkeypatch.setattr(II, "get_intent_domain", _boom_domain)
        monkeypatch.setattr(
            "app.services.unified_intent_recognizer.get_unified_intent_recognizer",
            lambda: unified,
        )
        rec = II.integrate_with_intent_system()
        assert isinstance(rec, II.NeuroIntentRecognizer)

    def test_get_neuro_intent_recognizer_singleton(self, monkeypatch):
        monkeypatch.setattr(II, "_neuro_recognizer", None)
        created = MagicMock(name="recognizer")
        monkeypatch.setattr(II, "integrate_with_intent_system", lambda: created)

        first = II.get_neuro_intent_recognizer()
        second = II.get_neuro_intent_recognizer()
        assert first is created
        assert second is created  # 缓存命中，不再构造

    def test_get_neuro_intent_recognizer_returns_cached(self, monkeypatch):
        cached = MagicMock(name="cached")
        monkeypatch.setattr(II, "_neuro_recognizer", cached)

        def _should_not_call():
            raise AssertionError("integrate should not be called when cached")

        monkeypatch.setattr(II, "integrate_with_intent_system", _should_not_call)
        assert II.get_neuro_intent_recognizer() is cached
