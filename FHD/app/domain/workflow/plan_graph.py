"""Pure plan-graph value objects shared by workflow ports and application code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass
class Branch:
    """条件边：按上一节点 output 匹配决定后续节点。

    - ``target``：后续节点 id。
    - ``condition``：匹配描述，如 ``{"key": "low_stock", "equals": true}`` 或
      ``{"key": "status", "equals": "ok"}``。
    """

    target: str
    condition: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowNode:
    node_id: str
    tool_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    risk: RiskLevel = "low"
    idempotent: bool = False
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    # ``next`` 为无条件默认后继；``branches`` 为按 output 匹配的条件后继。
    next: str | None = None
    branches: list[Branch] = field(default_factory=list)


@dataclass
class PlanGraph:
    plan_id: str
    intent: str
    todo_steps: list[str] = field(default_factory=list)
    nodes: list[WorkflowNode] = field(default_factory=list)
    risk_level: RiskLevel = "low"
    metadata: dict[str, Any] = field(default_factory=dict)
