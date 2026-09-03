# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.orchestrator")


class __AgentOrchestratorPart01MixinPart01Mixin:
    def __init__(
        self,
        *,
        repository: _facade().AgentRunRepository | None = None,
        tool_executor: _facade().AgentToolExecutor | None = None,
    ) -> None:
        self._repo = repository or _facade().get_agent_run_repository()
        self._repository_status = {
            "mode": "sqlalchemy"
            if isinstance(self._repo, _facade().SQLAlchemyAgentRunRepository)
            else "memory",
            "durable": isinstance(self._repo, _facade().SQLAlchemyAgentRunRepository),
        }
        self._tool_executor = tool_executor or _facade().AgentToolExecutor()

    @staticmethod
    def _ingest_artifact_to_dataset(run: _facade().AgentRun, artifact: _facade().Any) -> None:
        _facade().ingest_artifact_to_dataset(run, artifact)

    def start_run(
        self,
        *,
        user_id: str,
        message: str,
        runtime_context: dict[str, _facade().Any] | None = None,
        auto_execute: bool = True,
    ) -> _facade().AgentRun:
        run = _facade().AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        run.metadata["persistence"] = dict(self._repository_status)
        run.metadata["runtime_context"] = dict(runtime_context or {})
        _facade().apply_task_context(run, runtime_context)
        run.add_event("run.created", "Agent run 已创建")
        self._repo.save(run)
        try:
            plan = self._plan(run, runtime_context=dict(runtime_context or {}))
            self._apply_plan(run, plan)
            _facade().apply_ai_budget_metadata(
                run, dict(plan.metadata or {}), dict(runtime_context or {})
            )
            self._repo.save(run)
            if auto_execute:
                self._execute_with_durable_lease(run, runtime_context=dict(runtime_context or {}))
            return _facade().cast("AgentRun", self._repo.save(run))
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("agent run start failed")
            run.status = "failed"
            run.error = _facade()._INTERNAL_RUN_ERROR
            run.add_event(
                "run.failed", "Agent run 失败", {"error_code": _facade()._INTERNAL_RUN_ERROR}
            )
            return _facade().cast("AgentRun", self._repo.save(run))

    def start_run_from_plan(
        self,
        *,
        user_id: str,
        message: str,
        plan: _facade().PlanGraph,
        runtime_context: dict[str, _facade().Any] | None = None,
        auto_execute: bool = True,
    ) -> _facade().AgentRun:
        run = _facade().AgentRun(user_id=str(user_id or ""), message=str(message or ""))
        run.metadata["persistence"] = dict(self._repository_status)
        run.metadata["runtime_context"] = dict(runtime_context or {})
        _facade().apply_task_context(run, runtime_context)
        run.add_event("run.created", "Agent run 已创建")
        run.add_event(
            "planner.completed",
            "Agent 计划已接管",
            {
                "plan_id": plan.plan_id,
                "intent": plan.intent,
                "nodes": len(plan.nodes),
                "source": "provided_plan",
            },
        )
        try:
            self._apply_plan(run, plan)
            _facade().apply_ai_budget_metadata(
                run, dict(plan.metadata or {}), dict(runtime_context or {})
            )
            self._repo.save(run)
            if auto_execute:
                self._execute_with_durable_lease(run, runtime_context=dict(runtime_context or {}))
            return _facade().cast("AgentRun", self._repo.save(run))
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception("agent run from plan failed")
            run.status = "failed"
            run.error = _facade()._INTERNAL_RUN_ERROR
            run.add_event(
                "run.failed", "Agent run 失败", {"error_code": _facade()._INTERNAL_RUN_ERROR}
            )
            return _facade().cast("AgentRun", self._repo.save(run))

    def continue_run(
        self,
        run_id: str,
        *,
        approved_by: str = "",
        approved_step_id: str = "",
        runtime_context: dict[str, _facade().Any] | None = None,
    ) -> _facade().AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        waiting_step = self._find_waiting_step(run, approved_step_id=approved_step_id)
        if waiting_step is None and str(approved_step_id or "").strip():
            wanted = str(approved_step_id).strip()
            waiting_step = next(
                (
                    step
                    for step in run.steps
                    if step.status == "pending" and wanted in {step.step_id, step.node_id}
                ),
                None,
            )
        if waiting_step is None:
            run.add_event(
                "run.continue_ignored",
                "没有等待确认的步骤",
                {"approved_by": approved_by, "approved_step_id": approved_step_id},
            )
            return _facade().cast("AgentRun | None", self._repo.save(run))
        context = dict(run.metadata.get("runtime_context") or {})
        context.update(dict(runtime_context or {}))
        run.metadata["runtime_context"] = context
        _facade().apply_ai_budget_metadata(run, context)
        waiting_step.status = "pending"
        run.status = "running"
        run.error = ""
        run.add_event(
            "step.approved",
            f"步骤 {waiting_step.node_id} 已确认继续",
            {
                "step_id": waiting_step.step_id,
                "node_id": waiting_step.node_id,
                "tool_id": waiting_step.tool_id,
                "action": waiting_step.action,
                "approved_by": approved_by,
            },
        )
        self._execute_with_durable_lease(
            run, runtime_context=context, approved_step_id=waiting_step.step_id
        )
        return _facade().cast("AgentRun | None", self._repo.save(run))

    def list_runs(self, *, user_id: str | None = None, limit: int = 50) -> list[_facade().AgentRun]:
        return _facade().cast(
            "list[AgentRun]", self._repo.list_recent(user_id=user_id, limit=limit)
        )

    def list_events(
        self, run_id: str, *, after_event_id: str | None = None
    ) -> list[_facade().RunEvent]:
        return _facade().cast(
            "list[RunEvent]", self._repo.list_events(run_id, after_event_id=after_event_id)
        )

    def _plan(
        self, run: _facade().AgentRun, *, runtime_context: dict[str, _facade().Any]
    ) -> _facade().PlanGraph:
        from app.application.agent_orchestrator.multimodal_planner import (
            build_multimodal_autonomous_plan,
        )
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry

        run.status = "planning"
        run.add_event("planner.started", "开始生成 Agent 计划")
        self._repo.save(run)
        context = dict(runtime_context or {})
        context.setdefault("message", run.message)
        self._recall_knowledge_for_run(run, context=context)
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
        return plan

    def _recall_knowledge_for_run(
        self, run: _facade().AgentRun, *, context: dict[str, _facade().Any]
    ) -> None:
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
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("knowledge recall hook skipped", exc_info=True)

    @staticmethod
    def _attach_memory_recall(run: _facade().AgentRun, recall_meta: _facade().Any) -> None:
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

    def _remember_run_outcome_for(self, run: _facade().AgentRun) -> None:
        """统一 Agent Runtime 接缝：run 终态记忆回写（best-effort，开关控制）。"""
        try:
            from app.application.agent_runtime.pipeline import (
                agent_runtime_hooks_enabled,
                remember_run_outcome,
            )

            if not agent_runtime_hooks_enabled():
                return
            ctx = dict(run.metadata.get("runtime_context") or {})
            summary = self._run_outcome_summary(run)
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
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.debug("memory writeback hook skipped", exc_info=True)

    @staticmethod
    def _run_outcome_summary(run: _facade().AgentRun) -> str:
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

    def _apply_plan(self, run: _facade().AgentRun, plan: _facade().PlanGraph) -> None:
        run.plan_id = plan.plan_id
        run.intent = plan.intent
        plan_metadata = dict(plan.metadata or {})
        run.metadata["plan"] = {
            "todo_steps": list(plan.todo_steps or []),
            "risk_level": plan.risk_level,
            "metadata": plan_metadata,
        }
        self._attach_memory_recall(run, plan_metadata.get("memory_recall"))
        run.steps = [self._step_from_node(node) for node in plan.nodes]
        self._apply_repair_policy(run, dict(plan.metadata or {}))
        self._attach_artifacts_from_payload(
            run, getattr(plan, "metadata", {}) or {}, source="plan.metadata"
        )
        self._refresh_artifact_metadata(run)
        run.status = "running" if run.steps else "blocked"
        if not run.steps:
            run.error = "planner returned no executable steps"
            run.add_event("planner.blocked", "计划没有可执行节点")

    @staticmethod
    def _step_from_node(node: _facade().WorkflowNode) -> _facade().AgentStep:
        spec = _facade().get_tool_action_spec(node.tool_id, node.action)
        return _facade().AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=spec.action if spec is not None else node.action,
            params=dict(node.params or {}),
            risk=spec.risk if spec is not None else str(node.risk or "low"),
            idempotent=bool(spec.idempotent) if spec is not None else bool(node.idempotent),
            description=str(node.description or ""),
            depends_on=list(node.depends_on or []),
        )

    @staticmethod
    def _find_waiting_step(
        run: _facade().AgentRun, *, approved_step_id: str = ""
    ) -> _facade().AgentStep | None:
        wanted = str(approved_step_id or "").strip()
        for step in run.steps:
            if step.status != "waiting_user":
                continue
            if wanted and wanted not in {step.step_id, step.node_id}:
                continue
            return step
        return None

    def _execute_ready_steps(
        self,
        run: _facade().AgentRun,
        *,
        runtime_context: dict[str, _facade().Any],
        approved_step_id: str = "",
    ) -> None:
        approved = str(approved_step_id or "").strip()
        completed_node_ids: set[str] = {
            step.node_id for step in run.steps if step.status == "completed"
        }
        node_outputs: dict[str, _facade().Any] = {
            step.node_id: dict(step.output or {})
            for step in run.steps
            if step.status == "completed"
        }
        for step in run.steps:
            if self._apply_requested_control(run):
                return
            if step.status == "completed":
                continue
            if any(dep not in completed_node_ids for dep in step.depends_on):
                run.status = "blocked"
                step.status = "skipped"
                step.error = "dependencies are not completed"
                run.add_event(
                    "step.blocked",
                    f"步骤 {step.node_id} 依赖未满足",
                    {"step_id": step.step_id, "depends_on": step.depends_on},
                )
                return
            step_is_approved = bool(approved and approved in {step.step_id, step.node_id})
            if not self._can_auto_execute(step) and (not step_is_approved):
                step.status = "waiting_user"
                run.status = "waiting_user"
                run.add_event(
                    "step.waiting_user",
                    f"步骤 {step.node_id} 需要用户确认",
                    {
                        "step_id": step.step_id,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "risk": step.risk,
                        "idempotent": step.idempotent,
                    },
                )
                return
            while True:
                budget_payload = _facade().budget_exceeded_payload(
                    run,
                    additional_cost_units=self._step_cost_units(step),
                    scope=f"{step.tool_id}.{step.action}",
                )
                if budget_payload is not None:
                    self._mark_budget_exceeded(run, step, budget_payload, node_outputs=node_outputs)
                    return
                self._execute_step(
                    run, step, runtime_context=runtime_context, node_outputs=node_outputs
                )
                if self._apply_requested_control(run):
                    return
                if step.status == "completed":
                    break
                if self._prepare_repair_or_retry(run, step, runtime_context=runtime_context):
                    continue
                run.status = "failed"
                run.error = step.error or f"step {step.node_id} failed"
                self._refresh_run_cost_metadata(run)
                self._refresh_repair_metadata(run)
                run.final_output = {
                    "node_outputs": node_outputs,
                    "tool_calls": [call.to_dict() for call in run.tool_calls],
                    "artifacts": [artifact.to_dict() for artifact in run.artifacts],
                    "cost_units_total": run.metadata["cost_units_total"],
                    "ai_cost_units_total": run.metadata["ai_cost_units_total"],
                    "failed_step_id": step.step_id,
                    "error": run.error,
                    "repair_count": run.metadata.get("repair_count", 0),
                }
                self._append_llm_summary_to_final_output(run)
                self._remember_run_outcome_for(run)
                return
            completed_node_ids.add(step.node_id)
        run.status = "completed"
        self._refresh_run_cost_metadata(run)
        self._refresh_repair_metadata(run)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": run.metadata["cost_units_total"],
            "ai_cost_units_total": run.metadata["ai_cost_units_total"],
            "repair_count": run.metadata.get("repair_count", 0),
        }
        self._append_llm_summary_to_final_output(run)
        self._remember_run_outcome_for(run)
        run.add_event("run.completed", "Agent run 执行完成", run.final_output)

    @staticmethod
    def _can_auto_execute(step: _facade().AgentStep) -> bool:
        return str(step.risk or "").lower() == "low" and bool(step.idempotent)
