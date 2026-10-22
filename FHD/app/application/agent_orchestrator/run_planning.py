"""Plan construction and knowledge/memory exchange, independent of execution state."""

from __future__ import annotations

import logging
from typing import Any, cast

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_repository import AgentRunRepository
from app.application.workflow.types import PlanGraph
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class RunPlanning:
    def __init__(self, repository: AgentRunRepository) -> None:
        self.repository = repository

    def plan(self, run: AgentRun, *, runtime_context: dict[str, Any]) -> PlanGraph:
        from app.application.agent_orchestrator.multimodal_planner import (
            build_multimodal_autonomous_plan,
        )
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry

        run.status = "planning"
        run.add_event("planner.started", "开始生成 Agent 计划")
        self.repository.save(run)
        context = dict(runtime_context or {})
        context.setdefault("message", run.message)
        self.recall_knowledge_for_run(run, context=context)
        multimodal_plan = build_multimodal_autonomous_plan(
            user_id=run.user_id, message=run.message, runtime_context=context
        )
        if multimodal_plan is not None:
            run.add_event(
                "planner.completed",
                "多模态 Artifact 自主计划生成完成",
                {
                    "plan_id": multimodal_plan.plan_id,
                    "intent": multimodal_plan.intent,
                    "nodes": len(multimodal_plan.nodes),
                    "source": "multimodal_autonomous_planner",
                    "artifact_count": multimodal_plan.metadata.get("artifact_count", 0),
                },
            )
            return multimodal_plan
        planner = LLMWorkflowPlanner()
        plan = planner.plan(run.user_id, run.message, get_workflow_tool_registry(), context)
        run.add_event(
            "planner.completed",
            "Agent 计划生成完成",
            {"plan_id": plan.plan_id, "intent": plan.intent, "nodes": len(plan.nodes)},
        )
        return cast(PlanGraph, plan)

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
        """统一 Agent Runtime 接缝：run 终态记忆回写（best-effort，开关控制）。"""
        try:
            from app.application.agent_runtime.pipeline import (
                agent_runtime_hooks_enabled,
                remember_run_outcome,
            )

            if not agent_runtime_hooks_enabled():
                return
            ctx = dict(run.metadata.get("runtime_context") or {})
            summary = self.run_outcome_summary(run)
            remembered = remember_run_outcome(
                user_id=run.user_id,
                task=run.message,
                summary=summary,
                success=str(run.status) == "completed",
                session_id=str(ctx.get("session_id") or ctx.get("conversation_id") or ""),
                metadata={"run_id": run.run_id, "intent": run.intent, "status": str(run.status)},
            )
            run.add_event(
                "runtime.memory_writeback",
                "run 终态记忆回写完成" if remembered else "run 终态记忆回写跳过",
                {"remembered": bool(remembered), "status": str(run.status)},
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
