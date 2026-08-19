from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, cast

RiskLevel = Literal["low", "medium", "high"]

MergeSemantics = Literal["set", "append", "merge_dict"]


def normalize_workflow_risk(value: object, *, default: RiskLevel = "medium") -> RiskLevel:
    """Normalize untrusted plan metadata to the workflow risk literal."""
    text = str(value or default).strip().lower()
    if text in {"low", "medium", "high"}:
        return cast(RiskLevel, text)
    return default


@dataclass(frozen=True)
class StateField:
    """为 runtime_context 中一个 key 声明其类型与合并语义。

    - ``type``：期望的类型（str/int/float/bool/list/dict）或任意可调用谓词；None 表示不校验。
    - ``merge``：节点写入该 key 时的合并语义，默认 "set"。
    """

    key: str
    type: Any = None
    merge: MergeSemantics = "set"


@dataclass
class StateSchema:
    """类型化 StateSchema：为 runtime_context 的 key 集合声明类型与合并语义。"""

    fields: dict[str, StateField] = field(default_factory=dict)

    def declare(
        self,
        key: str,
        type: Any = None,
        merge: MergeSemantics = "set",
    ) -> StateSchema:
        self.fields[key] = StateField(key=key, type=type, merge=merge)
        return self

    def get(self, key: str) -> StateField | None:
        return self.fields.get(key)


def _type_matches(value: Any, expected: Any) -> bool:
    if expected is None:
        return True
    if expected is bool:
        return isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is str:
        return isinstance(value, str)
    if expected is list:
        return isinstance(value, list)
    if expected is dict:
        return isinstance(value, dict)
    if isinstance(expected, type):
        return isinstance(value, expected)
    if callable(expected):
        try:
            return bool(expected(value))
        except (ValueError, TypeError):
            return False
    return False


def _validate_and_merge(
    result: dict[str, Any],
    key: str,
    value: Any,
    field: StateField,
) -> None:
    if field.merge == "set":
        if field.type is not None and not _type_matches(value, field.type):
            raise ValueError(
                f"StateSchema 字段 '{key}' 类型不符: 期望 {_describe_type(field.type)}, "
                f"实际 {_describe_type(type(value))}"
            )
        result[key] = value
        return

    if field.merge == "append":
        # 该 key 的累积结果是一个 list；field.type 为 list 时视为"累积器"声明，
        # 不逐项校验；否则按元素类型校验被追加的值。
        if (
            field.type is not None
            and field.type is not list
            and not _type_matches(value, field.type)
        ):
            raise ValueError(
                f"StateSchema 字段 '{key}' 'append' 元素类型不符: 期望 "
                f"{_describe_type(field.type)}, 实际 {_describe_type(type(value))}"
            )
        existing = result.get(key)
        if existing is None:
            result[key] = [value]
        elif isinstance(existing, list):
            existing.append(value)
        else:
            raise ValueError(
                f"StateSchema 字段 '{key}' 'append' 失败: 当前值不是 list "
                f"(实际 {type(existing).__name__})"
            )
        return

    if field.merge == "merge_dict":
        if not isinstance(value, dict):
            raise ValueError(
                f"StateSchema 字段 '{key}' 'merge_dict' 失败: 写入值不是 dict "
                f"(实际 {type(value).__name__})"
            )
        existing = result.get(key)
        if existing is None:
            result[key] = dict(value)
        elif isinstance(existing, dict):
            existing.update(value)
        else:
            raise ValueError(
                f"StateSchema 字段 '{key}' 'merge_dict' 失败: 当前值不是 dict "
                f"(实际 {type(existing).__name__})"
            )
        return

    raise ValueError(f"未知 merge 语义 '{field.merge}'")


def _describe_type(expected: Any) -> str:
    return getattr(expected, "__name__", str(expected))


