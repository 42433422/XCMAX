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
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import httpx

from app.application.workflow.llm_plan_generation import (
    _decode_completion,
    _has_native_tool_calls,
    _model_context_value,
    _model_payload,
    _tool_specs,
    build_plan_from_payload,
    model_plan_schema_error,
)
from app.application.workflow.tool_calling import plan_output_schema, request_json_completion
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode, plan_to_dict
from app.infrastructure.modstore_transport import MarketModelError
from app.security.log_redaction import redact_log_text

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
    "业务节点的 tool_id 与 action 必须分别逐字取自同一条工具契约，不要把工具名、公式名或描述拼进 action。内置 clarify.ask 只用于提问。",
    "仅当确实缺少用户可补充的业务事实时才允许澄清；未知动作、权限或协议错误不得降级为 clarify.ask。",
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


def _diagnostic_text(value: str, max_chars: int = 240) -> str:
    """Redact before truncating so exported repair traces cannot split credentials."""
    return redact_log_text(value)[:max_chars]


def _repair_max_attempts() -> int:
    try:
        value = int(str(os.environ.get(_ENV_REPAIR_MAX) or "").strip())
    except ValueError:
        return _DEFAULT_REPAIR_MAX
    return max(0, min(_MAX_REPAIR_MAX, value))


def _node_signature(node: WorkflowNode) -> str:
    return json.dumps(asdict(node), ensure_ascii=False, sort_keys=True, default=str)


def _mentioned_nodes(error: str) -> set[str]:
    # Only the validator's leading subject identifies the failing node. A nested
    # error value can mention another node without granting permission to edit it.
    match = re.match(r"(?:目标)?节点\s+([^\s:：,，]+)", str(error or ""))
    return {match.group(1)} if match else set()


