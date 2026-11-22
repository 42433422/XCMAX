"""Bound a trusted chat answer to an existing frozen graph's reference question."""

from __future__ import annotations

import copy
from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.task_dispatcher import notify_agent_task_dispatcher
from app.application.agent_orchestrator.task_execution_repository import (
    get_task_execution_repository,
)
from app.application.agent_orchestrator.task_execution_sql_repository import (
    SQLAlchemyTaskExecutionRepository,
)
from app.application.workflow.clarification_lifecycle import resolve_confirmed_target
from app.domain.task_lifecycle.agent_runtime_results import model_unsettled
from app.infrastructure.codex.binding import CodexBindingError, CodexBindingStore


def answer_reference_input(
    store: CodexBindingStore, *, run_id: str, text: str
) -> dict[str, Any] | None:
    """Called only after gateway owner/context checks and durable request dedup.

    Selection is deterministic and limited to independently verified candidates.
    It queues the same child with no approval grant and starts no model turn.
    """
    binding = store.get(run_id)
    if not binding.run.metadata.get("runtime_frozen_plan"):
        return None
    rows = store.receipt_snapshot(run_id)
    questions = {
        (question["run_id"], question["step_id"]): question
        for row in rows
        if (receipt := row.get("receipt") or {}).get("needs_user_input") is True
        and isinstance(question := receipt.get("clarification"), dict)
        and question.get("run_id")
        and question.get("step_id")
    }
    if len(questions) != 1:
        return None
    # Refresh after receipt_snapshot has settled cost/reservation metadata.
    binding = store.get(run_id)
    store._validate_authority(binding.run, binding.metadata)
    store._validate_control(binding.run)
    if binding.metadata.get("coordinator_active") or model_unsettled(binding.metadata):
        raise CodexBindingError("binding_conflict", "原执行者或模型计量尚未结束，不能补答")
    question = next(iter(questions.values()))
    if not any(
        call.get("child_run_id") == question["run_id"] and call.get("reservation_state") == "held"
        for call in binding.metadata.get("calls", {}).values()
    ):
        raise CodexBindingError("binding_conflict", "原子任务预算已变化，请先核对原任务")
    child = store.repository.get(question["run_id"])
    if child is None:
        return None
    proof = (child.metadata.get("reference_clarifications") or {}).get(question["step_id"])
    if not isinstance(proof, dict) or proof.get("answer") is not None:
        return None
    selection = resolve_confirmed_target(text, question.get("candidates") or [])
    if selection is not None:
        queue = get_task_execution_repository()
        if not isinstance(queue, SQLAlchemyTaskExecutionRepository):
            raise CodexBindingError("binding_conflict", "原任务的持久化调度当前不可用")
        staged = AgentOrchestrator(repository=store.repository).stage_clarification_answer(
            child.run_id,
            step_id=question["step_id"],
            parameters=selection,
            requested_by=binding.run.user_id,
            queue=queue,
            parent_snapshot=binding.run,
        )
        if staged is None:
            raise CodexBindingError("request_conflict", "原任务状态已变化，请刷新后重新选择")
        notify_agent_task_dispatcher()
    from app.application.agent_runtime.receipt_projection import refresh_codex_receipts

    refreshed = refresh_codex_receipts(store.get(run_id).run, repository=store.repository)
    result = copy.deepcopy(refreshed.final_output["codex_result"])
    if selection is None:
        result["output"] = str(question.get("question") or "请补充原任务信息") + (
            "\n请回复候选编号、完整名称或明确序号，例如「第二个」。"
        )
    return dict(result)
