"""Plan construction and knowledge/memory exchange, independent of execution state."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.workflow.workflow_types import PlanGraph
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class RunPlanning:
    def __init__(self, repository: AgentRunRepository) -> None:
        self.repository = repository

    def plan(self, run: AgentRun, *, runtime_context: dict[str, Any]) -> PlanGraph:
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry

        run.status = "planning"
        run.add_event("planner.started", "开始生成 Agent 计划")
        self.repository.save(run)
        context = dict(runtime_context or {})
        from app.application.agent_orchestrator.attachment_inputs import (
            AttachmentInputError,
            resolve_attachment_context,
        )

        try:
            context, artifacts = resolve_attachment_context(context)
        except AttachmentInputError as exc:
            from app.application.workflow.workflow_types import WorkflowNode

            return PlanGraph(
                plan_id=f"attachment-rejected-{run.run_id}",
                intent="attachment_reupload_required",
                todo_steps=[str(exc)],
                nodes=[
                    WorkflowNode(
                        node_id="attachment_reupload",
                        tool_id="clarify",
                        action="ask",
                        params={"question": str(exc)},
                        risk="low",
                        idempotent=True,
                        description=str(exc),
                    )
                ],
                metadata={"attachment_rejected": True},
            )
        context.setdefault("message", run.message)
        skill_lines = _active_skill_rules(run.message)
        context["active_skills"] = skill_lines
        self.recall_knowledge_for_run(run, context=context)
        from app.infrastructure.llm.model_admission import model_rate_limit_scope

        planner = LLMWorkflowPlanner()
        with model_rate_limit_scope(context):
            plan = planner.plan(run.user_id, run.message, get_workflow_tool_registry(), context)
        if artifacts:
            plan.metadata["artifacts"] = artifacts
        run.add_event(
            "planner.completed",
            "Agent 计划生成完成",
            {"plan_id": plan.plan_id, "intent": plan.intent, "nodes": len(plan.nodes)},
        )
        return plan

    def recall_knowledge_for_run(self, run: AgentRun, *, context: dict[str, Any]) -> None:
        """统一 Agent Runtime 接缝：pre-plan 知识库 RAG 召回（best-effort，开关控制）。

        召回结果以 RetrievalCall 上 run 账本，并注入 planner context（``knowledge_rag``）。
        dataset_id 取自 runtime_context / context（当前无全局知识索引，按需指定）。
        """
        try:
            from app.application.agent_runtime.pipeline import (
                agent_runtime_hooks_enabled,
                recall_knowledge_context,
            )

            if not agent_runtime_hooks_enabled():
                return
            dataset_id = str(
                (run.metadata.get("runtime_context") or {}).get("dataset_id")
                or context.get("dataset_id")
                or ""
            ).strip()
            call = recall_knowledge_context(query=run.message, dataset_id=dataset_id)
            if str(call.get("status") or "") == "skipped":
                return
            from app.application.agent_orchestrator.run_models import retrieval_call_from_dict

            retrieval_call = retrieval_call_from_dict(call)
            if not retrieval_call.query:
                retrieval_call.query = run.message
            run.retrieval_calls.append(retrieval_call)
            context["knowledge_rag"] = {
                "dataset_id": dataset_id,
                "chunks": call.get("chunks") or [],
                "citations": call.get("citations") or [],
            }
            run.add_event(
                "runtime.knowledge_recalled",
                "知识库 RAG 召回完成",
                {
                    "call_id": retrieval_call.call_id,
                    "status": retrieval_call.status,
                    "chunk_count": len(retrieval_call.chunks),
                },
            )
        except RECOVERABLE_ERRORS:
            logger.debug("knowledge recall hook skipped", exc_info=True)

    @staticmethod
    def attach_memory_recall(run: AgentRun, recall_meta: Any) -> None:
        """统一 Agent Runtime 接缝：planner pre-plan 记忆召回落 run.memory_references。"""
        if not isinstance(recall_meta, dict) or not recall_meta:
            return
        from app.application.agent_orchestrator.run_models import memory_reference_from_dict

        for key in ("user_memory_rag", "memory_v2"):
            payload = recall_meta.get(key)
            if not isinstance(payload, dict):
                continue
            run.memory_references.append(
                memory_reference_from_dict(
                    {
                        "query": run.message,
                        "memory_type": "user_memory" if key == "user_memory_rag" else "memory_v2",
                        "source": key,
                        "hits": payload.get("hits") or [],
                        "summary": str(payload.get("summary") or "")[:2000],
                        "status": "completed",
                        "metadata": {"origin": "planner.pre_plan_recall"},
                    }
                )
            )
        run.add_event(
            "runtime.memory_recalled",
            "pre-plan 用户记忆召回已上账",
            {"reference_count": len(run.memory_references)},
        )

    def remember_run_outcome_for(self, run: AgentRun) -> None:
        """Write accepted results back through the existing memory namespace."""
        try:
            from app.application.agent_orchestrator.business_action_ledger import canonical_hash
            from app.application.agent_orchestrator.result_verification import (
                summarize_verification,
            )
            from app.application.agent_orchestrator.task_context import task_context_of
            from app.application.agent_runtime.pipeline import (
                agent_runtime_hooks_enabled,
                remember_run_outcome,
            )
            from app.domain.task_lifecycle.results import execution_result_error

            if not agent_runtime_hooks_enabled():
                return
            report = summarize_verification(run)
            completed = run.status == "completed"
            reason = (
                "execution_not_terminal"
                if run.status not in {"completed", "failed", "cancelled", "rejected"}
                else "result_not_verified"
                if completed
                and (report.get("accepted") is not True or execution_result_error(run.final_output))
                else ""
            )
            if reason:
                run.add_event(
                    "runtime.memory_writeback",
                    "结果未完成或未通过核验，未写入成功记忆",
                    {"remembered": False, "status": str(run.status), "reason": reason},
                )
                return
            committed = self.repository.get(run.run_id)
            if (
                committed is None
                or committed.status != run.status
                or canonical_hash(committed.final_output) != canonical_hash(run.final_output)
                or (
                    completed
                    and canonical_hash(summarize_verification(committed)) != canonical_hash(report)
                )
            ):
                run.add_event(
                    "runtime.memory_writeback",
                    "终态回执尚未持久化，未写入结果记忆",
                    {
                        "remembered": False,
                        "status": str(run.status),
                        "reason": "terminal_receipt_not_committed",
                    },
                )
                return
            ctx = dict(run.metadata.get("runtime_context") or {})
            task = task_context_of(run)
            summary = (
                self.run_outcome_summary(run) if completed else str(run.error or run.status)[:600]
            )
            evidence = canonical_hash(
                [
                    {
                        key: row.get(key)
                        for key in (
                            "call_id",
                            "status",
                            "contract_sha256",
                            "output_sha256",
                            "evidence_sha256",
                        )
                    }
                    for row in report["steps"]
                ]
            )
            feedback_id = canonical_hash([run.run_id, run.status, summary, evidence])
            previous = run.metadata.get("memory_feedback") or {}
            if previous.get("feedback_id") == feedback_id and previous.get("remembered") is True:
                return
            metadata = {
                "run_id": run.run_id,
                "task_id": str(task["task_id"]),
                "root_run_id": str(task["root_run_id"]),
                "turn_id": str(task.get("turn_id") or ctx.get("turn_id") or ""),
                "tenant_id": str(ctx.get("tenant_id") or ""),
                "intent": run.intent,
                "status": str(run.status),
                "verification_status": report["status"],
                "evidence_sha256": evidence,
                "feedback_id": feedback_id,
            }
            remembered = remember_run_outcome(
                user_id=run.user_id,
                task=run.message,
                summary=summary,
                success=completed,
                session_id=str(ctx.get("session_id") or ctx.get("conversation_id") or ""),
                metadata=metadata,
            )
            run.metadata["memory_feedback"] = {**metadata, "remembered": bool(remembered)}
            run.add_event(
                "runtime.memory_writeback",
                "run 终态记忆回写完成" if remembered else "run 终态记忆回写跳过",
                {**metadata, "remembered": bool(remembered)},
            )
        except RECOVERABLE_ERRORS:
            logger.debug("memory writeback hook skipped", exc_info=True)

    @staticmethod
    def run_outcome_summary(run: AgentRun) -> str:
        """终态摘要：优先取工具输出的可读字段，退化为错误/状态描述。"""
        outputs = (
            run.final_output.get("node_outputs") if isinstance(run.final_output, dict) else None
        )
        if isinstance(outputs, dict):
            for value in outputs.values():
                if isinstance(value, dict):
                    for key in ("summary", "message", "output", "result", "preview"):
                        text = str(value.get(key) or "").strip()
                        if text:
                            return text[:600]
                elif isinstance(value, str) and value.strip():
                    return value.strip()[:600]
        return str(run.error or run.status or "")[:600]


def _active_skill_rules(message: str) -> list[str]:
    """按消息触发条件加载仓库技能；未配置或读取失败时保持原规划行为。"""
    if os.environ.get("XCAGI_AGENT_SKILLS_ENABLED", "1") == "0":
        return []
    try:
        from app.application.skills.skill_registry import skill_rules

        return skill_rules(message)
    except RECOVERABLE_ERRORS:
        logger.debug("skill registry skipped", exc_info=True)
        return []
