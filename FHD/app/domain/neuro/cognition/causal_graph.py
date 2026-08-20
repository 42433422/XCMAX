"""业务因果图（SCM lite）——相关性检索之上的可干预因果层。

只覆盖订单履约样板链，不做全量因果发现。节点=可观测事件/状态，
边=可干预动作。检索仍可做召回；决策与解释走本图。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CausalEdge:
    source: str
    target: str
    relation: str
    intervention: str | None
    strength: float
    sign: int = 1
    note: str = ""

    @property
    def is_intervenable(self) -> bool:
        return bool(self.intervention) and self.relation != "correlates_with"


@dataclass
class CausalGraph:
    graph_id: str
    version: str
    nodes: set[str] = field(default_factory=set)
    edges: list[CausalEdge] = field(default_factory=list)

    def children(self, node_id: str) -> list[CausalEdge]:
        return [e for e in self.edges if e.source == node_id]

    def parents(self, node_id: str) -> list[CausalEdge]:
        return [e for e in self.edges if e.target == node_id]

    def intervenable_edges(self) -> list[CausalEdge]:
        return [e for e in self.edges if e.is_intervenable]

    def classify_link(self, source: str, target: str) -> str:
        """返回 causal | correlational | unknown。"""
        for edge in self.edges:
            if edge.source == source and edge.target == target:
                if edge.relation == "correlates_with" or not edge.intervention:
                    return "correlational"
                return "causal"
        return "unknown"


def _default_graph_path() -> Path:
    return Path(__file__).resolve().parents[4] / "resources" / "neuro" / "causal_order_chain.json"


def load_causal_graph(path: Path | None = None) -> CausalGraph:
    """加载 SCM lite JSON；失败时返回空图（best-effort）。"""
    graph_path = path or _default_graph_path()
    try:
        raw = json.loads(graph_path.read_text(encoding="utf-8"))
    except RECOVERABLE_ERRORS:
        logger.debug("load_causal_graph failed: %s", graph_path, exc_info=True)
        return CausalGraph(graph_id="empty", version="0")

    nodes = {str(n.get("id")) for n in (raw.get("nodes") or []) if n.get("id")}
    edges: list[CausalEdge] = []
    for item in raw.get("edges") or []:
        if not isinstance(item, dict):
            continue
        src = str(item.get("from") or "").strip()
        dst = str(item.get("to") or "").strip()
        if not src or not dst:
            continue
        try:
            strength = float(item.get("strength") or 0.0)
        except (TypeError, ValueError):
            strength = 0.0
        try:
            raw_sign = item.get("sign")
            sign = int(1 if raw_sign is None else raw_sign)
        except (TypeError, ValueError):
            sign = 1
        intervention = item.get("intervention")
        edges.append(
            CausalEdge(
                source=src,
                target=dst,
                relation=str(item.get("relation") or "causes"),
                intervention=str(intervention) if intervention else None,
                strength=max(0.0, min(1.0, strength)),
                sign=1 if sign >= 0 else -1,
                note=str(item.get("note") or ""),
            )
        )
    return CausalGraph(
        graph_id=str(raw.get("graph_id") or "unnamed"),
        version=str(raw.get("version") or "0"),
        nodes=nodes,
        edges=edges,
    )


@lru_cache(maxsize=1)
def get_order_fulfillment_graph() -> CausalGraph:
    return load_causal_graph()


def reset_causal_graph_cache() -> None:
    get_order_fulfillment_graph.cache_clear()


def explain_relatedness(
    source: str,
    target: str,
    *,
    graph: CausalGraph | None = None,
) -> dict[str, Any]:
    """区分「相关」与「可干预原因」。"""
    g = graph or get_order_fulfillment_graph()
    kind = g.classify_link(source, target)
    matched = next((e for e in g.edges if e.source == source and e.target == target), None)
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "intervenable": bool(matched and matched.is_intervenable),
        "intervention": matched.intervention if matched else None,
        "strength": matched.strength if matched else 0.0,
        "note": matched.note if matched else "",
        "graph_id": g.graph_id,
    }