def enforce_repair_scope(original: PlanGraph, candidate: PlanGraph, error: str) -> str | None:
    """拒绝越界修复：节点增删、改动未报错节点、降低风险。"""
    if _RISK_RANK.get(candidate.risk_level, 0) < _RISK_RANK.get(original.risk_level, 0):
        return "修复不得降低计划的风险等级"
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
        if (original_node.tool_id, original_node.action) == ("clarify", "ask") and (
            node.tool_id,
            node.action,
        ) != ("clarify", "ask"):
            return f"修复不得把节点 {node_id} 的澄清改为直接执行"
        if node_id not in mentioned:
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
    response_error: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    relevant_ids = {str(node.tool_id) for node in plan.nodes or []}
    relevant_ids.update({"clarify", "conversation"})
    # A fabricated tool is absent from the catalog. Show authorized alternatives
    # instead of repeating an empty catalog that cannot repair its identifier.
    has_unknown_tool = bool(relevant_ids - tool_registry.keys() - {"clarify", "conversation"})
    relevant_registry = {
        key: spec
        for key, spec in tool_registry.items()
        if has_unknown_tool or error_code == "unknown_tool" or key in relevant_ids
    }
    payload = {
        "task": "修复下列计划中导致校验失败的部分，输出完整计划 JSON。",
        "rules": list(_RULES),
        "error": {"code": error_code, "message": _model_context_value(str(error or "")[:400])},
        "user_message": _model_context_value(str(user_message or "")[:2000]),
        "original_plan": _model_context_value(plan_to_dict(plan)),
        "tool_registry": _tool_specs(relevant_registry),
        "output_schema": plan_output_schema(relevant_registry),
    }
    if response_error:
        payload["previous_response_error"] = response_error
    return [
        {"role": "system", "content": _REPAIR_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def _repair_decode_diagnostic(response: Any) -> dict[str, Any]:
    """Diagnose a rejected repair without persisting raw model text or secrets."""
    if not isinstance(response, dict):
        return {"reason": "response_not_object", "response_length": 0}
    parsed, raw = _model_payload(response)
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    truncated = isinstance(first, dict) and first.get("finish_reason") == "length"
    if _has_native_tool_calls(response):
        reason = "unexpected_tool_call"
    elif truncated:
        reason = "output_truncated"
    elif not raw:
        reason = "empty_content"
    elif not isinstance(parsed, dict):
        reason = "invalid_json"
    else:
        candidate = dict(parsed)
        candidate.setdefault("mode", "workflow")
        reason = "schema_invalid" if model_plan_schema_error(candidate) else "decoder_rejected"
    diagnostic: dict[str, Any] = {"reason": reason, "response_length": len(raw)}
    if raw:
        diagnostic["response_sha256"] = hashlib.sha256(
            raw.encode("utf-8", errors="backslashreplace")
        ).hexdigest()
    return diagnostic


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
    error = validate(planned)
    # Compare against the actual deterministic normalization, not untrusted flags.
    raw_current = copy.deepcopy(planned)
    if not error:
        trace["first_pass_valid"] = True
        trace["fixed"] = True
        return planned, trace

    trace["initial_error"] = _diagnostic_text(error)
    mentioned = _mentioned_nodes(error)
    trace["invalid_node_actions"] = [
        {
            "node_id": _diagnostic_text(node.node_id, 80),
            "tool_id": _diagnostic_text(node.tool_id, 120),
            "action": _diagnostic_text(node.action, 120),
        }
        for node in (planned.nodes or [])
        if node.node_id in mentioned
    ][:5]
    attempts = (
        _repair_max_attempts()
        if max_attempts is None
        else max(0, min(_MAX_REPAIR_MAX, int(max_attempts)))
    )
    current = planned
    response_error = None
    for _ in range(attempts):
        code = classify_plan_error(error)
        trace["errors"].append({"code": code, "message": _diagnostic_text(error)})
        if code in _NON_REPAIRABLE:
            break
        messages = build_repair_messages(
            plan=current,
            error=error,
            tool_registry=tool_registry,
            user_message=message,
            error_code=code,
            response_error=response_error,
        )
        # Count issued requests, including malformed responses and failures.
        trace["attempts"] += 1
        try:
            response = request_json_completion(
                complete,
                messages=messages,
                context=context,
                temperature=0.0,
            )
        except (ValueError, TypeError, RuntimeError, OSError, httpx.TransportError) as exc:
            from app.application.agent_orchestrator.context_window_manager import (
                ContextWindowExceeded,
            )
            from app.application.workflow.retry_policy import PlanningBudgetExceeded
            from app.domain.model_admission_errors import (
                ModelCircuitOpenError,
                ModelConcurrencyLimitError,
                ModelRateLimitError,
            )
            from app.domain.shared_services.conversation_service import ConversationRevisionError
            from app.utils.resilience.rate_limiter import RateLimitBackendError

            if isinstance(exc, ConversationRevisionError):
                raise
            raw_error = str(exc)
            reason = "计划修复请求失败，请稍后重试。"
            trace["failure_kind"] = "plan_repair_failed"
            if isinstance(exc, PlanningBudgetExceeded):
                trace["failure_kind"] = "planning_budget_exhausted"
                reason = "规划已达到等待时限或自动重试上限，请重试原请求；本次未执行业务操作"
            elif isinstance(exc, ContextWindowExceeded):
                trace["failure_kind"] = "planner_error"
                context["_planning_failure_code"] = "context_window_exceeded"
                reason = "模型上下文超过当前模型能力上限，请缩短输入或调整模型。"
            elif isinstance(exc, MarketModelError):
                trace.update(failure_kind="model_unavailable", status_code=exc.status_code)
                reason = str(MarketModelError({"status": exc.status_code}))
            elif isinstance(
                exc, (ModelCircuitOpenError, ModelConcurrencyLimitError, ModelRateLimitError)
            ):
                trace["failure_kind"] = "model_unavailable"
                context["_planning_failure_code"] = exc.code
                reason = str(exc)
            elif isinstance(exc, (OSError, httpx.TransportError, RateLimitBackendError)):
                trace["failure_kind"] = "model_unavailable"
                reason = "模型请求连接失败或超时，请稍后重试。"
            logger.warning("计划修复请求失败: %s", type(exc).__name__)
            trace["errors"].append(
                {
                    "code": "repair_request_failed",
                    "message": reason,
                    "error_type": type(exc).__name__[:80],
                    "error_length": len(raw_error),
                    "error_sha256": hashlib.sha256(
                        raw_error.encode("utf-8", errors="backslashreplace")
                    ).hexdigest(),
                }
            )
            break
        decoded = _decode_completion(response) if isinstance(response, dict) else None
        if decoded is None:
            response_error = _repair_decode_diagnostic(response)
            trace["errors"].append(
                {
                    "code": "unparsable_repair",
                    "message": "修复输出无法解析",
                    **response_error,
                }
            )
            if response_error["reason"] == "unexpected_tool_call":
                break
            # Keep the last deterministic plan and failing-node scope unchanged.
            # A malformed model answer consumes an attempt, not the whole repair.
            continue
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
            trace["errors"].append(
                {"code": "scope_violation", "message": _diagnostic_text(scope_error)}
            )
            break
        next_error = validate(candidate)
        response_error = None
        raw_current = copy.deepcopy(candidate)
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
