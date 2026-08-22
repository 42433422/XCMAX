# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib
from typing import Literal


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


class __AIChatApplicationServicePart02MixinPart01Mixin:
    def _build_workflow_thinking_steps(self, plan, decision_reason: str) -> str:
        tool_labels = {
            "business_db": "业务数据",
            "customers": "客户资料",
            "products": "产品资料",
            "materials": "原材料资料",
            "shipment_records": "发货记录",
            "print": "打印服务",
            "dataset_rag": "企业知识库",
        }
        action_labels = {
            "query": "查询",
            "read": "读取",
            "write": "写入",
            "create": "新增",
            "update": "更新",
            "delete": "删除",
            "generate": "生成",
            "execute": "执行",
        }
        intent_labels = {
            "product_query": "查询产品资料",
            "customer_query": "查询客户资料",
            "deterministic_chat_reply": "处理业务咨询",
        }
        node_lines: list[str] = []
        for node in plan.nodes or []:
            raw_description = getattr(node, "description", "")
            description = raw_description.strip() if isinstance(raw_description, str) else ""
            if not description:
                tool_name = tool_labels.get(str(node.tool_id), "业务能力")
                action_name = action_labels.get(str(node.action), "处理")
                description = f"{action_name}{tool_name}"
            node_lines.append(f"- {description}")
        nodes_text = "\n".join(node_lines) if node_lines else "- 直接生成答复，无需执行业务步骤"
        metadata = getattr(plan, "metadata", {}) or {}
        user_memory_rag_summary = str(metadata.get("user_memory_rag_summary") or "").strip()
        memory_v2_summary = str(metadata.get("memory_v2_summary") or "").strip()
        tool_probe_outputs = metadata.get("tool_probe_outputs") or []
        if not isinstance(tool_probe_outputs, list):
            tool_probe_outputs = []
        successful_probe_count = 0
        for item in tool_probe_outputs[:3]:
            if not isinstance(item, dict):
                continue
            ok = bool(item.get("success"))
            successful_probe_count += int(ok)
        memory_block = (
            f"3.5) 用户记忆 RAG 概览:\n{user_memory_rag_summary}\n"
            if user_memory_rag_summary
            else ""
        )
        memory_v2_block = (
            f"3.6) Memory v2 已确认记忆:\n{memory_v2_summary}\n" if memory_v2_summary else ""
        )
        probe_block = (
            f"3.7) 能力预检: 已确认 {successful_probe_count} 项业务能力可用\n"
            if tool_probe_outputs
            else ""
        )
        raw_intent = str(getattr(plan, "intent", "") or "").strip()
        intent_text = intent_labels.get(raw_intent, "处理当前业务请求")
        risks = {str(getattr(node, "risk", "low") or "low") for node in (plan.nodes or [])}
        risk_text = (
            "涉及业务变更，执行前需要确认或审批"
            if risks & {"medium", "high", "critical"}
            else "只读或低风险操作，可直接执行"
        )
        return (
            f"工作编排:\n1) 业务目标: {intent_text}\n"
            f"2) 执行计划: 共 {len(node_lines)} 个业务步骤\n"
            f"3) 安全边界: {risk_text}\n"
            f"{memory_block}{memory_v2_block}{probe_block}"
            f"4) 执行方式: 按业务依赖顺序推进，并持续回写状态\n"
            f"5) 业务步骤:\n{nodes_text}"
        )

    def _workflow_products_float_query(self, plan, run_result, user_message: str) -> str:
        """从产品查询节点参数/结果或用户原话中提取副窗搜索词。"""
        for node in plan.nodes or []:
            if node.tool_id == "products" and node.action == "query":
                p = node.params or {}
                q = (
                    str(p.get("keyword") or "").strip()
                    or str(p.get("model_number") or "").strip()
                    or str(p.get("product_name") or p.get("name") or "").strip()
                )
                if q := self._normalize_product_query(q):
                    return q
        for r in run_result.node_results:
            if not r.success or r.tool_id != "products" or r.action != "query":
                continue
            out = r.output or {}
            rows = out.get("data") or []
            if isinstance(rows, list) and rows:
                row = rows[0] if isinstance(rows[0], dict) else {}
                if isinstance(row, dict):
                    m = str(row.get("model_number") or "").strip()
                    n = str(row.get("name") or row.get("product_name") or "").strip()
                    if m:
                        return m
                if n:
                    return n
        return self._normalize_product_query(user_message)

    def _start_agentic_workflow_agent_run(
        self, *, user_id: str, message: str, plan, runtime_context: dict[str, _facade().Any]
    ):
        from app.application.agent_orchestrator.run_models import AgentRun
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository

        repository = get_agent_run_repository()
        run = AgentRun(
            user_id=str(user_id or ""),
            message=str(message or ""),
            status="running",
            plan_id=str(getattr(plan, "plan_id", "") or ""),
            intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
            metadata={
                "runtime_context": dict(runtime_context or {}),
                "trace_mode": "agentic_loop_bridge",
                "plan": {
                    "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                    "risk_level": str(getattr(plan, "risk_level", "") or ""),
                    "metadata": dict(getattr(plan, "metadata", {}) or {}),
                },
            },
        )
        run.add_event("run.created", "Agentic workflow run 已创建")
        run.add_event(
            "planner.completed",
            "Agentic workflow 计划已接管",
            {
                "plan_id": run.plan_id,
                "intent": run.intent,
                "source": "workflow_engine.agentic_loop",
            },
        )
        run.add_event("agentic_loop.started", "Agentic workflow loop 开始执行", {"observed": True})
        return repository.save(run)

    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        run_result,
        runtime_context: dict[str, _facade().Any],
        agent_run=None,
    ):
        from app.application.agent_orchestrator.run_models import (
            AgentRun,
            AgentStep,
            ToolCall,
            artifact_from_dict,
        )
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        repository = get_agent_run_repository()
        runtime_ctx = dict(runtime_context or {})
        run = agent_run
        if run is None:
            run = AgentRun(
                user_id=str(user_id or ""),
                message=str(message or ""),
                status="running",
                plan_id=str(getattr(plan, "plan_id", "") or ""),
                intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
                metadata={
                    "runtime_context": dict(runtime_ctx),
                    "trace_mode": "agentic_loop_bridge",
                    "plan": {
                        "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                        "risk_level": str(getattr(plan, "risk_level", "") or ""),
                        "metadata": dict(getattr(plan, "metadata", {}) or {}),
                    },
                },
            )
            run.add_event("run.created", "Agentic workflow run 已创建")
            run.add_event(
                "planner.completed",
                "Agentic workflow 计划已接管",
                {
                    "plan_id": run.plan_id,
                    "intent": run.intent,
                    "source": "workflow_engine.agentic_loop",
                },
            )
            run.add_event(
                "agentic_loop.started", "Agentic workflow loop 开始执行", {"observed": True}
            )
        run.metadata["runtime_context"] = dict(runtime_ctx)
        run.metadata["trace_mode"] = "agentic_loop_bridge"
        run.add_event(
            "agentic_loop.completed",
            str(getattr(run_result, "message", "") or "AgenticLoop 已完成"),
            {"observed": True},
        )
        node_outputs: dict[str, _facade().Any] = {}
        for result in getattr(run_result, "node_results", []) or []:
            spec = get_tool_action_spec(result.tool_id, result.action)
            status: Literal["completed", "failed"] = (
                "completed" if bool(getattr(result, "success", False)) else "failed"
            )
            step = AgentStep(
                node_id=str(result.node_id or f"agent_{result.tool_id}_{result.action}"),
                tool_id=str(result.tool_id or ""),
                action=str(getattr(spec, "action", "") or result.action or ""),
                params=dict(getattr(result, "params", {}) or {}),
                risk=str(getattr(spec, "risk", "") or "medium"),
                idempotent=bool(getattr(spec, "idempotent", False)),
                description="agentic loop observed tool execution",
                status=status,
                output=dict(getattr(result, "output", {}) or {}),
                error=str(getattr(result, "error", "") or ""),
                started_at=str(getattr(result, "started_at", "") or ""),
                finished_at=str(getattr(result, "finished_at", "") or ""),
                duration_ms=int(getattr(result, "duration_ms", 0) or 0),
            )
            if status == "failed" and (not step.error):
                step.error = self._workflow_output_message(step.output) or "tool failed"
            call = ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params or {}),
                status="completed" if status == "completed" else "failed",
                output=dict(step.output or {}),
                error=step.error,
                cost_units=int(getattr(spec, "cost_units", 0) or 0),
                permission=str(getattr(spec, "permission", "") or ""),
                started_at=step.started_at or "",
                finished_at=step.finished_at or "",
                duration_ms=step.duration_ms,
                metadata={
                    "observed": True,
                    "trace_mode": "agentic_loop_bridge",
                    "retryable": bool(getattr(result, "retryable", True)),
                    "retries": int(getattr(result, "retries", 0) or 0),
                    "recovery_hint": str(getattr(result, "recovery_hint", "") or ""),
                },
            )
            run.steps.append(step)
            run.tool_calls.append(call)
            node_outputs[step.node_id] = step.output
            run.add_event(
                "tool.started",
                f"观察到 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "cost_units": call.cost_units,
                    "permission": call.permission,
                    "observed": True,
                },
            )
            run.add_event(
                "tool.completed" if status == "completed" else "tool.failed",
                f"记录 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "duration_ms": step.duration_ms,
                    "cost_units": call.cost_units,
                    "observed": True,
                    "error": step.error,
                },
            )
            for artifact_payload in self._iter_agentic_artifact_payloads(step.output):
                artifact = artifact_from_dict(artifact_payload)
                if not artifact.artifact_type:
                    continue
                artifact.source = artifact.source or f"{step.tool_id}.{step.action}"
                artifact.metadata = {
                    **dict(artifact.metadata or {}),
                    "step_id": step.step_id,
                    "call_id": call.call_id,
                    "trace_mode": "agentic_loop_bridge",
                }
                run.artifacts.append(artifact)
                run.add_event(
                    "artifact.attached",
                    f"Artifact 已附加: {artifact.artifact_type}",
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "name": artifact.name,
                        "source": artifact.source,
                    },
                )
        cost_units_total = sum(int(call.cost_units or 0) for call in run.tool_calls)
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = cost_units_total
        run.metadata["artifact_count"] = len(run.artifacts)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": cost_units_total,
            "workflow_result": {
                "success": bool(getattr(run_result, "success", False)),
                "message": str(getattr(run_result, "message", "") or ""),
                "workflow_status": dict(
                    (getattr(run_result, "final_context", {}) or {}).get("workflow_status") or {}
                ),
            },
        }
        run.status = "completed" if bool(getattr(run_result, "success", False)) else "failed"
        if run.status == "failed":
            run.error = str(getattr(run_result, "message", "") or "Agentic workflow failed")
            run.add_event("run.failed", run.error, run.final_output)
        else:
            run.add_event("run.completed", "Agentic workflow run 执行完成", run.final_output)
        return repository.save(run)
