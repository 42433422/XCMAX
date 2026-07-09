"""AI chat workflow response formatting / agent-run bridge mixin."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class AIChatWorkflowFormatMixin:
    def _build_workflow_thinking_steps(self, plan, decision_reason: str) -> str:
        node_lines = []
        for node in plan.nodes or []:
            deps = ",".join(node.depends_on) if node.depends_on else "无"
            node_lines.append(
                f"- 节点 {node.node_id}: {node.tool_id}.{node.action} "
                f"(risk={node.risk}, depends_on={deps})"
            )
        nodes_text = "\n".join(node_lines) if node_lines else "- 无可执行节点"

        metadata = getattr(plan, "metadata", {}) or {}
        user_memory_rag_summary = str(metadata.get("user_memory_rag_summary") or "").strip()
        memory_v2_summary = str(metadata.get("memory_v2_summary") or "").strip()
        tool_probe_outputs = metadata.get("tool_probe_outputs") or []
        if not isinstance(tool_probe_outputs, list):
            tool_probe_outputs = []

        probe_lines = []
        for item in tool_probe_outputs[:3]:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("tool_id") or "").strip()
            action = str(item.get("action") or "").strip()
            ok = bool(item.get("success"))
            msg = str(item.get("message") or "").strip()
            preview = str(item.get("data_preview") or "").strip()
            if preview:
                preview = preview[:220] + ("…" if len(preview) > 220 else "")
            probe_lines.append(f"- {tid}.{action}: success={ok}; {msg} {preview}".strip())

        memory_block = (
            f"3.5) 用户记忆 RAG 概览:\n{user_memory_rag_summary}\n"
            if user_memory_rag_summary
            else ""
        )
        memory_v2_block = (
            f"3.6) Memory v2 已确认记忆:\n{memory_v2_summary}\n" if memory_v2_summary else ""
        )
        probe_block = (
            "3.7) 工具探测概览:\n"
            + ("\n".join(probe_lines) if probe_lines else "- 无成功探测结果")
            + "\n"
        )
        return (
            "思考步骤:\n"
            f"1) 意图理解: {plan.intent}\n"
            "2) 计划生成: 基于工具注册表构建可执行节点图\n"
            f"3) 风险判断: {decision_reason}\n"
            f"{memory_block}{memory_v2_block}{probe_block}"
            "4) 执行编排: 按依赖顺序执行节点并传递上下文\n"
            f"5) 节点图:\n{nodes_text}"
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
                if q:
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
        return str(user_message or "").strip()

    def _start_agentic_workflow_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        runtime_context: dict[str, Any],
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
        run.add_event(
            "agentic_loop.started",
            "Agentic workflow loop 开始执行",
            {"observed": True},
        )
        return repository.save(run)

    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        run_result,
        runtime_context: dict[str, Any],
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
                "agentic_loop.started",
                "Agentic workflow loop 开始执行",
                {"observed": True},
            )
        run.metadata["runtime_context"] = dict(runtime_ctx)
        run.metadata["trace_mode"] = "agentic_loop_bridge"
        run.add_event(
            "agentic_loop.completed",
            str(getattr(run_result, "message", "") or "AgenticLoop 已完成"),
            {"observed": True},
        )

        node_outputs: dict[str, Any] = {}
        for result in getattr(run_result, "node_results", []) or []:
            spec = get_tool_action_spec(result.tool_id, result.action)
            status = "completed" if bool(getattr(result, "success", False)) else "failed"
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
            if status == "failed" and not step.error:
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

    @staticmethod
    def _iter_agentic_artifact_payloads(output: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(output, dict):
            return []
        artifacts = output.get("artifacts")
        if artifacts is None:
            artifacts = output.get("artifact")
        if isinstance(artifacts, dict):
            return [artifacts]
        if isinstance(artifacts, list):
            return [item for item in artifacts if isinstance(item, dict)]
        return []

    @staticmethod
    def _agent_plan_can_auto_execute(plan) -> bool:
        nodes = getattr(plan, "nodes", None)
        if not isinstance(nodes, (list, tuple)) or not nodes:
            return False
        try:
            from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        except RECOVERABLE_ERRORS:
            return False
        for node in nodes:
            spec = get_tool_action_spec(getattr(node, "tool_id", ""), getattr(node, "action", ""))
            risk = str(getattr(spec, "risk", "") or getattr(node, "risk", "") or "").lower()
            idempotent = bool(getattr(spec, "idempotent", getattr(node, "idempotent", False)))
            if risk != "low" or not idempotent:
                return False
        return True

    def _format_agent_run_response(
        self,
        plan,
        agent_run,
        thinking_steps: str = "",
        user_message: str = "",
    ) -> dict[str, Any]:
        lines = [
            f"工作流: {plan.intent}",
            f"计划ID: {plan.plan_id}",
            f"RunID: {agent_run.run_id}",
        ]
        if thinking_steps:
            lines.append(thinking_steps)
        if plan.todo_steps:
            lines.append("TODO:")
            lines.extend([f"- {x}" for x in plan.todo_steps])
        lines.append("执行结果:")

        node_params_by_id = {
            str(getattr(node, "node_id", "")): (getattr(node, "params", None) or {})
            for node in (getattr(plan, "nodes", None) or [])
        }
        for step in getattr(agent_run, "steps", []) or []:
            if step.status == "completed":
                item = type(
                    "AgentNodeResult",
                    (),
                    {
                        "node_id": step.node_id,
                        "success": True,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "output": step.output,
                        "error": "",
                    },
                )()
                lines.extend(
                    self._format_workflow_tool_success_line(
                        item,
                        node_params_by_id.get(str(step.node_id), {}),
                    )
                )
            else:
                lines.append(f"- {step.node_id}: {step.status}（{step.error or '未完成'}）")

        success = agent_run.status == "completed"
        cost_units_total = int((agent_run.metadata or {}).get("cost_units_total") or 0)
        tool_call_count = int((agent_run.metadata or {}).get("tool_call_count") or 0)
        artifact_payloads = [
            artifact.to_dict() for artifact in getattr(agent_run, "artifacts", []) or []
        ]
        if tool_call_count:
            lines.append(f"工具调用: {tool_call_count} 次，成本单位: {cost_units_total}")
        if artifact_payloads:
            lines.append(f"Artifacts: {len(artifact_payloads)} 个")
        response_text = "\n".join(lines)
        payload: dict[str, Any] = {
            "success": success,
            "message": "处理完成" if success else "处理失败",
            "response": response_text,
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "data": {
                "text": response_text,
                "action": "workflow_done" if success else "workflow_failed",
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "plan_id": plan.plan_id,
                    "intent": plan.intent,
                    "thinking_steps": thinking_steps,
                    "todo": plan.todo_steps,
                    "agent_status": agent_run.status,
                    "tool_call_count": tool_call_count,
                    "cost_units_total": cost_units_total,
                    "artifact_count": len(artifact_payloads),
                    "artifacts": artifact_payloads,
                    "tool_calls": [
                        {
                            "call_id": call.call_id,
                            "step_id": call.step_id,
                            "node_id": call.node_id,
                            "tool_id": call.tool_id,
                            "action": call.action,
                            "status": call.status,
                            "cost_units": call.cost_units,
                            "duration_ms": call.duration_ms,
                            "permission": call.permission,
                        }
                        for call in getattr(agent_run, "tool_calls", []) or []
                    ],
                    "node_results": [
                        {
                            "node_id": step.node_id,
                            "success": step.status == "completed",
                            "tool_id": step.tool_id,
                            "action": step.action,
                            "message": step.error or self._workflow_output_message(step.output),
                            "output_preview": self._workflow_output_preview(step.output),
                            "duration_ms": step.duration_ms,
                        }
                        for step in getattr(agent_run, "steps", []) or []
                    ],
                },
            },
        }
        if success and any(
            step.status == "completed" and step.tool_id == "products" and step.action == "query"
            for step in getattr(agent_run, "steps", []) or []
        ):
            payload["autoAction"] = {
                "type": "show_products_float",
                "feature": "products",
                "query": str(user_message or "").strip(),
            }
        return payload

    @staticmethod
    def _workflow_output_preview(output: Any, max_chars: int = 700) -> str:
        if output is None:
            return ""
        value = output
        if isinstance(output, dict):
            value = {
                k: v
                for k, v in output.items()
                if k
                in {
                    "success",
                    "message",
                    "error",
                    "employee_id",
                    "exists",
                    "created",
                    "unit_name",
                    "matched_count",
                    "redirect",
                }
            }
            data = output.get("data")
            if isinstance(data, list):
                value["row_count"] = len(data)
                value["rows"] = data[:5]
            elif isinstance(data, dict):
                value["data"] = {
                    k: v
                    for k, v in data.items()
                    if k
                    in {
                        "summary",
                        "result",
                        "error",
                        "success",
                        "registered_tool_count",
                        "available_employee_ids",
                    }
                } or str(data)[:260]
            elif data is not None:
                value["data"] = data
            raw = output.get("raw")
            if raw is not None and "data" not in value:
                value["raw"] = str(raw)[:260]
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
        text = text.strip()
        if len(text) > max_chars:
            return text[:max_chars] + "..."
        return text

    @staticmethod
    def _workflow_output_message(output: Any) -> str:
        if not isinstance(output, dict):
            return ""
        return str(output.get("message") or output.get("error") or "").strip()

    def _format_workflow_tool_success_line(
        self,
        item,
        node_params: dict[str, Any],
    ) -> list[str]:
        output = getattr(item, "output", None)
        out = output if isinstance(output, dict) else {}
        message = self._workflow_output_message(out)
        preview = self._workflow_output_preview(out)

        if item.tool_id == "employee":
            if item.action in ("list", "query"):
                data = out.get("data") if isinstance(out.get("data"), dict) else {}
                count = data.get("registered_tool_count", 0)
                line = f"- {item.node_id}: 成功（发现 {count} 个可调用员工）"
            else:
                employee_id = str(
                    out.get("employee_id") or node_params.get("employee_id") or "-"
                ).strip()
                suffix = f": {message}" if message else ""
                line = f"- {item.node_id}: 成功（员工 {employee_id}{suffix}）"
            return [line, f"    · 结果预览: {preview}"] if preview else [line]

        if item.tool_id == "business_db":
            entity = str(node_params.get("entity") or out.get("entity") or "-").strip()
            operation = str(node_params.get("operation") or item.action or "").strip()
            if item.action in ("read", "query", "list"):
                rows = out.get("data")
                count = len(rows) if isinstance(rows, list) else 0
                line = f"- {item.node_id}: 成功（{entity} 查询 {count} 条）"
            else:
                suffix = f": {message}" if message else ""
                line = f"- {item.node_id}: 成功（{entity}.{operation}{suffix}）"
            return [line, f"    · 结果预览: {preview}"] if preview else [line]

        if message:
            return [f"- {item.node_id}: 成功（{message}）"]
        return [f"- {item.node_id}: 成功"]

    def _format_workflow_run_response(
        self,
        plan,
        run_result,
        thinking_steps: str = "",
        user_message: str = "",
    ) -> dict[str, Any]:
        lines = [f"工作流: {plan.intent}", f"计划ID: {plan.plan_id}"]
        if thinking_steps:
            lines.append(thinking_steps)
        if plan.todo_steps:
            lines.append("TODO:")
            lines.extend([f"- {x}" for x in plan.todo_steps])
        lines.append("执行结果:")
        plan_nodes = getattr(plan, "nodes", None)
        if not isinstance(plan_nodes, (list, tuple)):
            plan_nodes = []
        node_params_by_id = {
            str(getattr(node, "node_id", "")): (getattr(node, "params", None) or {})
            for node in plan_nodes
        }
        for item in run_result.node_results:
            if item.success and item.tool_id == "products" and item.action == "query":
                rows = (item.output or {}).get("data") or []
                n = len(rows) if isinstance(rows, list) else 0
                lines.append(f"- {item.node_id}: 成功（产品库命中 {n} 条）")
                if isinstance(rows, list) and rows:
                    from app.utils.ai_helpers import format_money, safe_float

                    for row in rows[:5]:
                        if not isinstance(row, dict):
                            continue
                        m = str(row.get("model_number") or "").strip() or "-"
                        name = str(row.get("name") or row.get("product_name") or "-").strip()
                        p = safe_float(row.get("price"))
                        u = str(row.get("unit") or "").strip() or "-"
                        lines.append(f"    · {m} / {name} / ￥{format_money(p)} / 单位:{u}")
            elif item.success:
                node_params = node_params_by_id.get(str(item.node_id), {})
                lines.extend(self._format_workflow_tool_success_line(item, node_params))
            else:
                lines.append(f"- {item.node_id}: 失败（{item.error}）")
                retryable = getattr(item, "retryable", True)
                retryable = retryable if isinstance(retryable, bool) else True
                try:
                    retries = int(getattr(item, "retries", 0) or 0)
                except (TypeError, ValueError):
                    retries = 0
                if retryable and retries:
                    lines.append(f"    · 已自动重试: {retries} 次")
                elif not retryable:
                    lines.append("    · 未自动重试: 非幂等或中高风险操作")
                raw_recovery_hint = getattr(item, "recovery_hint", "")
                recovery_hint = (
                    raw_recovery_hint.strip() if isinstance(raw_recovery_hint, str) else ""
                )
                if recovery_hint:
                    lines.append(f"    · 恢复建议: {recovery_hint}")
        if run_result.message:
            lines.append(f"说明: {run_result.message}")
        response_text = "\n".join(lines)
        payload: dict[str, Any] = {
            "success": run_result.success,
            "message": "处理完成" if run_result.success else "处理失败",
            "response": response_text,
            "data": {
                "text": response_text,
                "action": "workflow_done" if run_result.success else "workflow_failed",
                "data": {
                    "plan_id": plan.plan_id,
                    "intent": plan.intent,
                    "thinking_steps": thinking_steps,
                    "todo": plan.todo_steps,
                    "node_results": [
                        {
                            "node_id": r.node_id,
                            "success": r.success,
                            "tool_id": r.tool_id,
                            "action": r.action,
                            "message": r.error or self._workflow_output_message(r.output),
                            "output_preview": self._workflow_output_preview(r.output),
                            "retries": getattr(r, "retries", 0),
                            "retryable": getattr(r, "retryable", True),
                            "recovery_hint": getattr(r, "recovery_hint", ""),
                            "duration_ms": getattr(r, "duration_ms", 0),
                        }
                        for r in run_result.node_results
                    ],
                    "workflow_status": getattr(run_result, "final_context", {}).get(
                        "workflow_status", {}
                    )
                    if isinstance(getattr(run_result, "final_context", {}), dict)
                    else {},
                    "workflow_trace": getattr(run_result, "final_context", {}).get(
                        "workflow_trace", []
                    )
                    if isinstance(getattr(run_result, "final_context", {}), dict)
                    else [],
                },
            },
        }
        if run_result.success and any(
            r.success and r.tool_id == "products" and r.action == "query"
            for r in run_result.node_results
        ):
            q = self._workflow_products_float_query(plan, run_result, user_message)
            payload["autoAction"] = {
                "type": "show_products_float",
                "feature": "products",
                "query": q,
            }
            if q:
                lines.append(f"\n已为你打开产品副窗，搜索：{q}")
            else:
                lines.append("\n已为你打开产品副窗，可在卡片中查询或编辑。")
            payload["response"] = "\n".join(lines)
            payload["data"]["text"] = payload["response"]

        slot_overlay = self._normal_slot_dispatch_chat_overlay(run_result)
        if slot_overlay:
            if slot_overlay.get("response"):
                payload["response"] = slot_overlay["response"]
            if slot_overlay.get("message"):
                payload["message"] = slot_overlay["message"]
            if slot_overlay.get("autoAction"):
                payload["autoAction"] = slot_overlay["autoAction"]
            if slot_overlay.get("task"):
                payload["task"] = slot_overlay["task"]
            payload.setdefault("data", {})
            payload["data"]["text"] = payload["response"]

        return payload

    @staticmethod
    def _normal_slot_dispatch_chat_overlay(run_result) -> dict[str, Any]:
        for item in reversed(run_result.node_results):
            if not item.success or item.tool_id != "normal_slot_dispatch":
                continue
            out = item.output or {}
            if not isinstance(out, dict) or not out.get("success"):
                continue
            if not (out.get("autoAction") or out.get("task")):
                continue
            picked: dict[str, Any] = {}
            for key in ("response", "message", "autoAction", "task"):
                if key in out:
                    picked[key] = out[key]
            return picked
        return {}

    def _dispatch_workflow_tool(
        self, tool_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool

            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except RECOVERABLE_ERRORS as err:
            logger.error(
                "workflow 工具调度失败 tool=%s action=%s err=%s",
                tool_id,
                action,
                err,
                exc_info=True,
            )
            return {"success": False, "message": str(err)}
