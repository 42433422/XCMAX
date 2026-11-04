"""Workflow response formatting mixin for AIChatWorkflowResponseMixin."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.application import agent_task_context
from app.application.agent_orchestrator.public_step_errors import public_step_error

logger = logging.getLogger(__name__)
_PUBLIC_WORKFLOW_FAILURE = "工作流执行失败，详细信息已记录"


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
                reason = public_step_error(step) or _PUBLIC_WORKFLOW_FAILURE
                lines.append(f"- {step.node_id}: {step.status}（{reason}）")

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
                            "message": (
                                self._workflow_output_message(step.output)
                                if step.status == "completed"
                                else public_step_error(step) or _PUBLIC_WORKFLOW_FAILURE
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

    def _format_workflow_run_response(
        self,
        plan,
        run_result,
        thinking_steps: str = "",
        user_message: str = "",
        state_updates: list[dict[str, Any]] | None = None,
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
                lines.append(
                    f"- {item.node_id}: 失败（{public_step_error(item, allow_reference_message=False) or _PUBLIC_WORKFLOW_FAILURE}）"
                )
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
                    lines.append("    · 恢复建议: 请检查依赖服务后重试")
        if run_result.success and run_result.message:
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
                            "message": (
                                self._workflow_output_message(r.output)
                                if r.success
                                else public_step_error(r, allow_reference_message=False)
                                or _PUBLIC_WORKFLOW_FAILURE
                            ),
                            "output_preview": self._workflow_output_preview(r.output)
                            if r.success
                            else "",
                            "retries": getattr(r, "retries", 0),
                            "retryable": getattr(r, "retryable", True),
                            "recovery_hint": ("" if r.success else "请检查依赖服务后重试"),
                            "duration_ms": getattr(r, "duration_ms", 0),
                        }
                        for r in run_result.node_results
                    ],
                    "workflow_status": getattr(run_result, "final_context", {}).get(
                        "workflow_status", {}
                    )
                    if run_result.success
                    and isinstance(getattr(run_result, "final_context", {}), dict)
                    else {},
                    "workflow_trace": getattr(run_result, "final_context", {}).get(
                        "workflow_trace", []
                    )
                    if run_result.success
                    and isinstance(getattr(run_result, "final_context", {}), dict)
                    else [],
                    "state_updates": (state_updates or []) if run_result.success else [],
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
