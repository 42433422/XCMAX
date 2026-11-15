"""计划校验失败的最小修复循环。

参考 instructor / LangChain OutputFixingParser 的成熟做法：把「校验错误 + 原输出 +
相关工具契约」回灌给模型，只允许做最小修改，然后重新走同一套确定性校验。

边界：
- 只修复计划结构，不绕过风险门、审批、幂等与租户注入。
- 未出错节点必须逐字段保持一致；禁止删除/新增节点、禁止降低风险。
- 达到轮数上限仍失败时返回 ``None``，由现有拒绝路径生成澄清，不执行任何业务操作。
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from collections.abc import Callable
from typing import Any

from app.application.workflow.llm_plan_generation import (
    _decode_completion,
    _tool_specs,
    build_plan_from_payload,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict

logger = logging.getLogger(__name__)

_ENV_REPAIR_MAX = "XCAGI_PLAN_REPAIR_MAX"
_DEFAULT_REPAIR_MAX = 2
_MAX_REPAIR_MAX = 3

_REPAIR_SYSTEM_PROMPT = (
    "你是业务计划修复器。只修复导致校验失败的节点，输出与输入同结构的 JSON，不要解释。"
    "未出错的节点必须原样保留；不得新增未授权工具或动作；不得降低任何节点的风险；"
    "不得删除节点，也不得把澄清改成直接执行。"
)

_RULES = (
    "只输出 JSON，不要 markdown。",
    "保持 node_id 稳定：只修改报错节点，其他节点的 tool_id/action/params/depends_on/next/branches/risk 必须逐字段不变。",
    "params 中每个 {{节点ID.结果路径}} 引用的节点都必须列入当前节点的 depends_on。",
    "修正后仍要满足 tool_registry 的 input_schema 与 required_params。",
    "无法在不破坏其他节点的前提下修复时，把该节点改为 clarify.ask 并给出具体问题。",
)

_ERROR_CODES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("unauthorized_action", ("使用未授权动作",)),
    ("unknown_tool", ("使用未授权工具", "没有可用动作")),
    ("missing_param", ("缺少 required_params",)),
    ("bad_reference", ("参数预检失败",)),
    ("graph_cycle", ("成环", "循环", "cycle")),
    ("clarify_invalid", ("澄清节点", "clarify")),
    ("reply_shape", ("普通回复计划",)),
    ("schema_invalid", ("未通过工具参数预检",)),
    ("graph_invalid", ("节点不存在", "重复", "计划图")),
)

_NON_REPAIRABLE = frozenset({"reply_shape"})

_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "blocked": 3}


def classify_plan_error(message: str) -> str:
    """把校验错误归到可修复类别；未知错误按 graph_invalid 处理。"""
    text = str(message or "")
    for code, markers in _ERROR_CODES:
        if any(marker in text for marker in markers):
            return code
    return "graph_invalid"


def _repair_max_attempts() -> int:
    try:
        value = int(str(os.environ.get(_ENV_REPAIR_MAX) or "").strip())
    except ValueError:
        return _DEFAULT_REPAIR_MAX
    return max(0, min(_MAX_REPAIR_MAX, value))


def _node_signature(node: WorkflowNode) -> tuple[Any, ...]:
    return (
        node.tool_id,
        node.action,
        json.dumps(node.params or {}, ensure_ascii=False, sort_keys=True, default=str),
        tuple(str(value) for value in node.depends_on or []),
        node.next,
        json.dumps(
            [
                {"target": branch.target, "condition": branch.condition}
                for branch in node.branches or []
            ],
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
        node.risk,
    )


def _mentioned_nodes(error: str) -> set[str]:
    found = set(re.findall(r"节点\s*([A-Za-z0-9_.\-]+)", str(error or "")))
    found.update(re.findall(r"目标节点\s*([A-Za-z0-9_.\-]+)", str(error or "")))
    return {value for value in found if value}


def enforce_repair_scope(original: PlanGraph, candidate: PlanGraph, error: str) -> str | None:
    """拒绝越界修复：节点增删、改动未报错节点、降低风险。"""
    before = {node.node_id: node for node in original.nodes or []}
    after = {node.node_id: node for node in candidate.nodes or []}
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    if removed:
        return f"修复不得删除节点: {', '.join(removed)}"
    if added:
        return f"修复不得新增节点: {', '.join(added)}"
    mentioned = _mentioned_nodes(error)
    for node_id, node in after.items():
        original_node = before[node_id]
        if _RISK_RANK.get(str(node.risk), 0) < _RISK_RANK.get(str(original_node.risk), 0):
            return f"修复不得降低节点 {node_id} 的风险等级"
        if mentioned and node_id not in mentioned:
            if _node_signature(node) != _node_signature(original_node):
                return f"修复改动了未报错的节点 {node_id}"
    return None


def build_repair_messages(
    *,
    plan: PlanGraph,
    error: str,
    tool_registry: dict[str, Any],
    user_message: str,
    error_code: str,
) -> list[dict[str, str]]:
    relevant_ids = {str(node.tool_id) for node in plan.nodes or []}
    relevant_ids.update({"clarify", "conversation"})
    specs = [
        spec
        for spec in _tool_specs(tool_registry)
        if str(spec.get("tool_id") or "") in relevant_ids
    ]
    payload = {
        "task": "修复下列计划中导致校验失败的部分，输出完整计划 JSON。",
        "rules": list(_RULES),
        "error": {"code": error_code, "message": str(error or "")[:400]},
        "user_message": str(user_message or "")[:2000],
        "original_plan": plan_to_dict(plan),
        "tool_registry": specs,
        "output_schema": {
            "mode": "workflow",
            "intent": "string",
            "todo_steps": ["string"],
            "risk_level": "low|medium|high",
            "nodes": [
                {
                    "node_id": "string",
                    "tool_id": "string",
                    "action": "string",
                    "params": {},
                    "risk": "low|medium|high",
                    "idempotent": "bool",
                    "description": "string",
                    "depends_on": ["node_id"],
                    "next": "node_id or null",
                    "branches": [{"target": "node_id", "condition": {}}],
                }
            ],
        },
    }
    return [
        {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def repair_plan(
    *,
    planned: PlanGraph | None,
    plan_id: str,
    message: str,
    context: dict[str, Any],
    tool_registry: dict[str, Any],
    validate: Callable[[PlanGraph], str | None],
    complete: Callable[..., dict[str, Any] | None],
    max_attempts: int | None = None,
) -> tuple[PlanGraph | None, dict[str, Any]]:
    """校验 → 最小修复 → 再校验；返回最终计划与修复轨迹。"""
    trace: dict[str, Any] = {
        "attempts": 0,
        "errors": [],
        "fixed": False,
        "first_pass_valid": False,
    }
    if planned is None:
        return None, trace
    # 校验会就地规范 risk/idempotent 并插入澄清节点；先留一份原始快照做最小修改比对。
    raw_current = copy.deepcopy(planned)
    error = validate(planned)
    if not error:
        trace["first_pass_valid"] = True
        trace["fixed"] = True
        return planned, trace

    attempts = _repair_max_attempts() if max_attempts is None else max(0, int(max_attempts))
    current = planned
    for _ in range(attempts):
        code = classify_plan_error(error)
        trace["errors"].append({"code": code, "message": str(error)[:240]})
        if code in _NON_REPAIRABLE:
            break
        messages = build_repair_messages(
            plan=current,
            error=error,
            tool_registry=tool_registry,
            user_message=message,
            error_code=code,
        )
        try:
            response = complete(
                messages=messages,
                context=context,
                temperature=0.0,
                max_tokens=1200,
            )
        except (ValueError, TypeError, RuntimeError) as exc:
            logger.warning("计划修复请求失败: %s", exc)
            break
        decoded = _decode_completion(response) if isinstance(response, dict) else None
        if decoded is None:
            trace["errors"].append({"code": "unparsable_repair", "message": "修复输出无法解析"})
            break
        parsed, nodes = decoded
        candidate = build_plan_from_payload(
            plan_id=plan_id,
            message=message,
            parsed=parsed,
            nodes=nodes,
            context=context,
        )
        scope_error = enforce_repair_scope(raw_current, candidate, error)
        if scope_error:
            trace["errors"].append({"code": "scope_violation", "message": scope_error})
            break
        raw_current = copy.deepcopy(candidate)
        trace["attempts"] += 1
        next_error = validate(candidate)
        current = candidate
        if not next_error:
            trace["fixed"] = True
            return current, trace
        error = next_error
    return None, trace


__all__ = [
    "build_repair_messages",
    "classify_plan_error",
    "enforce_repair_scope",
    "repair_plan",
]
