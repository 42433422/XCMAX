"""认知全栈：因果 / 技能契约 / 软约束 / 学习反馈 / 自我反思。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.neuro.cognition.causal_graph import (
    explain_relatedness,
    get_order_fulfillment_graph,
    reset_causal_graph_cache,
)
from app.domain.neuro.cognition.cognitive_orchestrator import (
    CognitiveOrchestrator,
    reset_cognitive_orchestrator,
)
from app.domain.neuro.cognition.counterfactual import CounterfactualProbe
from app.domain.neuro.cognition.plan_constraints import (
    SoftConstraints,
    is_sla_hit_soft,
    save_soft_constraints,
    select_processor_by_cost,
)
from app.domain.neuro.cognition.plan_graph_log import append_plan_graph, requires_plan_log
from app.domain.neuro.cognition.skill_contract import (
    SkillRouter,
    reset_skill_router,
)
from app.domain.neuro.evolution.learning_feedback import FeedbackEvent
from app.domain.neuro.evolution.self_reflection import (
    REFLECT_DENYLIST,
    SelfReflectionEngine,
    reset_self_reflection_engine,
)


@pytest.fixture(autouse=True)
def _reset_singletons(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_REFLECTION_LEDGER", str(tmp_path / "reflection.jsonl"))
    monkeypatch.setenv("XCAGI_PLAN_GRAPH_LOG", str(tmp_path / "plans.jsonl"))
    monkeypatch.setenv("XCAGI_ROUTING_LOG_PATH", str(tmp_path / "routing.jsonl"))
    monkeypatch.setenv("XCAGI_SOFT_CONSTRAINTS_PATH", str(tmp_path / "soft.json"))
    reset_causal_graph_cache()
    reset_skill_router()
    reset_cognitive_orchestrator()
    reset_self_reflection_engine()
    yield
    reset_causal_graph_cache()
    reset_skill_router()
    reset_cognitive_orchestrator()
    reset_self_reflection_engine()


def test_causal_graph_distinguishes_intervenable_from_correlation():
    g = get_order_fulfillment_graph()
    assert g.graph_id == "order_fulfillment_scm_lite"
    assert any(e.is_intervenable for e in g.edges)
    causal = explain_relatedness("inventory.shortage", "delivery.delay", graph=g)
    assert causal["kind"] == "causal"
    assert causal["intervenable"] is True
    corr = explain_relatedness("payment.received", "customer.satisfaction", graph=g)
    assert corr["kind"] == "correlational"
    assert corr["intervenable"] is False


def test_counterfactual_probe_on_shortage():
    report = CounterfactualProbe().probe("补货", observed={"inventory.shortage": True})
    assert report.do_node == "inventory.shortage"
    assert report.effects
    assert any(e.kind == "causal" for e in report.effects)
    assert "可干预" in report.narrative or "inventory" in report.narrative


def test_skill_router_open_world_and_bootstrap():
    router = SkillRouter()
    hit = router.match("帮我开一张发货单", intent="shipment_generate")
    assert hit
    assert hit[0].skill.skill_id == "ship.generate"
    assert hit[0].reason == "bootstrap_intent"

    open_route = router.route_open_world("帮我做一套从没见过的合规审计流程", confidence=0.1)
    assert open_route["status"] == "skill_proposal"
    assert open_route["proposal"]["proposed_skill_id"].startswith("open.")


def test_soft_constraints_select_and_sla_slack(tmp_path, monkeypatch):
    path = tmp_path / "soft.json"
    monkeypatch.setenv("XCAGI_SOFT_CONSTRAINTS_PATH", str(path))
    save_soft_constraints(SoftConstraints(), path=path)
    decision = select_processor_by_cost(prefer="reflex")
    assert decision["mode"] == "soft_constraint"
    assert decision["selected"] in {"reflex", "subconscious", "conscious"}
    assert is_sla_hit_soft("conscious", 240.0, slack=1.25) is True
    assert is_sla_hit_soft("conscious", 900.0, slack=1.25) is False


def test_plan_graph_log_requires_multistep(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_PLAN_GRAPH_LOG", str(tmp_path / "plans.jsonl"))

    class _N:
        def __init__(self, i):
            self.node_id = f"n{i}"
            self.tool_id = "t"
            self.action = "query"
            self.depends_on = []

    class _P:
        plan_id = "p1"
        intent = "demo"
        todo_steps = ["a", "b"]
        nodes = [_N(1), _N(2)]
        risk_level = "low"
        metadata = {}

    plan = _P()
    assert requires_plan_log(plan) is True
    assert append_plan_graph(plan, phase="planned") is True
    lines = (tmp_path / "plans.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["node_count"] == 2


def test_learning_feedback_reward_bounds():
    low = FeedbackEvent(kind="user_correction", success=False).reward()
    high = FeedbackEvent(kind="task_outcome", success=True, confidence=0.9).reward()
    assert 0.0 <= low <= 0.3
    assert high >= 0.8


def test_self_reflection_whitelist_and_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv("XCAGI_REFLECTION_LEDGER", str(tmp_path / "reflection.jsonl"))
    monkeypatch.setenv("XCAGI_SOFT_CONSTRAINTS_PATH", str(tmp_path / "soft.json"))
    engine = SelfReflectionEngine()

    denied = engine.critique_and_propose(
        target="cognitive_architecture",
        critique="想重写处理器拓扑",
        proposal={"action": "rewrite"},
    )
    assert denied.stage == "rejected"
    assert "cognitive_architecture" in REFLECT_DENYLIST

    patch = engine.critique_and_propose(
        target="soft_constraints",
        critique="conscious 太慢，提高 latency 权重",
        proposal={"w_latency": 0.55},
    )
    assert patch.stage == "proposed"
    assert engine.advance(patch.patch_id, to_stage="shadow") is not None
    assert engine.advance(patch.patch_id, to_stage="canary") is not None
    promoted = engine.advance(patch.patch_id, to_stage="promoted")
    assert promoted is not None
    assert promoted.stage == "promoted"
    soft = json.loads(Path(tmp_path / "soft.json").read_text(encoding="utf-8"))
    assert soft["w_latency"] == pytest.approx(0.55)


def test_orchestrator_enriches_unknown_intent():
    orch = CognitiveOrchestrator()
    out = orch.enrich_intent_result(
        {"intent": "unk", "confidence": 0.1, "text": "订单为什么延期了缺货吗"},
        text="订单为什么延期了缺货吗",
        risk_level="high",
    )
    assert out["skill_route"]["status"] in {"skill_candidate", "skill_proposal"}
    assert out["counterfactual"] is not None
    assert out["path_suggestion"]["mode"] == "soft_constraint"


def test_intent_confirmation_uses_skill_candidate():
    from app.services.intent_confirmation_service import IntentConfirmationService

    svc = IntentConfirmationService()
    result = svc.check_and_build_prompt(
        {
            "final_intent": "unk",
            "raw_input": "帮客户发货出一张发货单",
            "slots": {},
            "domain": "generic",
        }
    )
    assert result["status"] in {"missing_slots", "complete", "unclear"}
    assert "skill_route" in result
