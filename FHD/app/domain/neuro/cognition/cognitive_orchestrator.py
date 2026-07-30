"""认知编排器——把因果 / 技能 / 软约束 / 反思串成一次 Conscious 决策包。

不替代现有意图分类器；在其之上补开放世界与可解释因果。
"""

from __future__ import annotations

import logging
from typing import Any

from app.domain.neuro.cognition.counterfactual import CounterfactualProbe
from app.domain.neuro.cognition.plan_constraints import select_processor_by_cost
from app.domain.neuro.cognition.skill_contract import SkillRouter, get_skill_router
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class CognitiveOrchestrator:
    def __init__(
        self,
        skill_router: SkillRouter | None = None,
        counterfactual: CounterfactualProbe | None = None,
    ) -> None:
        self._skills = skill_router or get_skill_router()
        self._cf = counterfactual or CounterfactualProbe()

    def enrich_intent_result(
        self,
        intent_result: dict[str, Any],
        *,
        text: str = "",
        domain: str = "generic",
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        """增强意图结果：技能路由 + 可选反事实 + 软约束路径建议。"""
        out = dict(intent_result or {})
        raw = (
            text
            or str(out.get("raw_input") or out.get("text") or out.get("message") or "")
        ).strip()
        intent = (
            out.get("final_intent")
            or out.get("primary_intent")
            or out.get("tool_key")
            or out.get("deepseek_intent")
            or out.get("intent")
        )
        try:
            confidence = float(out.get("confidence") or out.get("intent_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        skill_route = self._skills.route_open_world(
            raw,
            intent=str(intent) if intent else None,
            domain=domain,
            confidence=confidence,
        )
        out["skill_route"] = skill_route

        # 反事实探针（高风险 / 履约问句）
        cf_block: dict[str, Any] | None = None
        if self._cf.should_probe(risk_level=risk_level, text=raw):
            intervention = self._pick_intervention(raw, out)
            observed = {}
            slots = out.get("slots") if isinstance(out.get("slots"), dict) else {}
            if "缺货" in raw or slots.get("shortage"):
                observed["inventory.shortage"] = True
            cf_block = self._cf.probe(intervention, observed=observed).to_dict()
        out["counterfactual"] = cf_block

        # 软约束路径建议（供 CognitiveRouter / planner 参考）
        prefer = "conscious" if skill_route.get("status") == "skill_proposal" else None
        if confidence >= 0.85 and skill_route.get("status") == "skill_candidate":
            prefer = "reflex"
        out["path_suggestion"] = select_processor_by_cost(prefer=prefer)

        return out

    def after_execution(
        self,
        *,
        success: bool,
        selected_processor: str,
        suggested_processor: str | None = None,
        latency_ms: float = 0.0,
        sla_hit: bool | None = None,
        trace_id: str | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        """执行后：反馈学习 + 可选反思（选错层）。"""
        # 惰性导入 evolution，避免 cognition↔application 启动环。
        from app.domain.neuro.evolution.learning_feedback import record_task_outcome
        from app.domain.neuro.evolution.self_reflection import get_self_reflection_engine

        fb = record_task_outcome(
            success=success,
            processor=selected_processor,
            latency_ms=latency_ms,
            sla_hit=sla_hit,
            trace_id=trace_id,
            note=note,
        )
        reflection = None
        if (
            suggested_processor
            and suggested_processor != selected_processor
            and not success
        ):
            try:
                patch = get_self_reflection_engine().reflect_on_routing_mistake(
                    selected=selected_processor,
                    better=suggested_processor,
                    reason=note or "task_failed_after_suboptimal_route",
                    metrics={"latency_ms": latency_ms, "sla_hit": sla_hit},
                )
                # 自动进入 shadow，不直接 promote
                get_self_reflection_engine().advance(patch.patch_id, to_stage="shadow")
                reflection = patch.to_dict()
                reflection["stage"] = "shadow"
            except RECOVERABLE_ERRORS:
                logger.debug("reflection after_execution failed", exc_info=True)
        return {"feedback": fb, "reflection": reflection}

    def _pick_intervention(self, text: str, intent_result: dict[str, Any]) -> str:
        if "补货" in text:
            return "补货"
        if "缺货" in text:
            return "缺货"
        if "延期" in text or "交期" in text:
            return "改交期"
        if "发货" in text:
            return "发货"
        skill = (intent_result.get("skill_route") or {}).get("skill") or {}
        if skill.get("uses_causal_graph"):
            return "缺货"
        return "确认订单"


_orchestrator: CognitiveOrchestrator | None = None


def get_cognitive_orchestrator() -> CognitiveOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CognitiveOrchestrator()
    return _orchestrator


def reset_cognitive_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
