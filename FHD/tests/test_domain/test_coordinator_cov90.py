"""真实行为测试：app.domain.neuro.processors.coordinator.ProcessorCoordinator。

覆盖：
- route()：policy 命中短路 / reflex 高置信 / 后台优先级 → 潜意识 / 默认显意识
- process()：reflex / subconscious / conscious 三路；conscious 失败降级到 reflex；
  RECOVERABLE_ERRORS 异常路径（紧急降级成功 / 兜底失败报告 / 降级再抛被吞）
- _process_reflex / _process_subconscious / _process_conscious：返回报告结构
- _emit_intent_event：reflex 成功发 reflex+recognized / 非 reflex 成功只 recognized /
  失败发 failed / emit 抛 RECOVERABLE_ERRORS 被吞
- 便捷函数 process_intent / route_intent / get_processor_coordinator 单例

所有处理器（reflex/subconscious/conscious）经构造函数注入 MagicMock；intent_domain
与 policy_router 在“使用处”导入点 patch。测试离线、确定性、快速。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.domain.neuro.processors.coordinator as C
from app.domain.neuro.processors.coordinator import (
    ProcessingReport,
    ProcessorCoordinator,
    ProcessorType,
    RoutingDecision,
    process_intent,
    route_intent,
)
from app.domain.neuro.reflex_arc import ReflexResult, ReflexType
from app.neuro_bus.events.base import EventPriority, NeuroEvent

MOD = "app.domain.neuro.processors.coordinator"
POLICY = "app.neuro_bus.routing.policy_router.decide_processor_with_policy"


# ---------------------------------------------------------------------------
# helpers / fixtures
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


def _make_coord(reflex=None, subconscious=None, conscious=None) -> ProcessorCoordinator:
    """构造一个所有处理器都被 mock 的协调器。"""
    return ProcessorCoordinator(
        reflex_arc=reflex or MagicMock(name="reflex"),
        subconscious=subconscious or MagicMock(name="subconscious"),
        conscious=conscious or MagicMock(name="conscious"),
    )


@pytest.fixture(autouse=True)
def _no_policy(monkeypatch):
    """默认 policy_router 不命中（返回 None），让 route() 走启发式分支。

    单独测试 policy 命中时局部覆写。
    """
    monkeypatch.setattr(POLICY, lambda text, event: None)


@pytest.fixture
def fake_domain(monkeypatch):
    """patch coordinator 顶层导入的 get_intent_domain。"""
    dom = MagicMock(name="intent_domain")
    monkeypatch.setattr(C, "get_intent_domain", lambda: dom)
    return dom


# ===========================================================================
# route()
# ===========================================================================
class TestRoute:
    def test_policy_short_circuits(self, monkeypatch):
        """policy_router 命中时直接返回其决策，不碰 reflex。"""
        sentinel = RoutingDecision(
            processor_type=ProcessorType.SUBCONSCIOUS,
            confidence=0.42,
            reason="policy",
        )
        monkeypatch.setattr(POLICY, lambda text, event: sentinel)
        reflex = MagicMock()
        coord = _make_coord(reflex=reflex)

        out = coord.route("anything")

        assert out is sentinel
        reflex.process.assert_not_called()

    def test_reflex_high_confidence(self):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.GREETING, confidence=0.9
        )
        coord = _make_coord(reflex=reflex)

        out = coord.route("你好")

        assert out.processor_type == ProcessorType.REFLEX
        assert out.confidence == 0.9
        assert "greeting" in out.reason
        assert coord._reflex_count == 1

    def test_reflex_triggered_but_low_confidence_falls_through(self):
        """触发但置信度 < 0.8 → 不走 reflex，默认 conscious。"""
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=True, confidence=0.5)
        coord = _make_coord(reflex=reflex)

        out = coord.route("含糊")

        assert out.processor_type == ProcessorType.CONSCIOUS
        assert coord._reflex_count == 0
        assert coord._conscious_count == 1

    @pytest.mark.parametrize("prio", [EventPriority.LOW, EventPriority.BACKGROUND])
    def test_background_priority_routes_subconscious(self, prio):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False, confidence=0.0)
        coord = _make_coord(reflex=reflex)
        ev = NeuroEvent(event_type="t", payload={}, priority=prio)

        out = coord.route("后台任务", event=ev)

        assert out.processor_type == ProcessorType.SUBCONSCIOUS
        assert out.confidence == 0.9
        assert coord._subconscious_count == 1

    def test_default_to_conscious(self):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False, confidence=0.0)
        coord = _make_coord(reflex=reflex)
        ev = NeuroEvent(event_type="t", payload={}, priority=EventPriority.HIGH)

        out = coord.route("正常请求", event=ev)

        assert out.processor_type == ProcessorType.CONSCIOUS
        assert out.confidence == 0.7
        assert "Default" in out.reason
        assert coord._conscious_count == 1


# ===========================================================================
# _process_reflex
# ===========================================================================
class TestProcessReflex:
    async def test_triggered_builds_success_report(self):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.HELP, confidence=0.95, response="帮助"
        )
        coord = _make_coord(reflex=reflex)

        report = await coord._process_reflex("怎么用", "u1")

        assert report.success is True
        assert report.processor_used == ProcessorType.REFLEX
        assert report.result["reflex_type"] == "help"
        assert report.result["response"] == "帮助"
        assert report.result["confidence"] == 0.95
        assert report.latency_ms >= 0.0

    async def test_not_triggered_reflex_type_none(self):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False, confidence=0.0)
        coord = _make_coord(reflex=reflex)

        report = await coord._process_reflex("xyz", "u")

        assert report.success is False
        assert report.result["reflex_type"] is None


# ===========================================================================
# _process_subconscious
# ===========================================================================
class TestProcessSubconscious:
    async def test_returns_success_report(self):
        sub = MagicMock()
        sub.process = AsyncMock(return_value=True)
        coord = _make_coord(subconscious=sub)

        report = await coord._process_subconscious("文本", "u", {"k": "v"})

        assert report.success is True
        assert report.processor_used == ProcessorType.SUBCONSCIOUS
        assert report.result == {"processed": True}
        # 验证传给 subconscious 的事件结构正确
        sub.process.assert_awaited_once()
        ev = sub.process.await_args.args[0]
        assert isinstance(ev, NeuroEvent)
        assert ev.event_type == "subconscious.task"
        assert ev.priority == EventPriority.LOW
        assert ev.payload["text"] == "文本"
        assert ev.payload["context"] == {"k": "v"}

    async def test_failure_report(self):
        sub = MagicMock()
        sub.process = AsyncMock(return_value=False)
        coord = _make_coord(subconscious=sub)

        report = await coord._process_subconscious("文本", "u", {})

        assert report.success is False
        assert report.result == {"processed": False}


# ===========================================================================
# _process_conscious
# ===========================================================================
class TestProcessConscious:
    async def test_success_report_maps_data_and_error(self):
        conscious = MagicMock()
        conscious.process = AsyncMock(
            return_value=MagicMock(success=True, data={"answer": 42}, error=None)
        )
        coord = _make_coord(conscious=conscious)

        report = await coord._process_conscious("问题", "u", {"c": 1})

        assert report.success is True
        assert report.processor_used == ProcessorType.CONSCIOUS
        assert report.result == {"answer": 42}
        assert report.error is None
        ev = conscious.process.await_args.args[0]
        assert ev.event_type == "intent.process"
        assert ev.priority == EventPriority.HIGH
        assert ev.payload["user_id"] == "u"

    async def test_failure_report_propagates_error(self):
        conscious = MagicMock()
        conscious.process = AsyncMock(
            return_value=MagicMock(success=False, data=None, error="boom")
        )
        coord = _make_coord(conscious=conscious)

        report = await coord._process_conscious("问题", "u", {})

        assert report.success is False
        assert report.error == "boom"


# ===========================================================================
# _emit_intent_event
# ===========================================================================
class TestEmitIntentEvent:
    async def test_reflex_success_emits_reflex_and_recognized(self, fake_domain):
        coord = _make_coord()
        report = ProcessingReport(
            success=True,
            processor_used=ProcessorType.REFLEX,
            latency_ms=1.5,
            result={"reflex_type": "greeting", "response": "您好"},
        )
        decision = RoutingDecision(ProcessorType.REFLEX, 0.9, "r")

        await coord._emit_intent_event("你好", "u9", report, decision)

        fake_domain.emit_reflex_triggered.assert_called_once()
        rk = fake_domain.emit_reflex_triggered.call_args.kwargs
        assert rk["reflex_type"] == "greeting"
        assert rk["user_id"] == "u9"
        fake_domain.emit_intent_recognized.assert_called_once()
        ek = fake_domain.emit_intent_recognized.call_args.kwargs
        assert ek["processor_used"] == "reflex"
        assert ek["raw_text"] == "你好"

    async def test_reflex_success_missing_reflex_type_defaults_unknown(self, fake_domain):
        """report.result 为 None / 缺 reflex_type → 用 'unknown'。"""
        coord = _make_coord()
        report = ProcessingReport(
            success=True,
            processor_used=ProcessorType.REFLEX,
            latency_ms=1.0,
            result=None,
        )
        decision = RoutingDecision(ProcessorType.REFLEX, 0.9, "r")

        await coord._emit_intent_event("hi", "", report, decision)

        rk = fake_domain.emit_reflex_triggered.call_args.kwargs
        assert rk["reflex_type"] == "unknown"

    async def test_non_reflex_success_only_recognized(self, fake_domain):
        coord = _make_coord()
        report = ProcessingReport(
            success=True,
            processor_used=ProcessorType.CONSCIOUS,
            latency_ms=10.0,
            result={"x": 1},
        )
        decision = RoutingDecision(ProcessorType.CONSCIOUS, 0.7, "c")

        await coord._emit_intent_event("问题", "u", report, decision)

        fake_domain.emit_reflex_triggered.assert_not_called()
        fake_domain.emit_intent_recognized.assert_called_once()
        assert fake_domain.emit_intent_recognized.call_args.kwargs["processor_used"] == "conscious"

    async def test_failure_emits_intent_failed(self, fake_domain):
        coord = _make_coord()
        report = ProcessingReport(
            success=False,
            processor_used=ProcessorType.CONSCIOUS,
            latency_ms=5.0,
            result=None,
            error="nope",
        )
        decision = RoutingDecision(ProcessorType.CONSCIOUS, 0.7, "c")

        await coord._emit_intent_event("问题", "u", report, decision)

        fake_domain.emit_intent_recognized.assert_not_called()
        fake_domain.emit_intent_failed.assert_called_once()
        fk = fake_domain.emit_intent_failed.call_args.kwargs
        assert fk["error"] == "nope"
        assert fk["user_id"] == "u"

    async def test_failure_default_error_message(self, fake_domain):
        coord = _make_coord()
        report = ProcessingReport(
            success=False,
            processor_used=ProcessorType.CONSCIOUS,
            latency_ms=5.0,
            result=None,
            error=None,
        )
        decision = RoutingDecision(ProcessorType.CONSCIOUS, 0.7, "c")

        await coord._emit_intent_event("问题", "u", report, decision)

        fk = fake_domain.emit_intent_failed.call_args.kwargs
        assert fk["error"] == "Processing failed"

    async def test_emit_exception_swallowed(self, monkeypatch):
        """get_intent_domain 抛 RECOVERABLE_ERRORS（bus down）→ 静默吞掉。"""

        def _boom():
            raise RuntimeError("bus down")

        monkeypatch.setattr(C, "get_intent_domain", _boom)
        coord = _make_coord()
        report = ProcessingReport(
            success=True,
            processor_used=ProcessorType.REFLEX,
            latency_ms=1.0,
            result={"reflex_type": "greeting"},
        )
        decision = RoutingDecision(ProcessorType.REFLEX, 0.9, "r")

        # 不应抛出
        await coord._emit_intent_event("你好", "u", report, decision)


# ===========================================================================
# process() — end to end
# ===========================================================================
class TestProcess:
    async def test_reflex_path(self, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(
            triggered=True, rtype=ReflexType.GREETING, confidence=0.9, response="您好"
        )
        coord = _make_coord(reflex=reflex)

        report = await coord.process("你好", user_id="u")

        assert report.success is True
        assert report.processor_used == ProcessorType.REFLEX
        assert report.fallback_used is False
        assert report.latency_ms >= 0.0
        fake_domain.emit_intent_recognized.assert_called_once()

    async def test_subconscious_path(self, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False, confidence=0.0)
        sub = MagicMock()
        sub.process = AsyncMock(return_value=True)
        coord = _make_coord(reflex=reflex, subconscious=sub)

        # 直接强制路由为 subconscious（route 默认会走 conscious，这里覆写决策）
        coord.route = MagicMock(return_value=RoutingDecision(ProcessorType.SUBCONSCIOUS, 0.9, "bg"))

        report = await coord.process("后台", user_id="u")

        assert report.processor_used == ProcessorType.SUBCONSCIOUS
        assert report.success is True
        sub.process.assert_awaited_once()

    async def test_conscious_success_no_fallback(self, fake_domain):
        reflex = MagicMock()
        reflex.process.return_value = _reflex(triggered=False, confidence=0.0)
        conscious = MagicMock()
        conscious.process = AsyncMock(
            return_value=MagicMock(success=True, data={"ok": 1}, error=None)
        )
        coord = _make_coord(reflex=reflex, conscious=conscious)

        report = await coord.process("问题", user_id="u")

        assert report.processor_used == ProcessorType.CONSCIOUS
        assert report.success is True
        assert report.fallback_used is False
        assert coord._fallback_count == 0

    async def test_conscious_fail_falls_back_to_reflex(self, fake_domain):
        """conscious 失败但 reflex 命中 → 降级，fallback_used=True。"""
        reflex = MagicMock()
        # route() 会先调一次 reflex.process（不触发，置信度 0），随后降级再调一次（触发）
        reflex.process.side_effect = [
            _reflex(triggered=False, confidence=0.0),  # route 阶段
            _reflex(triggered=True, rtype=ReflexType.GREETING, confidence=0.9),  # 降级阶段
        ]
        conscious = MagicMock()
        conscious.process = AsyncMock(
            return_value=MagicMock(success=False, data=None, error="conscious down")
        )
        coord = _make_coord(reflex=reflex, conscious=conscious)

        report = await coord.process("你好", user_id="u")

        assert report.fallback_used is True
        assert report.processor_used == ProcessorType.REFLEX
        assert report.success is True
        assert coord._fallback_count == 1

    async def test_conscious_fail_reflex_also_fails_keeps_conscious(self, fake_domain):
        """conscious 失败且 reflex 也不命中 → 保留 conscious 失败报告。"""
        reflex = MagicMock()
        reflex.process.side_effect = [
            _reflex(triggered=False, confidence=0.0),  # route 阶段
            _reflex(triggered=False, confidence=0.0),  # 降级阶段也失败
        ]
        conscious = MagicMock()
        conscious.process = AsyncMock(
            return_value=MagicMock(success=False, data=None, error="dead")
        )
        coord = _make_coord(reflex=reflex, conscious=conscious)

        report = await coord.process("问题", user_id="u")

        assert report.fallback_used is False
        assert report.processor_used == ProcessorType.CONSCIOUS
        assert report.success is False
        assert coord._fallback_count == 0

    async def test_recoverable_error_emergency_fallback_success(self, fake_domain):
        """处理中抛 RECOVERABLE_ERRORS → 紧急降级 reflex 成功。"""
        reflex = MagicMock()
        reflex.process.side_effect = [
            _reflex(triggered=False, confidence=0.0),  # route 阶段
            _reflex(triggered=True, rtype=ReflexType.GREETING, confidence=0.9),  # 紧急降级
        ]
        conscious = MagicMock()
        conscious.process = AsyncMock(side_effect=RuntimeError("crash"))
        coord = _make_coord(reflex=reflex, conscious=conscious)

        report = await coord.process("你好", user_id="u")

        assert report.success is True
        assert report.fallback_used is True
        assert report.processor_used == ProcessorType.REFLEX
        assert coord._error_count == 1
        assert coord._fallback_count == 1

    async def test_recoverable_error_fallback_fails_returns_fail_report(self, fake_domain):
        """处理中抛错且紧急降级 reflex 也不命中 → 返回失败报告并 emit failed。"""
        reflex = MagicMock()
        reflex.process.side_effect = [
            _reflex(triggered=False, confidence=0.0),  # route 阶段
            _reflex(triggered=False, confidence=0.0),  # 紧急降级也失败
        ]
        conscious = MagicMock()
        conscious.process = AsyncMock(side_effect=ValueError("bad data"))
        coord = _make_coord(reflex=reflex, conscious=conscious)

        report = await coord.process("问题", user_id="u")

        assert report.success is False
        assert report.processor_used == ProcessorType.CONSCIOUS
        assert report.error == "bad data"
        assert coord._error_count == 1
        assert coord._fallback_count == 0
        fake_domain.emit_intent_failed.assert_called_once()

    async def test_recoverable_error_fallback_also_raises_returns_fail_report(self, fake_domain):
        """紧急降级 reflex 自身又抛 RECOVERABLE_ERRORS → 内层 except 吞掉，仍返回失败报告。"""
        reflex = MagicMock()
        reflex.process.side_effect = [
            _reflex(triggered=False, confidence=0.0),  # route 阶段
            RuntimeError("reflex也炸了"),  # 紧急降级阶段抛错
        ]
        conscious = MagicMock()
        conscious.process = AsyncMock(side_effect=RuntimeError("crash"))
        coord = _make_coord(reflex=reflex, conscious=conscious)

        report = await coord.process("问题", user_id="u")

        assert report.success is False
        assert report.processor_used == ProcessorType.CONSCIOUS
        assert report.error == "crash"
        assert coord._error_count == 1


# ===========================================================================
# get_stats / get_all_processor_stats
# ===========================================================================
class TestStats:
    def test_get_stats_rates(self):
        coord = _make_coord()
        coord._reflex_count = 3
        coord._subconscious_count = 1
        coord._conscious_count = 6
        coord._fallback_count = 2
        coord._error_count = 1

        stats = coord.get_stats()

        assert stats["total"] == 10
        assert stats["reflex"] == 3
        assert stats["fallbacks"] == 2
        assert stats["errors"] == 1
        assert stats["reflex_rate"] == pytest.approx(0.3)
        assert stats["fallback_rate"] == pytest.approx(0.2)

    def test_get_stats_zero_total_no_div_error(self):
        coord = _make_coord()
        stats = coord.get_stats()
        assert stats["total"] == 0
        assert stats["reflex_rate"] == 0.0
        assert stats["fallback_rate"] == 0.0

    def test_get_all_processor_stats_aggregates(self):
        reflex = MagicMock()
        reflex.get_stats.return_value = {"r": 1}
        sub = MagicMock()
        sub.get_stats.return_value = {"s": 2}
        conscious = MagicMock()
        conscious.get_stats.return_value = {"c": 3}
        coord = _make_coord(reflex=reflex, subconscious=sub, conscious=conscious)

        out = coord.get_all_processor_stats()

        assert out["reflex"] == {"r": 1}
        assert out["subconscious"] == {"s": 2}
        assert out["conscious"] == {"c": 3}
        assert "coordinator" in out
        assert out["coordinator"]["total"] == 0


# ===========================================================================
# 便捷函数 + 单例
# ===========================================================================
class TestConvenienceFns:
    async def test_process_intent_delegates(self, monkeypatch, fake_domain):
        fake_coord = MagicMock()
        fake_coord.process = AsyncMock(
            return_value=ProcessingReport(
                success=True,
                processor_used=ProcessorType.REFLEX,
                latency_ms=1.0,
                result={"ok": True},
            )
        )
        monkeypatch.setattr(C, "get_processor_coordinator", lambda: fake_coord)

        out = await process_intent("你好", "u", {"c": 1})

        assert out.success is True
        fake_coord.process.assert_awaited_once_with("你好", "u", {"c": 1})

    def test_route_intent_returns_processor_type(self, monkeypatch):
        fake_coord = MagicMock()
        fake_coord.route.return_value = RoutingDecision(ProcessorType.SUBCONSCIOUS, 0.9, "bg")
        monkeypatch.setattr(C, "get_processor_coordinator", lambda: fake_coord)

        out = route_intent("后台")

        assert out == ProcessorType.SUBCONSCIOUS
        fake_coord.route.assert_called_once_with("后台")

    def test_get_processor_coordinator_singleton(self, monkeypatch):
        monkeypatch.setattr(C, "_coordinator", None)
        # 避免真实工厂去构造 reflex/subconscious/conscious 单例的副作用
        monkeypatch.setattr(C, "get_reflex_arc", lambda: MagicMock())
        monkeypatch.setattr(C, "get_subconscious_processor", lambda: MagicMock())
        monkeypatch.setattr(C, "get_conscious_processor", lambda: MagicMock())

        first = C.get_processor_coordinator()
        second = C.get_processor_coordinator()

        assert first is second
        assert isinstance(first, ProcessorCoordinator)
