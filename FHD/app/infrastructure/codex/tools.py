"""Thin MCP-to-business-task bridge using the authoritative tool contracts.

The server creates operation identities, restores the bound principal per call,
and returns existing durable receipts. No model-supplied flag grants approval.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.task_models import mod_id_of_run, tenant_id_of_run
from app.application.agent_orchestrator.tool_permission import actor_tool_denial, redact
from app.application.agent_orchestrator.tool_spec import (
    ToolActionSpecV2,
    build_tool_specs_v2,
    get_tool_action_spec,
    validate_tool_call,
)
from app.application.agent_orchestrator.unified_task import create_unified_task
from app.domain.task_lifecycle.results import execution_result_outcome_unknown
from app.infrastructure.codex.binding import (
    CodexBinding,
    CodexBindingError,
    CodexBindingStore,
    canonical_digest,
)

CODEX_TOOL_NAMES = (
    "capability_search",
    "capability_describe",
    "execute_action",
    "execute_plan",
    "task_evidence",
    "request_input",
)
_CONTROL_TOOLS = frozenset({"aiopen", "conversation", "clarify"})
_AUTHORITY_KEYS = frozenset(
    {
        "tenant_id",
        "user_id",
        "actor_id",
        "local_user_id",
        "mod_id",
        "active_mod_id",
        "approved",
        "auto_approve",
        "skip_approval",
        "approval_id",
        "approval_grant",
        "permissions",
        "permission",
        "runtime_context",
        "employee_tool_allowlist",
        "system_prompt",
        "idempotency_key",
        "business_action_id",
        "parent_run_id",
        "run_id",
    }
)


def _safe_output(value: Any) -> Any:
    if isinstance(value, dict):
        return redact({k: _safe_output(v) for k, v in value.items() if not str(k).startswith("_")})
    if isinstance(value, list):
        return [_safe_output(v) for v in value]
    return value


def _unknown(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "verified": False,
        "status": "unknown",
        "outcome": "unknown",
        "task_id": call["child_task_id"],
        "run_id": call.get("child_run_id", ""),
        "reconciliation_required": True,
        "retryable": False,
        "message": "原业务调用结果尚未确定；请核对原任务，不可重新提交相同操作",
    }


def read_call_receipt(
    store: CodexBindingStore, binding: CodexBinding, call: dict[str, Any]
) -> dict[str, Any]:
    """Read business truth, never turn completion or MCP transport success."""
    child = store.repository.get(str(call.get("child_run_id") or ""))
    if child is None:
        task = store.repository.get_task(
            user_id=binding.run.user_id,
            task_id=call["child_task_id"],
            tenant_id=tenant_id_of_run(binding.run),
        )
        if task is not None:
            child = store.repository.get(task.active_run_id)
    if child is None:
        metadata = binding.metadata
        if (
            call.get("state") == "claimed"
            and call.get("generation") == metadata.get("generation")
            and metadata.get("coordinator_active")
            and not metadata.get("revoked")
            and float(metadata.get("expires_at", 0)) > time.time()
        ):
            return {
                "success": False,
                "verified": False,
                "status": "claimed",
                "task_id": call["child_task_id"],
                "run_id": "",
                "in_progress": True,
                "retryable": False,
                "message": "原调用正在登记业务任务，请读取原调用状态",
            }
        return _unknown(call)
    context = child.metadata.get("runtime_context") or {}
    if (
        child.user_id != binding.run.user_id
        or tenant_id_of_run(child) != tenant_id_of_run(binding.run)
        or mod_id_of_run(child) != mod_id_of_run(binding.run)
        or context.get("parent_run_id") != binding.run_id
        or (child.metadata.get("task_context") or {}).get("task_id") != call["child_task_id"]
    ):
        raise CodexBindingError("owner_changed", "业务回执不属于当前运行范围")
    outputs = [step.output for step in child.steps] + [record.output for record in child.tool_calls]
    total_cost = max(
        int(child.metadata.get("ai_cost_units_total") or 0),
        sum(int(record.cost_units or 0) for record in child.tool_calls)
        + sum(int(record.cost_units or 0) for record in child.llm_calls),
    )
    unknown = (
        bool(child.metadata.get("non_retryable"))
        and (child.metadata.get("recovery") or {}).get("state") == "manual_reconciliation_required"
    )
    if unknown or any(execution_result_outcome_unknown(output) for output in outputs):
        return {
            **_unknown(call),
            "run_id": child.run_id,
            "child_updated_at": child.updated_at,
            "ai_cost_units_total": total_cost,
        }
    from app.infrastructure.codex.workflow import verified_step

    workflow_verified = True
    is_workflow = (call.get("tool_id"), call.get("action")) == ("xcmax_workflow", "execute")
    if is_workflow:
        from app.infrastructure.codex.workflow import validate_workflow_receipt

        workflow_verified = validate_workflow_receipt(binding, call, child)
    else:
        nodes = (child.metadata.get("plan") or {}).get("nodes") or []
        if len(nodes) != 1 or len(child.steps) != 1:
            raise CodexBindingError("evidence_mismatch", "业务任务已偏离原调用冻结计划")
        node, step = nodes[0], child.steps[0]
        if (
            canonical_digest({key: node.get(key) for key in ("tool_id", "action", "params")})
            != call["fingerprint"]
            or node.get("node_id") != step.node_id
            or node.get("tool_id") != step.tool_id
            or node.get("action") != step.action
            or node.get("params") != step.params
            or list(node.get("depends_on") or []) != step.depends_on
        ):
            raise CodexBindingError("evidence_mismatch", "业务任务已偏离原调用冻结计划")
    latest = {record.step_id: record for record in child.tool_calls}
    completed_steps = [
        step
        for step in child.steps
        if step.status != "skipped"
        and not (is_workflow and (step.tool_id, step.action) == ("clarify", "ask"))
    ]
    verified = (
        child.status == "completed"
        and workflow_verified
        and bool(completed_steps)
        and all(verified_step(step, latest.get(step.step_id)) for step in completed_steps)
    )
    status = child.status
    if status == "completed" and not verified:
        status = "failed"
    approval_card = None
    clarification = None
    if status == "waiting_user":
        from app.application.workflow.approval_card import build_approval_card_payload

        waiting = [step for step in child.steps if step.status == "waiting_user"]
        question = next(
            (step for step in waiting if (step.tool_id, step.action) == ("clarify", "ask")), None
        )
        if question is not None:
            clarification = {
                **_safe_output(question.output),
                "run_id": child.run_id,
                "step_id": question.step_id,
            }
        waiting = [step for step in waiting if (step.tool_id, step.action) != ("clarify", "ask")]
        approval_card = (
            build_approval_card_payload(
                action="approval_pending",
                inner={
                    "run_id": child.run_id,
                    "plan_id": child.plan_id,
                    "intent": child.intent,
                    "blocking_nodes": [step.node_id for step in waiting],
                    "approval_required": True,
                    "approval_nodes": [
                        {
                            "step_id": step.step_id,
                            "node_id": step.node_id,
                            "tool_id": step.tool_id,
                            "action": step.action,
                            "params": _safe_output(step.params),
                        }
                        for step in waiting
                    ],
                    "todo": [
                        step.description or f"{step.tool_id}.{step.action}" for step in waiting
                    ],
                    "reason": "原任务的冻结业务操作需要用户审批",
                },
            )
            if waiting
            else None
        )
    return {
        "success": verified,
        "verified": verified,
        "status": status,
        "run_id": child.run_id,
        "task_id": call["child_task_id"],
        "child_updated_at": child.updated_at,
        "ai_cost_units_total": total_cost,
        "pending_approval": approval_card is not None,
        "approval_card": approval_card,
        "needs_user_input": clarification is not None,
        "clarification": clarification,
        "retryable": False,
        "reconciliation_required": False,
        "message": str(child.error or ("业务回执已核验" if verified else "业务任务尚未完成")),
        "tool_calls": [_safe_output(record.to_dict()) for record in latest.values()],
        "artifacts": [_safe_output(artifact.to_dict()) for artifact in child.artifacts],
    }


class CodexToolBridge:
    def __init__(
        self,
        store: CodexBindingStore,
        orchestrator: AgentOrchestrator | None = None,
        *,
        gate: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator or AgentOrchestrator(repository=store.repository)
        self.gate = gate
        self.run_id = run_id

    def _check_gate(self, binding: CodexBinding, spec: ToolActionSpecV2, params: dict) -> None:
        if self.gate is None:
            if (binding.metadata.get("runtime_config") or {}).get("gate_required"):
                raise CodexBindingError("gate_required", "原员工工作空间授权必须恢复后才能执行")
            return
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        try:
            verdict = self.gate(spec.tool_id, spec.action, copy.deepcopy(params))
        except RECOVERABLE_ERRORS as exc:
            raise CodexBindingError("gate_denied", "员工工具授权检查失败，未执行") from exc
        if not isinstance(verdict, dict) or verdict.get("ok") is not True:
            reason = (
                str(verdict.get("reason") or "员工工具授权拒绝")
                if isinstance(verdict, dict)
                else "员工工具授权结果无效"
            )
            raise CodexBindingError("gate_denied", reason)

    @staticmethod
    def _allowed(spec: ToolActionSpecV2, binding: CodexBinding, params=None) -> bool:
        if spec.tool_id in _CONTROL_TOOLS:
            return False
        allowlist = binding.metadata.get("allowed_actions")
        if allowlist is not None and f"{spec.tool_id}.{spec.action}" not in allowlist:
            return False
        return actor_tool_denial(spec.tool_id, spec.action, binding.context, params or {}) is None

    def invoke(self, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise CodexBindingError("invalid_arguments", "工具参数必须是对象")
        with self.store.scope(token, "mcp") as binding:
            if self.run_id is not None and binding.run_id != self.run_id:
                raise CodexBindingError("scope_conflict", "运行凭据不属于此工具入口")
            if name == "capability_search":
                query = str(arguments.get("query") or "").strip().casefold()[:200]
                limit = arguments.get("limit", 12)
                if type(limit) is not int or not 1 <= limit <= 30:
                    raise CodexBindingError("invalid_arguments", "能力检索数量必须为 1 至 30")
                matches = []
                for spec in build_tool_specs_v2().values():
                    text = f"{spec.tool_id}.{spec.action} {spec.description}".casefold()
                    if (not query or query in text) and self._allowed(spec, binding):
                        matches.append(
                            {
                                "tool_id": spec.tool_id,
                                "action": spec.action,
                                "description": spec.description,
                                "read_only": spec.read_only,
                            }
                        )
                    if len(matches) >= limit:
                        break
                return {"success": True, "capabilities": matches}
            if name == "capability_describe":
                spec = self._spec(binding, arguments)
                return {
                    "success": True,
                    "capability": {
                        "tool_id": spec.tool_id,
                        "action": spec.action,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                        "read_only": spec.read_only,
                        "risk": spec.risk,
                        "approval_required": not (spec.read_only and spec.risk == "low"),
                    },
                }
            if name == "request_input":
                question = arguments.get("question")
                if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                    raise CodexBindingError("invalid_arguments", "请提供明确的待补充问题")
                self.store.update(
                    binding.run_id,
                    lambda run, metadata: metadata.update(
                        waiting_input={"question": question.strip(), "created_at": utc_now_iso()}
                    ),
                    generation=binding.metadata["generation"],
                )
                return {
                    "success": False,
                    "needs_user_input": True,
                    "status": "waiting_user",
                    "question": question.strip(),
                    "verified": False,
                }
            if name == "task_evidence":
                return self._evidence(binding, str(arguments.get("call_id") or ""))
            if name == "execute_action":
                return self._execute(binding, arguments)
            if name == "execute_plan":
                return self._execute_plan(binding, arguments)
            raise CodexBindingError("unknown_tool", "工具不属于当前运行接口")

    def _spec(self, binding: CodexBinding, args: dict[str, Any]) -> ToolActionSpecV2:
        spec = get_tool_action_spec(str(args.get("tool_id") or ""), str(args.get("action") or ""))
        if spec is None or not self._allowed(spec, binding, args.get("params")):
            raise CodexBindingError("permission_denied", "当前账号或员工未获授权使用该能力")
        return spec

    def _evidence(self, binding: CodexBinding, call_id: str) -> dict[str, Any]:
        binding = self.store.check_current(
            binding.run_id, generation=binding.metadata["generation"]
        )
        call = binding.metadata.get("calls", {}).get(call_id)
        if call is None:
            raise CodexBindingError("call_missing", "本次运行没有该工具调用")
        if (call.get("tool_id"), call.get("action")) == ("xcmax_workflow", "execute"):
            self._plan(binding, call.get("params") or {})
        else:
            self._spec(binding, call)
        receipt = read_call_receipt(self.store, binding, call)
        saved = self.store.record_call(
            binding.run_id, call_id, child_run_id=receipt.get("run_id", ""), receipt=receipt
        )
        return dict(saved.metadata["calls"][call_id]["receipt"])

    def _execute(self, binding: CodexBinding, args: dict[str, Any]) -> dict[str, Any]:
        if binding.run.metadata.get("runtime_frozen_plan") is not None:
            raise CodexBindingError("goal_mismatch", "原任务必须通过 execute_plan 执行完整冻结图")
        params = args.get("params")
        if not isinstance(params, dict):
            raise CodexBindingError("invalid_arguments", "业务参数必须是对象")
        if len(json.dumps(params, ensure_ascii=False, allow_nan=False).encode()) > 256_000:
            raise CodexBindingError("invalid_arguments", "业务参数过大，请使用已归档文件引用")
        if any(str(key).startswith("_") or key in _AUTHORITY_KEYS for key in params):
            raise CodexBindingError("identity_override", "模型不得提交身份、授权或执行控制字段")
        spec = self._spec(binding, args)
        validation = validate_tool_call(spec.tool_id, spec.action, params)
        if not validation.ok:
            return {
                "success": False,
                "verified": False,
                "status": "not_started",
                "error_code": validation.error_code,
                "message": validation.message,
            }
        self._check_gate(binding, spec, params)
        call_id = args.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise CodexBindingError("invalid_call", "工具调用标识无效")
        safe_read = spec.read_only and spec.risk == "low"
        call, created = self.store.claim_call(
            binding.run_id,
            call_id,
            tool_id=spec.tool_id,
            action=spec.action,
            params=params,
            read_only=safe_read,
            generation=binding.metadata["generation"],
            cost_units=spec.cost_units,
        )
        if not created:
            return self._evidence(self.store.get(binding.run_id), call_id)
        context = self._child_context(binding, call)
        context["task_title"] = f"{spec.tool_id}.{spec.action}"
        self.store.check_current(binding.run_id, generation=binding.metadata["generation"])
        if safe_read:
            from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

            plan = PlanGraph(
                plan_id=f"plan_{call['child_task_id']}",
                intent=f"{spec.tool_id}.{spec.action}",
                nodes=[
                    WorkflowNode(
                        node_id="action",
                        tool_id=spec.tool_id,
                        action=spec.action,
                        params=copy.deepcopy(params),
                        risk=spec.risk,
                        idempotent=spec.idempotent,
                    )
                ],
                risk_level=spec.risk,
                metadata={"source": "codex_read_task"},
            )
            child = self.orchestrator.start_run_from_plan(
                user_id=binding.run.user_id,
                message=binding.run.message,
                plan=plan,
                runtime_context=context,
                auto_execute=False,
            )
        else:
            child = create_unified_task(
                orchestrator=self.orchestrator,
                user_id=binding.run.user_id,
                task_id=call["child_task_id"],
                title=f"{spec.tool_id}.{spec.action}",
                message=binding.run.message,
                tool_id=spec.tool_id,
                action=spec.action,
                params=copy.deepcopy(params),
                runtime_context=context,
            ).run
        # The child id is durable before dispatch. A lost response can only read
        # this task; it cannot mint a new approved operation and execute twice.
        self.store.record_call(binding.run_id, call_id, child_run_id=child.run_id)
        try:
            self.store.check_current(binding.run_id, generation=binding.metadata["generation"])
            self._spec(binding, args)
            self._check_gate(binding, spec, params)
        except CodexBindingError:
            self.orchestrator.cancel_run(child.run_id, requested_by=binding.run.user_id)
            raise
        if safe_read and child.status in {"queued", "running"}:
            self.orchestrator.execute_dispatched_run(child.run_id)
        return self._evidence(self.store.get(binding.run_id), call_id)

    def _plan(self, binding: CodexBinding, args: dict[str, Any]):
        from app.application.agent_orchestrator.param_references import unresolved_placeholders
        from app.infrastructure.codex.workflow import frozen_plan

        plan = frozen_plan(binding, str(args.get("plan_digest") or ""))
        for node in plan.nodes:
            spec = self._spec(
                binding, {"tool_id": node.tool_id, "action": node.action, "params": node.params}
            )
            validation = validate_tool_call(
                node.tool_id, node.action, node.params, allow_references_from=set(node.depends_on)
            )
            if not validation.ok:
                raise CodexBindingError("goal_changed", "冻结图的动作契约当前不可用")
            if not unresolved_placeholders(node.params):
                self._check_gate(binding, spec, node.params)
        return plan

    def _execute_plan(self, binding: CodexBinding, args: dict[str, Any]) -> dict[str, Any]:
        if set(args) != {"plan_digest", "call_id"}:
            raise CodexBindingError("invalid_arguments", "只能提交原图摘要和调用标识")
        plan = self._plan(binding, args)
        call_id = args.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise CodexBindingError("invalid_call", "工具调用标识无效")
        costs = 0
        for node in plan.nodes:
            spec = get_tool_action_spec(node.tool_id, node.action)
            if spec is None:
                raise CodexBindingError("goal_changed", "冻结图的动作契约当前不可用")
            costs += spec.cost_units
        call, created = self.store.claim_call(
            binding.run_id,
            call_id,
            tool_id="xcmax_workflow",
            action="execute",
            params={"plan_digest": args["plan_digest"]},
            read_only=False,
            generation=binding.metadata["generation"],
            cost_units=costs,
        )
        if not created:
            return self._evidence(self.store.get(binding.run_id), call_id)
        context = self._child_context(binding, call)
        child = self.orchestrator.start_run_from_plan(
            user_id=binding.run.user_id,
            message=binding.run.message,
            plan=plan,
            runtime_context=context,
            auto_execute=False,
        )
        self.store.record_call(binding.run_id, call_id, child_run_id=child.run_id)
        try:
            self.store.check_current(binding.run_id, generation=binding.metadata["generation"])
            self._plan(binding, args)
        except CodexBindingError:
            self.orchestrator.cancel_run(child.run_id, requested_by=binding.run.user_id)
            raise
        if child.status in {"queued", "running"}:
            self.orchestrator.execute_dispatched_run(child.run_id)
        return self._evidence(self.store.get(binding.run_id), call_id)

    @staticmethod
    def _child_context(binding: CodexBinding, call: dict[str, Any]) -> dict[str, Any]:
        from app.application.agent_orchestrator.budget import AI_COST_BUDGET_KEYS

        context = binding.context
        for key in (
            *AI_COST_BUDGET_KEYS,
            "run_id",
            "agent_run_id",
            "task_id",
            "approved_step_id",
            "approval_receipt",
            "idempotency_key",
            "plan_id",
            "node_outputs",
            "_tool_approval_grants",
        ):
            context.pop(key, None)
        if call.get("budget_units") is not None:
            context["ai_cost_budget_units"] = call["budget_units"]
        context.update(
            task_id=call["child_task_id"],
            parent_run_id=binding.run_id,
            parent_task_id=str(
                (binding.run.metadata.get("task_context") or {}).get("task_id") or binding.run_id
            ),
            root_run_id=str(context.get("root_run_id") or binding.run_id),
            source="codex_runtime",
        )
        return context


def mcp_tool_definitions():
    """Use MCP SDK types; schema is glue around the existing capability catalog."""
    from mcp.types import Tool

    fields = {"tool_id": {"type": "string"}, "action": {"type": "string"}}
    definitions = [
        (
            "capability_search",
            "检索当前账号获授权的企业能力。",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30},
            },
            [],
        ),
        (
            "capability_describe",
            "读取权威工具参数契约；执行前读取需要的能力。",
            fields,
            ["tool_id", "action"],
        ),
        (
            "execute_action",
            "提交企业动作到受控任务链。待审批或未知结果不是完成，不可更换调用标识重复提交。",
            {**fields, "call_id": {"type": "string"}, "params": {"type": "object"}},
            ["tool_id", "action", "call_id", "params"],
        ),
        (
            "execute_plan",
            "按摘要提交宿主已冻结的完整业务图；保留顺序、条件、审批和原任务回执，不接收模型改图。",
            {"plan_digest": {"type": "string"}, "call_id": {"type": "string"}},
            ["plan_digest", "call_id"],
        ),
        (
            "task_evidence",
            "读取本次运行已提交动作的真实任务状态和证据。",
            {"call_id": {"type": "string"}},
            ["call_id"],
        ),
        (
            "request_input",
            "用户必须补充信息时登记问题并等待；不把提问当任务完成。",
            {"question": {"type": "string"}},
            ["question"],
        ),
    ]
    return [
        Tool(
            name=name,
            description=description,
            inputSchema={
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        )
        for name, description, props, required in definitions
    ]
