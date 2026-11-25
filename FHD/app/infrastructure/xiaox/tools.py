"""Thin MCP-to-business-task bridge using the authoritative tool contracts.

The server creates operation identities, restores the bound principal per call,
and returns existing durable receipts. No model-supplied flag grants approval.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.tool_spec import (
    ToolActionSpecV2,
    build_tool_specs_v2,
    get_tool_action_spec,
    validate_tool_call,
)
from app.application.agent_orchestrator.unified_task import create_unified_task
from app.infrastructure.xiaox.binding import (
    XiaoxBinding,
    XiaoxBindingError,
    XiaoxBindingStore,
)
from app.infrastructure.xiaox.receipts import read_call_receipt
from app.infrastructure.xiaox.tool_names import XIAOX_TOOL_NAMES

_CONTROL_TOOLS = frozenset({"conversation", "clarify"})
# These contracts use run_id to select an existing business object. The host's
# current execution identity remains exclusively in the bound runtime context.
_BUSINESS_RUN_TARGETS = frozenset(
    {("elt_import", "preview"), ("elt_import", "execute"), ("enterprise_cognition", "evaluate")}
)
_AUTHORITY_KEYS = frozenset(
    {
        "tenant_id",
        "user_id",
        "actor_id",
        "local_user_id",
        "mod_id",
        "active_mod_id",
        "approved",
        "human_approved",
        "approved_by",
        "approved_step_id",
        "auto_approve",
        "skip_approval",
        "approval_id",
        "approval_grant",
        "approval_request_id",
        "approval_receipt",
        "permissions",
        "permission",
        "runtime_context",
        "employee_tool_allowlist",
        "system_prompt",
        "tool_schema_digest",
        "idempotency_key",
        "business_action_id",
        "call_id",
        "tool_call_id",
        "step_id",
        "node_id",
        "task_id",
        "parent_run_id",
        "run_id",
    }
)


class XiaoxToolBridge:
    def __init__(
        self,
        store: XiaoxBindingStore,
        orchestrator: AgentOrchestrator | None = None,
        *,
        gate: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None,
        run_id: str | None = None,
    ) -> None:
        self.store = store
        self.orchestrator = orchestrator or AgentOrchestrator(repository=store.repository)
        self.gate = gate
        self.run_id = run_id

    def _check_gate(self, binding: XiaoxBinding, spec: ToolActionSpecV2, params: dict) -> None:
        from app.application.enterprise_cognition.execution import validate_goal_action
        from app.application.enterprise_cognition.goals import GoalBindingError

        try:
            validate_goal_action(
                binding.context,
                spec.tool_id,
                spec.action,
                params,
                read_only=spec.is_read_only_call(params),
            )
        except GoalBindingError as exc:
            raise XiaoxBindingError("goal_scope_denied", str(exc)) from exc
        if self.gate is None:
            if (binding.metadata.get("runtime_config") or {}).get("gate_required"):
                raise XiaoxBindingError("gate_required", "原员工工作空间授权必须恢复后才能执行")
            return
        from app.utils.operational_errors import RECOVERABLE_ERRORS

        try:
            verdict = self.gate(spec.tool_id, spec.action, copy.deepcopy(params))
        except RECOVERABLE_ERRORS as exc:
            raise XiaoxBindingError("gate_denied", "员工工具授权检查失败，未执行") from exc
        if not isinstance(verdict, dict) or verdict.get("ok") is not True:
            reason = (
                str(verdict.get("reason") or "员工工具授权拒绝")
                if isinstance(verdict, dict)
                else "员工工具授权结果无效"
            )
            raise XiaoxBindingError("gate_denied", reason)

    @staticmethod
    def _allowed(spec: ToolActionSpecV2, binding: XiaoxBinding, params=None) -> bool:
        if spec.tool_id in _CONTROL_TOOLS:
            return False
        if spec.tool_id == "aiopen":
            from app.application.aiopen.agent_bridge import supports_aiopen_step

            if not supports_aiopen_step(spec.action):
                return False
        allowlist = binding.metadata.get("allowed_actions")
        if allowlist is not None and f"{spec.tool_id}.{spec.action}" not in allowlist:
            return False
        return actor_tool_denial(spec.tool_id, spec.action, binding.context, params or {}) is None

    def invoke(self, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise XiaoxBindingError("invalid_arguments", "工具参数必须是对象")
        with self.store.scope(token, "mcp") as binding:
            if self.run_id is not None and binding.run_id != self.run_id:
                raise XiaoxBindingError("scope_conflict", "运行凭据不属于此工具入口")
            if name == "capability_search":
                query = str(arguments.get("query") or "").strip().casefold()[:200]
                limit = arguments.get("limit", 12)
                offset = arguments.get("offset", 0)
                if type(limit) is not int or not 1 <= limit <= 30:
                    raise XiaoxBindingError("invalid_arguments", "能力检索数量必须为 1 至 30")
                if type(offset) is not int or offset < 0:
                    raise XiaoxBindingError("invalid_arguments", "能力检索起点必须为非负整数")
                matches = []
                for _, spec in sorted(build_tool_specs_v2().items()):
                    text = f"{spec.tool_id}.{spec.action} {spec.description}".casefold()
                    if all(word in text for word in query.split()) and self._allowed(spec, binding):
                        matches.append(
                            {
                                "tool_id": spec.tool_id,
                                "action": spec.action,
                                "description": spec.description,
                                "read_only": spec.read_only,
                            }
                        )
                end = offset + limit
                return {
                    "success": True,
                    "capabilities": matches[offset:end],
                    "total": len(matches),
                    "next_offset": end if end < len(matches) else None,
                }
            if name == "capability_describe":
                spec = self._spec(binding, arguments)
                return {
                    "success": True,
                    "capability": {
                        "tool_id": spec.tool_id,
                        "action": spec.action,
                        "description": spec.description,
                        "input_schema": spec.input_schema,
                        "output_schema": spec.output_schema,
                        "schema_digest": spec.schema_digest,
                        "read_only": spec.read_only,
                        "read_only_if_unset": spec.read_only_if_unset,
                        "risk": spec.risk,
                        "idempotent": spec.idempotent,
                        "required_params": spec.required_params,
                        "timeout_seconds": spec.timeout_seconds,
                        "approval_required": not (spec.read_only and spec.risk == "low"),
                    },
                }
            if name == "request_input":
                question = arguments.get("question")
                if not isinstance(question, str) or not question.strip() or len(question) > 4000:
                    raise XiaoxBindingError("invalid_arguments", "请提供明确的待补充问题")
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
                from app.application.tool_execution_deadline import invocation_deadline

                # The MCP server thread predates begin_active. Restore its
                # current SQL budget instead of inheriting stale thread state
                # or accepting a model-supplied deadline field.
                active = binding.metadata.get("active_started_at") is not None
                budget = (
                    invocation_deadline(
                        time.monotonic()
                        + max(0.0, float(binding.metadata["deadline_at"]) - time.time())
                    )
                    if active
                    else nullcontext()
                )
                with budget:
                    return self._execute(binding, arguments)
            raise XiaoxBindingError("unknown_tool", "工具不属于当前运行接口")

    def _spec(self, binding: XiaoxBinding, args: dict[str, Any]) -> ToolActionSpecV2:
        spec = get_tool_action_spec(str(args.get("tool_id") or ""), str(args.get("action") or ""))
        if spec is None or not self._allowed(spec, binding, args.get("params")):
            raise XiaoxBindingError("permission_denied", "当前账号或员工未获授权使用该能力")
        return spec

    def _evidence(self, binding: XiaoxBinding, call_id: str) -> dict[str, Any]:
        binding = self.store.check_current(
            binding.run_id, generation=binding.metadata["generation"]
        )
        call = binding.metadata.get("calls", {}).get(call_id)
        if call is None:
            raise XiaoxBindingError("call_missing", "本次运行没有该工具调用")
        if (call.get("tool_id"), call.get("action")) != ("xcmax_workflow", "execute"):
            self._spec(binding, call)
        receipt = read_call_receipt(self.store, binding, call)
        saved = self.store.record_call(
            binding.run_id, call_id, child_run_id=receipt.get("run_id", ""), receipt=receipt
        )
        return dict(saved.metadata["calls"][call_id]["receipt"])

    def _execute(self, binding: XiaoxBinding, args: dict[str, Any]) -> dict[str, Any]:
        params = args.get("params")
        if not isinstance(params, dict):
            raise XiaoxBindingError("invalid_arguments", "业务参数必须是对象")
        if len(json.dumps(params, ensure_ascii=False, allow_nan=False).encode()) > 256_000:
            raise XiaoxBindingError("invalid_arguments", "业务参数过大，请使用已归档文件引用")
        business_run_target = (
            str(args.get("tool_id") or ""),
            str(args.get("action") or ""),
        ) in _BUSINESS_RUN_TARGETS
        if any(
            str(key).startswith("_")
            or (key in _AUTHORITY_KEYS and not (key == "run_id" and business_run_target))
            for key in params
        ):
            raise XiaoxBindingError("identity_override", "模型不得提交身份、授权或执行控制字段")
        spec = self._spec(binding, args)
        from app.domain.task_lifecycle.execution_mode import CONTEXT_KEY, deny_reason

        blocked = deny_reason(binding.context.get(CONTEXT_KEY), spec.tool_id, spec.action, params)
        if blocked:
            # Refuse before claiming the call, so plan mode cannot mint a child task
            # or an approval that a later turn could resume.
            return {
                "success": False,
                "verified": False,
                "status": "not_started",
                "error_code": "execution_mode_plan_blocked",
                "message": blocked,
            }
        self._check_schema(spec, args)
        validation = validate_tool_call(spec.tool_id, spec.action, params)
        from jsonschema import Draft202012Validator, SchemaError
        from referencing import Registry
        from referencing.exceptions import Unresolvable

        try:
            schema_valid = Draft202012Validator(spec.input_schema, registry=Registry()).is_valid(
                params
            )
        except (SchemaError, Unresolvable):
            schema_valid = False
        if not validation.ok or not schema_valid:
            return {
                "success": False,
                "verified": False,
                "status": "not_started",
                "error_code": validation.error_code or "schema_validation_failed",
                "message": validation.message or "参数不符合当前精确契约，请读取 schema 后补充。",
            }
        if spec.tool_id == "aiopen" and not spec.is_read_only_call(params):
            from app.application.aiopen.agent_bridge import inline_verification

            if not inline_verification(params):
                return {
                    "success": False,
                    "verified": False,
                    "status": "not_started",
                    "error_code": "verification_required",
                    "message": "请先提供同 session_id 的明确 verification 后置条件；本次未执行。",
                }
        self._check_gate(binding, spec, params)
        call_id = args.get("call_id")
        if not isinstance(call_id, str) or not call_id.strip():
            raise XiaoxBindingError("invalid_call", "工具调用标识无效")
        safe_read = spec.is_read_only_call(params) and spec.risk == "low"
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
        context["tool_schema_digest"] = spec.schema_digest
        # This child proves exactly one registered action. The original user
        # objective remains immutable on the parent; it is not this child's
        # completion criterion (a read may precede a requested business write).
        action_message = f"执行已登记能力 {spec.tool_id}.{spec.action}"
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
                metadata={"source": "xiaox_read_task"},
            )
            child = self.orchestrator.start_run_from_plan(
                user_id=binding.run.user_id,
                message=action_message,
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
            self._check_schema(self._spec(binding, args), args)
            self._check_gate(binding, spec, params)
        except XiaoxBindingError:
            self.orchestrator.cancel_run(child.run_id, requested_by=binding.run.user_id)
            raise
        if child.status in {"queued", "running"}:
            # 只读子任务必须派发；自动审批模式下的写子任务也不再停在审批断点。
            self.orchestrator.execute_dispatched_run(child.run_id)
        return self._evidence(self.store.get(binding.run_id), call_id)

    @staticmethod
    def _check_schema(spec: ToolActionSpecV2, args: dict[str, Any]) -> None:
        if args.get("schema_digest") != spec.schema_digest:
            raise XiaoxBindingError(
                "schema_changed",
                "请先读取 capability_describe 的当前契约和 schema_digest，再提交动作",
            )

    @staticmethod
    def _child_context(binding: XiaoxBinding, call: dict[str, Any]) -> dict[str, Any]:
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
            "tool_schema_digest",
        ):
            context.pop(key, None)
        context.pop("attachment_upload_ids", None)
        goal = binding.run.metadata.get("runtime_goal_contract") or {}
        upload_ids = [
            artifact["metadata"]["upload_id"]
            for artifact in goal.get("request", {}).get("attachments", [])
            if artifact.get("source") == "owned_elt_upload"
        ]
        if upload_ids:
            context["attachment_upload_ids"] = upload_ids
        if call.get("budget_units") is not None:
            context["ai_cost_budget_units"] = call["budget_units"]
        context.update(
            task_id=call["child_task_id"],
            parent_run_id=binding.run_id,
            parent_task_id=str(
                (binding.run.metadata.get("task_context") or {}).get("task_id") or binding.run_id
            ),
            root_run_id=str(context.get("root_run_id") or binding.run_id),
            source="xiaox_runtime",
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
                "offset": {"type": "integer", "minimum": 0},
            },
            [],
        ),
        (
            "capability_describe",
            "读取当前能力的精确参数和结果契约、风险及 schema_digest；执行动作必须使用此摘要。",
            fields,
            ["tool_id", "action"],
        ),
        (
            "execute_action",
            "提交企业动作到受控任务链。待审批或未知结果不是完成，不可更换调用标识重复提交。",
            {
                **fields,
                "call_id": {"type": "string"},
                "schema_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "params": {"type": "object"},
            },
            ["tool_id", "action", "call_id", "schema_digest", "params"],
        ),
        (
            "task_evidence",
            "读取本次运行已提交动作的真实任务状态和证据。",
            {"call_id": {"type": "string"}},
            ["call_id"],
        ),
        (
            "request_input",
            "仅当缺失信息确实阻断当前交付或业务操作缺关键参数时登记问题并等待；"
            "可在对话内完成的草案和修订应先直接交付，不得为对话内修订索要任务或目标内部 ID。"
            "提问不等于任务完成，也不构成审批或执行授权。",
            {"question": {"type": "string"}},
            ["question"],
        ),
    ]
    definitions_by_name = {
        name: (description, props, required) for name, description, props, required in definitions
    }
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
        for name in XIAOX_TOOL_NAMES
        for description, props, required in [definitions_by_name[name]]
    ]
