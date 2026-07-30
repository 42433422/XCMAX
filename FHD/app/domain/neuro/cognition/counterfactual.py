"""反事实探针——在高风险决策前沿因果图推演「若改 X，Y 会怎样」。

不做统计因果发现；用 SCM lite 边 + 观测状态做可解释推演。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.domain.neuro.cognition.causal_graph import (
    CausalGraph,
    get_order_fulfillment_graph,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class CounterfactualEffect:
    node_id: str
    direction: str  # increase | decrease | unclear
    magnitude: float
    via_intervention: str | None
    kind: str  # causal | correlational


@dataclass
class CounterfactualReport:
    intervention: str
    do_node: str
    effects: list[CounterfactualEffect] = field(default_factory=list)
    narrative: str = ""
    graph_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intervention": self.intervention,
            "do_node": self.do_node,
            "graph_id": self.graph_id,
            "narrative": self.narrative,
            "effects": [
                {
                    "node_id": e.node_id,
                    "direction": e.direction,
                    "magnitude": e.magnitude,
                    "via_intervention": e.via_intervention,
                    "kind": e.kind,
                }
                for e in self.effects
            ],
        }


# 常见业务干预 → 图节点
_INTERVENTION_ALIASES: dict[str, str] = {
    "缺货": "inventory.shortage",
    "shortage": "inventory.shortage",
    "inventory.shortage": "inventory.shortage",
    "改交期": "delivery.delay",
    "延期": "delivery.delay",
    "delivery.delay": "delivery.delay",
    "换客户": "order.created",
    "确认订单": "order.created",
    "confirm_order": "order.created",
    "补货": "inventory.shortage",
    "replenish_or_split": "inventory.shortage",
    "发货": "shipment.dispatched",
    "dispatch_shipment": "shipment.dispatched",
}


class CounterfactualProbe:
    """沿因果边做 do-intervention 推演。"""

    def __init__(self, graph: CausalGraph | None = None) -> None:
        self._graph = graph or get_order_fulfillment_graph()

    def resolve_do_node(self, intervention: str) -> str | None:
        key = str(intervention or "").strip()
        if not key:
            return None
        if key in self._graph.nodes:
            return key
        return _INTERVENTION_ALIASES.get(key) or _INTERVENTION_ALIASES.get(key.lower())

    def probe(
        self,
        intervention: str,
        *,
        observed: dict[str, Any] | None = None,
        depth: int = 3,
    ) -> CounterfactualReport:
        """对 intervention 做 do() 推演，返回下游效应。"""
        observed = observed or {}
        do_node = self.resolve_do_node(intervention)
        if not do_node:
            return CounterfactualReport(
                intervention=intervention,
                do_node="",
                narrative="unknown_intervention",
                graph_id=self._graph.graph_id,
            )

        effects: list[CounterfactualEffect] = []
        frontier = [do_node]
        seen = {do_node}
        for _ in range(max(1, depth)):
            next_frontier: list[str] = []
            for node in frontier:
                for edge in self._graph.children(node):
                    if edge.target in seen:
                        continue
                    seen.add(edge.target)
                    next_frontier.append(edge.target)
                    kind = (
                        "correlational"
                        if edge.relation == "correlates_with" or not edge.intervention
                        else "causal"
                    )
                    # 缺货类节点被「补货」干预时，延迟应下降
                    polarity = edge.sign
                    if do_node == "inventory.shortage" and intervention in {
                        "补货",
                        "replenish_or_split",
                        "缺货",
                    }:
                        # do(缺货=缓解) → 反转 shortage 下游负向
                        if intervention in {"补货", "replenish_or_split"}:
                            polarity = -edge.sign
                    direction = (
                        "increase" if polarity > 0 else "decrease" if polarity < 0 else "unclear"
                    )
                    # 观测到已存在短缺时放大量级
                    mag = edge.strength
                    if observed.get("inventory.shortage") and edge.source == "inventory.shortage":
                        mag = min(1.0, mag + 0.1)
                    effects.append(
                        CounterfactualEffect(
                            node_id=edge.target,
                            direction=direction,
                            magnitude=round(mag, 3),
                            via_intervention=edge.intervention,
                            kind=kind,
                        )
                    )
            frontier = next_frontier
            if not frontier:
                break

        narrative = self._narrative(intervention, do_node, effects)
        return CounterfactualReport(
            intervention=intervention,
            do_node=do_node,
            effects=effects,
            narrative=narrative,
            graph_id=self._graph.graph_id,
        )

    def _narrative(
        self,
        intervention: str,
        do_node: str,
        effects: list[CounterfactualEffect],
    ) -> str:
        if not effects:
            return f"对 {do_node} 施加「{intervention}」后，图中未见下游效应。"
        causal = [e for e in effects if e.kind == "causal"]
        corr = [e for e in effects if e.kind == "correlational"]
        parts = [f"若执行「{intervention}」(do={do_node})："]
        for e in causal[:4]:
            parts.append(
                f"可干预因果 → {e.node_id} 倾向{e.direction}(强度{e.magnitude})"
                + (f"，动作={e.via_intervention}" if e.via_intervention else "")
            )
        for e in corr[:2]:
            parts.append(f"仅相关 → {e.node_id}（不可当作主因干预）")
        return "；".join(parts)

    def should_probe(self, *, risk_level: str | None, text: str = "") -> bool:
        """高风险或多步履约问句时启用探针。"""
        risk = (risk_level or "").strip().lower()
        if risk in {"high", "critical"}:
            return True
        markers = ("为什么", "原因", "延期", "缺货", "交期", "因果", "若", "如果")
        return any(m in (text or "") for m in markers)


def probe_counterfactual(
    intervention: str,
    *,
    observed: dict[str, Any] | None = None,
    graph: CausalGraph | None = None,
) -> dict[str, Any]:
    """便捷函数：返回 dict，供 Conscious / API 注入。"""
    try:
        report = CounterfactualProbe(graph).probe(intervention, observed=observed)
        return report.to_dict()
    except RECOVERABLE_ERRORS:
        logger.debug("probe_counterfactual failed", exc_info=True)
        return {
            "intervention": intervention,
            "do_node": "",
            "effects": [],
            "narrative": "probe_failed",
            "graph_id": "",
        }
