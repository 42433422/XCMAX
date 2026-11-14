"""PlanGraph 落盘与失败反思钩子——避免继续膨胀 oversized planner.py。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def observe_plan_graph(
    plan: Any,
    *,
    phase: str,
    trace_id: str,
    extra: dict[str, Any] | None = None,
    force: bool = False,
    reflect_on_failure: bool = False,
    plan_id: str | None = None,
    validate_error: str | None = None,
) -> None:
    """Best-effort PlanGraph 观测；失败不阻断主规划路径。"""
    try:
        from app.domain.neuro.cognition.plan_graph_log import append_plan_graph

        payload_extra = dict(extra or {})
        if validate_error:
            payload_extra["validate_error"] = validate_error
        append_plan_graph(
            plan,
            phase=phase,
            force=force,
            trace_id=trace_id,
            extra=payload_extra,
        )
        if reflect_on_failure and validate_error:
            from app.domain.neuro.evolution.self_reflection import get_self_reflection_engine

            get_self_reflection_engine().critique_and_propose(
                target="prompt_template",
                critique=f"PlanGraph 校验失败: {validate_error}",
                proposal={"action": "revise_planner_prompt", "error": validate_error},
                evidence={"plan_id": plan_id},
            )
    except RECOVERABLE_ERRORS:
        logger.debug("plan_graph observe skipped", exc_info=True)


def _validate_clarify_nodes(plan: Any) -> str | None:
    """clarify 反问节点专属校验：其 branches[].target 必须指向图中已存在的普通操作节点。

    ``validate_plan_graph`` 已统一校验 next / 全部 branches 目标存在与成环，这里仅在
    ``finalize_planned_graph`` 内对 ``tool_id == "clarify"`` 的节点做二次聚焦校验，
    防止反问节点引用了被移除/不存在的目标仍被放行。
    """
    node_ids = {str(getattr(n, "node_id", "")) for n in (plan.nodes or [])}
    for node in plan.nodes or []:
        if str(getattr(node, "tool_id", "") or "") != "clarify":
            continue
        for branch in node.branches or []:
            target = str(getattr(branch, "target", "") or "")
            if target not in node_ids:
                return f"clarify 节点 {node.node_id} 的 branch 目标不存在: {target}"
    return None


def finalize_planned_graph(
    planned: Any,
    *,
    plan_id: str,
    context: dict[str, Any] | None,
    validate: Callable[[Any], str | None],
    warn: Callable[[str], None],
    plan_type: Any,
    node_type: Any,
) -> Any:
    """Validate generated plans and pause safely on rejection; never execute a fallback plan."""
    trace_id = str((context or {}).get("trace_id") or plan_id)
    rejection = str((context or {}).get("planning_failure_reason") or "模型未返回可用计划")
    if planned is not None:
        err = validate(planned)
        if err is None:
            # Conversation text is user content, not a durable business plan.
            # Keep model replies in the chat transcript only; the plan graph is
            # consumed immediately by the LangGraph runtime and is not logged.
            if (getattr(planned, "metadata", {}) or {}).get("response_mode") == "reply":
                return planned
            # 条件边 / 反问节点聚焦校验（next、branches 目标存在与成环由 validate 覆盖）。
            err = _validate_clarify_nodes(planned)
        if err is None:
            observe_plan_graph(
                planned,
                phase="planned",
                trace_id=trace_id,
                extra={"source": "platform_model"},
            )
            return planned
        rejection = str(err or "计划校验失败")
        warn(f"LangGraph 计划校验失败，本轮停止执行: {rejection}")
        observe_plan_graph(
            planned,
            phase="failed",
            force=True,
            trace_id=trace_id,
            extra={"source": "langgraph_planner"},
            plan_id=plan_id,
            validate_error=err,
        )
    question = (
        "我没能生成通过系统校验的计划，本轮没有执行任何业务操作。请补充业务对象和目标后重试。"
    )
    rejected = plan_type(
        plan_id=plan_id,
        intent="plan_rejected",
        todo_steps=["等待补充信息后重新规划"],
        nodes=[
            node_type(
                node_id="plan_rejected_clarification",
                tool_id="clarify",
                action="ask",
                params={
                    "question": question,
                    "answer_key": "confirmed",
                    "target_node_id": "",
                    "planning_rejected": True,
                },
                risk="low",
                idempotent=True,
                description="计划校验失败，暂停并请求补充业务目标",
            )
        ],
        risk_level="low",
        metadata={
            "planning_rejected": True,
            "planning_unavailable": planned is None,
            "rejection_reason": rejection[:240],
        },
    )
    observe_plan_graph(
        rejected,
        phase="rejected",
        force=True,
        trace_id=trace_id,
        extra={"source": "langgraph_planner_rejection"},
        validate_error=rejection,
    )
    return rejected
