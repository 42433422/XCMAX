from __future__ import annotations

import logging
from typing import Any

from .types import NodeExecutionResult, PlanGraph, StateSchema, WorkflowRunResult


def run_agentic_loop(
    engine: Any,
    event_logger: logging.Logger,
    plan: PlanGraph,
    runtime_context: dict[str, Any] | None,
    max_retries: int,
    tool_registry: dict[str, Any],
    user_id: str | None,
    state_schema: StateSchema | None = None,
) -> WorkflowRunResult:
    """Run the model-directed tool loop with fail-closed completion semantics."""
    runtime_context = dict(runtime_context or {})
    schema = state_schema or engine._default_state_schema
    all_node_results: list[NodeExecutionResult] = []
    agent_history: list[dict[str, Any]] = []
    max_steps = 10
    step = 0
    terminal_reason = ""
    completed_by_model = False
    decision_errors = 0

    user_message = str(runtime_context.get("message") or "").strip()

    while step < max_steps:
        step += 1

        decision = engine._llm_decide_next_step(
            user_message=user_message,
            tool_registry=tool_registry,
            runtime_context=runtime_context,
            agent_history=agent_history,
            user_id=user_id,
        )

        if decision is None:
            terminal_reason = "模型未返回可执行决策"
            break

        decision_action = str(decision.get("action") or "").strip()
        tool_id = decision.get("tool_id", "")
        tool_action = str(
            decision.get("action_name") or decision.get("tool_action") or decision_action
        ).strip()
        params = decision.get("params") or {}
        reasoning = str(decision.get("reasoning", "")).strip()

        event_logger.info(
            "AgenticLoop step=%d action=%s.%s reasoning=%s",
            step,
            tool_id,
            tool_action,
            reasoning[:100],
        )

        if decision_action == "done":
            agent_history.append({"step": step, "role": "done"})
            completed_by_model = True
            break

        agent_history.append(
            {
                "step": step,
                "role": "assistant",
                "tool_id": tool_id,
                "action": tool_action,
                "params": params,
                "reasoning": reasoning,
            }
        )

        if not tool_id or not tool_action or tool_action == "execute":
            decision_errors += 1
            agent_history.append(
                {
                    "step": step,
                    "role": "system",
                    "content": "工具决策缺少 tool_id 或真实 action_name，已跳过。",
                }
            )
            continue

        node_result = engine._run_single_tool(
            tool_id=tool_id,
            action=tool_action,
            params=params,
            runtime_context=runtime_context,
            max_retries=max_retries,
            retryable=engine._agentic_tool_allows_auto_retry(tool_registry, tool_id, tool_action),
        )
        all_node_results.append(node_result)
        engine._append_node_trace(runtime_context, node_result)
        engine._merge_state_schema(runtime_context, node_result, schema)

        runtime_context.setdefault("node_outputs", {})
        runtime_context["node_outputs"][f"agent_step_{step}"] = node_result.output
        engine._emit_state_update(node_result)

        if not node_result.success:
            agent_history.append(
                {
                    "step": step,
                    "role": "system",
                    "content": f"工具执行失败: {node_result.error}",
                }
            )
        else:
            output_preview = engine._summarize_output(node_result.output)
            agent_history.append(
                {
                    "step": step,
                    "role": "system",
                    "content": f"结果: {output_preview}",
                }
            )

    if step >= max_steps:
        event_logger.warning("AgenticLoop 达到最大步数限制 %d", max_steps)
        terminal_reason = f"达到最大步数限制 {max_steps}，但模型未声明完成"

    failed_results = [result for result in all_node_results if not result.success]
    success = completed_by_model and not failed_results and decision_errors == 0
    if failed_results:
        terminal_reason = f"{len(failed_results)} 个工具步骤失败"
    elif decision_errors:
        terminal_reason = f"{decision_errors} 个模型工具决策无效"
    runtime_context["workflow_status"] = {
        "state": "completed" if success else "failed",
        "completed_by_model": completed_by_model,
        "steps": step,
        "failed_tool_steps": len(failed_results),
        "invalid_decisions": decision_errors,
        "message": "AgenticLoop 执行完成" if success else terminal_reason,
    }

    return WorkflowRunResult(
        plan_id=plan.plan_id,
        success=success,
        node_results=all_node_results,
        final_context=runtime_context,
        message=(
            f"AgenticLoop 完成（{step} 步）"
            if success
            else f"AgenticLoop 未完成（{step} 步）：{terminal_reason}"
        ),
    )
