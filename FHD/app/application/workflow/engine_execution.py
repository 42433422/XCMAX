"""Node execution, retry policy and parameter preparation for workflow tools."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from app.application.product_query_context import inject_product_query_fallback
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .types import NodeExecutionResult, WorkflowNode

logger = logging.getLogger(__name__)


class ToolDispatcher(Protocol):
    def __call__(self, *, tool_id: str, action: str, params: dict[str, Any]) -> dict[str, Any]: ...


class NodeExecutor:
    """One attempt loop for DAG and agentic tools, with explicit parameter policy."""

    def __init__(self, dispatch: ToolDispatcher) -> None:
        self._dispatch = dispatch

    def execute(
        self,
        *,
        node_id: str,
        tool_id: str,
        action: str,
        params: dict[str, Any],
        prepare_params: Callable[[], dict[str, Any]],
        max_retries: int,
        retryable: bool,
    ) -> NodeExecutionResult:
        retries = 0
        last_error = ""
        started_perf = time.perf_counter()
        result = NodeExecutionResult(
            node_id=node_id,
            success=False,
            tool_id=tool_id,
            action=action,
            retryable=retryable,
            started_at=datetime.now(UTC).isoformat(),
        )
        effective_max_retries = max_retries if retryable else 0
        while retries <= effective_max_retries:
            attempt_started = time.perf_counter()
            try:
                output = self._dispatch(tool_id=tool_id, action=action, params=prepare_params())
                if isinstance(output, dict):
                    result.output = output
                if output.get("success", False):
                    result.success = True
                    result.attempts.append(attempt_summary(retries + 1, True, "", attempt_started))
                    break
                last_error = str(output.get("message") or output.get("error") or "unknown error")
            except RECOVERABLE_ERRORS as err:
                last_error = str(err)
                logger.warning(
                    "执行节点失败 node=%s tool=%s.%s err=%s",
                    node_id,
                    tool_id,
                    action,
                    err,
                    exc_info=True,
                )
            result.attempts.append(attempt_summary(retries + 1, False, last_error, attempt_started))
            retries += 1
        result.params = dict(params or {})
        result.retries = retries if result.success else max(0, retries - 1)
        result.finished_at = datetime.now(UTC).isoformat()
        result.duration_ms = elapsed_ms(started_perf)
        if not result.success:
            result.error = last_error
            result.recovery_hint = recovery_hint(
                tool_id=tool_id,
                action=action,
                error=last_error,
                output=result.output,
                retryable=retryable,
            )
        return result


def node_allows_auto_retry(node: WorkflowNode) -> bool:
    return bool(node.idempotent) or node.risk == "low"


def agentic_tool_allows_auto_retry(
    tool_registry: dict[str, Any], tool_id: str, action: str
) -> bool:
    spec = tool_registry.get(tool_id) if isinstance(tool_registry, dict) else None
    if not isinstance(spec, dict):
        return True
    actions = spec.get("actions") if isinstance(spec.get("actions"), dict) else {}
    meta = actions.get(action) if isinstance(actions, dict) else None
    if not isinstance(meta, dict):
        return True
    return bool(meta.get("idempotent")) or str(meta.get("risk") or "low") == "low"


def recovery_hint(
    *,
    tool_id: str,
    action: str,
    error: str,
    output: dict[str, Any] | None,
    retryable: bool,
) -> str:
    out = output if isinstance(output, dict) else {}
    message = str(error or out.get("message") or out.get("error") or "").strip()
    if out.get("pending_approval") or out.get("approval_required"):
        return "写操作已进入审批流；在审批工作台通过后重试或继续执行。"
    if out.get("requires_token"):
        token_name = str(out.get("token_name") or "DB_WRITE_TOKEN").strip()
        return f"缺少写库令牌 {token_name}；配置令牌或在受信任工作区内重试。"
    if out.get("available_employee_ids"):
        return "请从返回的 available_employee_ids 中选择员工 ID 后重新执行。"
    if "缺少 employee_id" in message:
        return "先执行 employee.list 查看可用员工，再带 employee_id 调用 employee.execute。"
    if "缺少" in message or "required" in message.lower():
        return "补齐提示中的必填参数后重新执行。"
    if not retryable:
        return "该节点可能产生副作用，系统未自动重试；请核对员工空间或数据库状态后手动重试。"
    if tool_id == "business_db" and action == "write":
        return "数据库写入失败；确认 entity/operation/payload 后重试，避免重复写入。"
    if message:
        return "可重试节点已耗尽自动重试；请检查参数、外部服务连接或稍后重试。"
    return ""


def elapsed_ms(started_perf: float) -> int:
    return max(0, int((time.perf_counter() - started_perf) * 1000))


def attempt_summary(attempt: int, success: bool, error: str, started_perf: float) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "success": bool(success),
        "error": str(error or "")[:240],
        "duration_ms": elapsed_ms(started_perf),
    }


def run_clarify_node(node: WorkflowNode, runtime_context: dict[str, Any]) -> NodeExecutionResult:
    """反问澄清节点执行：不调用业务工具。

    - 若 runtime_context 中已注入该节点的确认答案（``_clarify_answers[node.node_id]``），
      则产出 ``answer_confirmed``，供条件边（branches）路由到原操作节点继续执行。
    - 否则产出 ``requires_confirmation=true`` + ``question``，暂停工作流（interrupt），
      且不路由到写节点（写节点被 block）。
    """
    started_at = datetime.now(UTC).isoformat()
    started_perf = time.perf_counter()
    params = node.params or {}
    question = str(params.get("question") or "").strip()
    answer_key = str(params.get("answer_key") or "confirmed").strip() or "confirmed"
    target_node_id = str(params.get("target_node_id") or "").strip()
    answers = runtime_context.get("_clarify_answers") or {}
    if not isinstance(answers, dict):
        answers = {}
    my_answer = answers.get(node.node_id)
    if isinstance(my_answer, dict) and my_answer.get("confirmed") is not None:
        output = {
            "success": True,
            "answer_confirmed": bool(my_answer.get("confirmed")),
            "answer_key": answer_key,
        }
    else:
        output = {
            "success": True,
            "requires_confirmation": True,
            "answer_key": answer_key,
            "question": question,
            "target_node_id": target_node_id,
        }
    finished_at = datetime.now(UTC).isoformat()
    return NodeExecutionResult(
        node_id=node.node_id,
        success=True,
        tool_id="clarify",
        action="ask",
        params=dict(params),
        output=output,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=elapsed_ms(started_perf),
        retryable=True,
    )


def has_non_empty_param(params: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for k in keys:
        v = params.get(k)
        if v is not None and str(v).strip():
            return True
    return False


def merge_runtime_fallback_params(
    node: WorkflowNode,
    merged_params: dict[str, Any],
    runtime_context: dict[str, Any],
) -> None:
    user_msg = str(runtime_context.get("message") or "").strip()
    if not user_msg:
        return
    if node.tool_id == "products" and node.action == "query":
        if not has_non_empty_param(
            merged_params, ("keyword", "model_number", "product_name", "name", "unit_name")
        ):
            keyword = inject_product_query_fallback(merged_params, user_msg)
            logger.info(
                "工作流 products.query %s",
                f"注入有效检索词: {keyword[:80]}" if keyword else "按全量列表请求执行",
            )
    elif node.tool_id == "customers" and node.action == "query":
        if not has_non_empty_param(
            merged_params, ("keyword", "unit_name", "customer_name", "name")
        ):
            merged_params.pop("keyword", None)
            logger.info("工作流 customers.query 无检索词，按全量列表执行（不注入用户原话）")