def apply_state_schema(
    context: dict[str, Any],
    schema: StateSchema,
    writes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """校验 context 并合并节点写入的状态。

    - 对 ``writes`` 中每个 key：按 schema 声明的类型校验，再按 merge 语义归并进 context。
      （未在 schema 中声明的 key 走默认 "set"，不校验。）
    - 对 context 中已存在、但本轮 ``writes`` 未涉及的 schema key 做类型校验。
    - 类型或合并语义不符时抛出带明确信息的 ValueError，绝不静默丢数据。
    """
    result = dict(context or {})
    writes = writes or {}
    field_map = schema.fields if schema is not None else {}

    for key, value in writes.items():
        field = field_map.get(key)
        if field is not None:
            _validate_and_merge(result, key, value, field)
        else:
            result[key] = value

    for key, field in field_map.items():
        if key in writes:
            continue  # 本轮写入已在上层校验/归并
        if key not in result or result[key] is None:
            continue
        expected = field.type
        if field.merge == "append":
            # 仅校验累积容器必须是 list（元素类型在写入时已校验）
            if not isinstance(result[key], list):
                raise ValueError(
                    f"StateSchema 字段 '{key}' 'append' 校验失败: 当前值不是 list "
                    f"(实际 {type(result[key]).__name__})"
                )
        elif field.merge == "merge_dict":
            if not isinstance(result[key], dict):
                raise ValueError(
                    f"StateSchema 字段 '{key}' 'merge_dict' 校验失败: 当前值不是 dict "
                    f"(实际 {type(result[key]).__name__})"
                )
        elif expected is not None and not _type_matches(result[key], expected):
            raise ValueError(
                f"StateSchema 字段 '{key}' 类型不符: 期望 {_describe_type(expected)}, "
                f"实际 {_describe_type(type(result[key]))}"
            )

    return result


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ApprovalTrigger(str, Enum):
    ALWAYS = "always"
    NEVER = "never"
    CONDITIONAL = "conditional"


@dataclass
class ApprovalRule:
    tool_id: str
    action: str
    trigger: ApprovalTrigger = ApprovalTrigger.NEVER
    conditions: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class ApprovalRequest:
    request_id: str
    plan_id: str
    node_id: str
    tool_id: str
    action: str
    params: dict[str, Any]
    status: ApprovalStatus
    created_at: datetime
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    approver_comment: str = ""


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


@dataclass
class NodeExecutionResult:
    node_id: str
    success: bool
    tool_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retries: int = 0
    retryable: bool = True
    recovery_hint: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    attempts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WorkflowRunResult:
    plan_id: str
    success: bool
    node_results: list[NodeExecutionResult] = field(default_factory=list)
    final_context: dict[str, Any] = field(default_factory=dict)
    message: str = ""


def validate_plan_graph(plan: PlanGraph) -> str | None:
    if not plan.plan_id:
        return "plan_id 不能为空"
    if not plan.intent:
        return "intent 不能为空"
    if not plan.nodes:
        return "nodes 不能为空"

    node_ids = {node.node_id for node in plan.nodes}
    if len(node_ids) != len(plan.nodes):
        return "node_id 不能重复"

    for node in plan.nodes:
        if not node.node_id:
            return "存在空 node_id"
        if not node.tool_id:
            return f"节点 {node.node_id} 缺少 tool_id"
        if not node.action:
            return f"节点 {node.node_id} 缺少 action"
        for dep in node.depends_on:
            if dep not in node_ids:
                return f"节点 {node.node_id} 依赖不存在: {dep}"
            if dep == node.node_id:
                return f"节点 {node.node_id} 不能依赖自身"

    # 条件边校验：next / branches[].target 必须存在、不能指向自身、不能成环。
    for node in plan.nodes:
        if node.next is not None:
            if node.next not in node_ids:
                return f"节点 {node.node_id} 的 next 目标不存在: {node.next}"
            if node.next == node.node_id:
                return f"节点 {node.node_id} 的 next 不能指向自身"
        for branch in node.branches:
            if not branch.target:
                return f"节点 {node.node_id} 的 branch 缺少 target"
            if branch.target not in node_ids:
                return f"节点 {node.node_id} 的 branch 目标不存在: {branch.target}"
            if branch.target == node.node_id:
                return f"节点 {node.node_id} 的 branch 不能指向自身"

    cycle = _find_conditional_cycle(plan.nodes, node_ids)
    if cycle is not None:
        return cycle

    return None


def _find_conditional_cycle(nodes: list[WorkflowNode], node_ids: set[str]) -> str | None:
    """沿 next / branches[].target 下游边做 DFS 环检测；有环返回错误信息，否则 None。"""
    adj: dict[str, list[str]] = {nid: [] for nid in node_ids}
    for node in nodes:
        if node.next is not None:
            adj[node.node_id].append(node.next)
        for branch in node.branches:
            adj[node.node_id].append(branch.target)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(node_ids, WHITE)

    def dfs(u: str, stack: list[str]) -> str | None:
        color[u] = GRAY
        for v in adj[u]:
            if color[v] == GRAY:
                start = stack.index(v) if v in stack else 0
                return f"条件边形成环: {' -> '.join(stack[start:] + [v])}"
            if color[v] == WHITE:
                stack.append(v)
                err = dfs(v, stack)
                if err is not None:
                    return err
                stack.pop()
        color[u] = BLACK
        return None

    for nid in node_ids:
        if color[nid] == WHITE:
            err = dfs(nid, [nid])
            if err is not None:
                return err
    return None


def plan_to_dict(plan: PlanGraph) -> dict[str, Any]:
    """把 ``PlanGraph`` 序列化为可 JSON 持久化的 dict（供跨会话续跑存库）。"""
    return {
        "plan_id": plan.plan_id,
        "intent": plan.intent,
        "todo_steps": list(plan.todo_steps),
        "risk_level": plan.risk_level,
        "metadata": dict(plan.metadata),
        "nodes": [
            {
                "node_id": n.node_id,
                "tool_id": n.tool_id,
                "action": n.action,
                "params": dict(n.params),
                "risk": n.risk,
                "idempotent": n.idempotent,
                "description": n.description,
                "depends_on": list(n.depends_on),
                "next": n.next,
                "branches": [
                    {"target": b.target, "condition": dict(b.condition)} for b in n.branches
                ],
            }
            for n in plan.nodes
        ],
    }


def plan_from_dict(data: dict[str, Any] | None) -> PlanGraph | None:
    """从 ``plan_to_dict`` 产物还原 ``PlanGraph``；无数据时返回 ``None``。"""
    if not data:
        return None
    nodes: list[WorkflowNode] = []
    for n in data.get("nodes") or []:
        nodes.append(
            WorkflowNode(
                node_id=str(n.get("node_id") or ""),
                tool_id=str(n.get("tool_id") or ""),
                action=str(n.get("action") or ""),
                params=dict(n.get("params") or {}),
                risk=n.get("risk", "low"),
                idempotent=bool(n.get("idempotent", False)),
                description=str(n.get("description") or ""),
                depends_on=list(n.get("depends_on") or []),
                next=n.get("next"),
                branches=[
                    Branch(target=b["target"], condition=dict(b.get("condition") or {}))
                    for b in n.get("branches") or []
                ],
            )
        )
    return PlanGraph(
        plan_id=str(data.get("plan_id") or ""),
        intent=str(data.get("intent") or ""),
        todo_steps=list(data.get("todo_steps") or []),
        risk_level=data.get("risk_level", "low"),
        metadata=dict(data.get("metadata") or {}),
        nodes=nodes,
    )
