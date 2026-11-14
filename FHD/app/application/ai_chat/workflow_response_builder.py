"""Workflow response formatting mixin for AIChatWorkflowResponseMixin."""

from __future__ import annotations

import json
from typing import Any

from app.application import agent_task_context
from app.application.agent_orchestrator.public_step_errors import public_step_error

_PUBLIC_WORKFLOW_FAILURE = "工作流执行失败，详细信息已记录"


def _customer_query_summary(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    rows, total = output.get("data"), output.get("total")
    if not isinstance(rows, list) or type(total) is not int or total < 0:
        return None
    lines = [f"客户总数：{total}；本次显示 {len(rows)} 条。"]
    for row in rows:
        if isinstance(row, dict):
            name = str(row.get("customer_name") or row.get("unit_name") or "").strip()
            if name:
                lines.append(f"- {name}")
    return "\n".join(lines)


def normalize_product_float_query(raw: str) -> str:
    """Keep specific product terms while preserving an empty full-list query."""
    text = str(raw or "").strip()
    candidate = text.rstrip("。！？…").strip()
    for prefix in ("查询", "查一下", "查下", "查看", "看看", "看下", "查"):
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix) :].strip()
            break
    for scope in ("当前", "现有", "全部", "所有"):
        if candidate.startswith(scope):
            candidate = candidate[len(scope) :].strip()
            break
    if candidate in {"产品", "产品列表", "产品库"}:
        return ""
    return text


class AIChatWorkflowResponseMixin:
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
            f"4) 执行方式: 按业务依赖顺序推进，并持续回写状态\n"
            f"5) 业务步骤:\n{nodes_text}"
        )

    @staticmethod
    def _attach_task_tenant(runtime_context: dict[str, Any]) -> None:
        agent_task_context.attach_scoped_tenant(runtime_context)

    @staticmethod
    def _task_owner_id(user_id: str, runtime_context: dict[str, Any]) -> str:
        return agent_task_context.authenticated_task_owner(user_id, runtime_context)

    @staticmethod
    def _normalize_product_query(raw: str) -> str:
        return normalize_product_float_query(raw)

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
                reason = public_step_error(step)
                if reason:
                    lines.append(f"- {step.node_id}: {step.status}（{reason}）")
                elif step.status in {"pending", "skipped"}:
                    lines.append(f"- {step.node_id}: 未执行（前序步骤未完成或已中止）")
                else:
                    lines.append(f"- {step.node_id}: {step.status}（{_PUBLIC_WORKFLOW_FAILURE}）")

        from app.domain.task_lifecycle.results import execution_result_outcome_unknown

        recovery = (agent_run.metadata or {}).get("recovery")
        uncertain = (
            isinstance(recovery, dict) and recovery.get("state") == "manual_reconciliation_required"
        ) or any(
            isinstance(step.output, dict) and execution_result_outcome_unknown(step.output)
            for step in getattr(agent_run, "steps", []) or []
        )
        success = agent_run.status == "completed" and not uncertain
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
        steps = getattr(agent_run, "steps", []) or []
        if success and len(steps) == 1:
            step = steps[0]
            if (step.status, step.tool_id, step.action) == ("completed", "customers", "query"):
                response_text = _customer_query_summary(step.output) or response_text
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
                            "message": (
                                self._workflow_output_message(step.output)
                                if step.status == "completed"
                                else public_step_error(step)
                                or (
                                    "未执行（前序步骤未完成或已中止）"
                                    if step.status in {"pending", "skipped"}
                                    else _PUBLIC_WORKFLOW_FAILURE
                                )
                            ),
                            "output_preview": (
                                self._workflow_output_preview(step.output)
                                if step.status == "completed"
                                else ""
                            ),
                            "duration_ms": step.duration_ms,
                        }
                        for step in getattr(agent_run, "steps", []) or []
                    ],
                },
            },
        }
        if uncertain:
            text = "业务结果暂时无法核实，请核对原任务和业务数据，勿重复提交。"
            payload.update(
                success=False,
                message=text,
                response=text,
                execution_state="unknown",
                requires_reconciliation=True,
                retryable=False,
            )
            payload["data"].update(text=text, requires_reconciliation=True)
        write_actions = {"write", "create", "update", "delete", "batch_delete", "clear_dataset"}
        wrote = any(
            step.status == "completed" and step.action in write_actions for step in steps
        )
        if not success and not uncertain and not wrote:
            payload["execution"] = {
                "idempotency_key": "",
                "intent": str(getattr(plan, "intent", "") or ""),
                "committed": False,
                "effect": "none",
            }
        if success and any(
            step.status == "completed" and step.tool_id == "products" and step.action == "query"
            for step in getattr(agent_run, "steps", []) or []
        ):
            query = ""
            for step in getattr(agent_run, "steps", []) or []:
                if (
                    step.status != "completed"
                    or step.tool_id != "products"
                    or step.action != "query"
                ):
                    continue
                params = node_params_by_id.get(str(step.node_id), {})
                query = normalize_product_float_query(
                    str(
                        params.get("keyword")
                        or params.get("model_number")
                        or params.get("product_name")
                        or params.get("name")
                        or ""
                    )
                )
                if query:
                    break
            payload["autoAction"] = {
                "type": "show_products_float",
                "feature": "products",
                "query": query or normalize_product_float_query(user_message),
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
        return str(output.get("message") or "").strip()

    def _format_workflow_tool_success_line(
        self,
        item,
        node_params: dict[str, Any],
    ) -> list[str]:
        output = getattr(item, "output", None)
        out = output if isinstance(output, dict) else {}
        message = self._workflow_output_message(out)
        preview = self._workflow_output_preview(out)

        if item.tool_id == "customers" and item.action == "query":
            summary = _customer_query_summary(out)
            if summary is not None:
                return [f"- {item.node_id}: {summary}"]

        if item.tool_id == "employee":
            if item.action in ("list", "query"):
                data = out.get("data") if isinstance(out.get("data"), dict) else {}
                if not isinstance(data, dict):
                    data = {}
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
