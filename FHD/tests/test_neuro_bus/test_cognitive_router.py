"""CognitiveRouter 单元测试。

验证：
- MLP 未启用时回退 None（向后兼容）
- shadow 模式记录决策但不路由
- full 模式返回 RoutingDecision
- record_outcome 写入反馈闭环数据（sla_hit/success/reward）
- is_sla_hit 按处理器分级阈值判断
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.domain.neuro.processors.coordinator import ProcessorType, RoutingDecision
from app.neuro_bus.routing.cognitive_router import (
    CognitiveRouter,
    get_cognitive_router,
    reset_cognitive_router,
)


def _read_rows(log_path: Path) -> list[dict]:
    text = log_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [json.loads(line) for line in text.split("\n") if line]


@pytest.fixture(autouse=True)
def _reset_router(monkeypatch):
    """每个测试前后重置单例和 canary 缓存，避免状态泄漏。"""
    reset_cognitive_router()
    # 重置 policy_router 的 canary 缓存（模块级全局，跨测试会泄漏）
    import app.neuro_bus.routing.policy_router as pr

    monkeypatch.setattr(pr, "_canary_cache", None)
    monkeypatch.setattr(pr, "_canary_cache_ts", 0.0)
    yield
    reset_cognitive_router()


@pytest.fixture
def clean_env(monkeypatch):
    """清除所有路由相关环境变量，确保从干净状态开始。"""
    for key in (
        "XCAGI_ROUTING_POLICY_ENABLED",
        "XCAGI_ROUTING_POLICY_CANARY_RATIO",
        "XCAGI_ROUTING_CANARY_STATE",
        "XCAGI_ROUTING_LOG_PATH",
    ):
        monkeypatch.delenv(key, raising=False)
    yield monkeypatch


class TestCognitiveRouterRoute:
    """route() 方法测试。"""

    def test_route_returns_none_when_disabled(self, clean_env, tmp_path):
        """MLP 未启用时返回 (None, trace_id)，调用方回退规则路由。"""
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "log.jsonl"))
        router = CognitiveRouter()

        decision, trace_id = router.route("你好")

        assert decision is None
        assert isinstance(trace_id, str)
        assert len(trace_id) > 0

    def test_route_returns_none_in_shadow_mode(self, clean_env, tmp_path):
        """shadow 模式：记录决策到日志但不路由，返回 None。"""
        pytest.importorskip("torch")  # MLP 策略需 torch；CI 未装 ml 依赖时跳过
        log_path = tmp_path / "log.jsonl"
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))
        clean_env.setenv("XCAGI_ROUTING_POLICY_ENABLED", "shadow")

        router = CognitiveRouter()
        decision, trace_id = router.route("帮我查订单")

        assert decision is None
        rows = _read_rows(log_path)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "policy_shadow"
        assert rows[0]["trace_id"] == trace_id

    def test_route_returns_decision_in_full_mode(self, clean_env, tmp_path):
        """full 模式 + canary_ratio=1.0：返回 RoutingDecision，MLP 决策生效。"""
        pytest.importorskip("torch")  # MLP 策略需 torch；CI 未装 ml 依赖时跳过
        log_path = tmp_path / "log.jsonl"
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))
        clean_env.setenv("XCAGI_ROUTING_POLICY_ENABLED", "full")
        clean_env.setenv("XCAGI_ROUTING_POLICY_CANARY_RATIO", "1.0")

        router = CognitiveRouter()
        decision, trace_id = router.route("帮我查订单")

        # MLP v2 已加载，full 模式 + canary_ratio=1.0 应返回决策
        assert decision is not None
        assert isinstance(decision, RoutingDecision)
        assert decision.processor_type in (
            ProcessorType.REFLEX,
            ProcessorType.SUBCONSCIOUS,
            ProcessorType.CONSCIOUS,
        )
        assert isinstance(decision.confidence, float)
        rows = _read_rows(log_path)
        assert len(rows) >= 1
        assert rows[0]["outcome"] == "policy_selected"

    def test_route_with_explicit_trace_id(self, clean_env, tmp_path):
        """传入 trace_id 时使用它，不生成新的。"""
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "log.jsonl"))
        router = CognitiveRouter()

        _, trace_id = router.route("你好", trace_id="my-trace-123")

        assert trace_id == "my-trace-123"

    def test_route_generates_trace_id_when_none(self, clean_env, tmp_path):
        """未传 trace_id 时自动生成。"""
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "log.jsonl"))
        router = CognitiveRouter()

        _, trace_id_a = router.route("你好")
        _, trace_id_b = router.route("你好")

        assert trace_id_a != trace_id_b

    def test_route_swallows_exceptions_and_returns_none(self, clean_env, tmp_path):
        """policy_router 抛异常时优雅降级返回 None。"""
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "log.jsonl"))
        router = CognitiveRouter()

        with patch(
            "app.neuro_bus.routing.cognitive_router.decide_processor_with_policy",
            side_effect=RuntimeError("boom"),
        ):
            decision, trace_id = router.route("你好")

        assert decision is None
        assert isinstance(trace_id, str)


class TestCognitiveRouterRecordOutcome:
    """record_outcome() 方法测试。"""

    def test_record_outcome_writes_completed_row(self, clean_env, tmp_path):
        """记录路由结果，写入 outcome=policy_completed 行。"""
        log_path = tmp_path / "log.jsonl"
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(log_path))
        router = CognitiveRouter()

        router.record_outcome(
            trace_id="tid-out-1",
            processor_type=ProcessorType.CONSCIOUS,
            features=[0.1, 0.2],
            latency_ms=150.0,
            sla_hit=True,
            success=True,
            confidence=0.85,
        )

        rows = _read_rows(log_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["trace_id"] == "tid-out-1"
        assert row["action"] == "conscious"
        assert row["outcome"] == "policy_completed"
        assert row["sla_hit"] is True
        assert row["success"] is True
        assert row["reward"] == pytest.approx(1.0)  # 1*0.6 + 1*0.4
        assert row["extra"]["confidence"] == 0.85

    def test_record_outcome_reward_calculation(self, clean_env, tmp_path):
        """reward = sla_hit * 0.6 + success * 0.4 正确计算。"""
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "log.jsonl"))
        router = CognitiveRouter()

        cases = [
            (True, True, 1.0),
            (True, False, 0.6),
            (False, True, 0.4),
            (False, False, 0.0),
        ]
        for i, (sla, succ, expected) in enumerate(cases):
            router.record_outcome(
                trace_id=f"tid-{i}",
                processor_type=ProcessorType.REFLEX,
                features=None,
                latency_ms=1.0,
                sla_hit=sla,
                success=succ,
            )

        rows = _read_rows(tmp_path / "log.jsonl")
        for i, (_, _, expected) in enumerate(cases):
            assert rows[i]["reward"] == pytest.approx(expected)

    def test_record_outcome_swallows_exceptions(self, clean_env, tmp_path):
        """append_routing_decision 失败时不抛异常。"""
        clean_env.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "log.jsonl"))
        router = CognitiveRouter()

        with patch(
            "app.neuro_bus.routing.cognitive_router.append_routing_decision",
            side_effect=OSError("disk full"),
        ):
            router.record_outcome(
                trace_id="tid-err",
                processor_type=ProcessorType.REFLEX,
                features=None,
                latency_ms=1.0,
                sla_hit=True,
                success=True,
            )
        # 不抛异常即通过


class TestCognitiveRouterSlaHit:
    """is_sla_hit() 静态方法测试。"""

    def test_reflex_sla_threshold(self):
        """Reflex SLA 阈值 1ms。"""
        assert CognitiveRouter.is_sla_hit(ProcessorType.REFLEX, 0.5) is True
        assert CognitiveRouter.is_sla_hit(ProcessorType.REFLEX, 1.0) is True
        assert CognitiveRouter.is_sla_hit(ProcessorType.REFLEX, 1.5) is False

    def test_subconscious_sla_threshold(self):
        """Subconscious SLA 阈值 10ms。"""
        assert CognitiveRouter.is_sla_hit(ProcessorType.SUBCONSCIOUS, 5.0) is True
        assert CognitiveRouter.is_sla_hit(ProcessorType.SUBCONSCIOUS, 10.0) is True
        assert CognitiveRouter.is_sla_hit(ProcessorType.SUBCONSCIOUS, 15.0) is False

    def test_conscious_sla_threshold(self):
        """Conscious SLA 阈值 200ms。"""
        assert CognitiveRouter.is_sla_hit(ProcessorType.CONSCIOUS, 100.0) is True
        assert CognitiveRouter.is_sla_hit(ProcessorType.CONSCIOUS, 200.0) is True
        assert CognitiveRouter.is_sla_hit(ProcessorType.CONSCIOUS, 250.0) is False


class TestCognitiveRouterIsEnabled:
    """is_enabled() 静态方法测试。"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("shadow", True),
            ("canary", True),
            ("full", True),
            ("TRUE", True),
            ("", False),
            ("0", False),
            ("false", False),
            ("off", False),
            ("no", False),
            (None, False),
        ],
    )
    def test_is_enabled_env_var_parsing(self, clean_env, value, expected):
        if value is not None:
            clean_env.setenv("XCAGI_ROUTING_POLICY_ENABLED", value)
        assert CognitiveRouter.is_enabled() is (expected if value is not None else False)


class TestCognitiveRouterSingleton:
    """get_cognitive_router() 单例测试。"""

    def test_singleton_returns_same_instance(self):
        router1 = get_cognitive_router()
        router2 = get_cognitive_router()
        assert router1 is router2

    def test_reset_clears_singleton(self):
        router1 = get_cognitive_router()
        reset_cognitive_router()
        router2 = get_cognitive_router()
        assert router1 is not router2
