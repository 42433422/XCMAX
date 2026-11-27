"""Thin MCP-to-business-task bridge using the authoritative tool contracts.

The server creates operation identities, restores the bound principal per call,
and returns existing durable receipts. No model-supplied flag grants approval.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager, nullcontext
from typing import TYPE_CHECKING, Any

from app.application.agent_orchestrator.orchestrator import AgentOrchestrator
from app.application.agent_orchestrator.run_models import utc_now_iso
from app.application.agent_orchestrator.tool_permission import actor_tool_denial
from app.application.agent_orchestrator.tool_spec import (
    ToolActionSpecV2,
    get_tool_action_spec,
    validate_tool_call,
)
from app.application.agent_orchestrator.unified_task import create_unified_task
from app.domain.workbook_write_contract import (
    WORKBOOK_READER,
    WORKBOOK_WRITE_REVIEW,
    WORKBOOK_WRITER,
)
from app.infrastructure.xiaox.binding import (
    XiaoxBinding,
    XiaoxBindingError,
    XiaoxBindingStore,
    canonical_digest,
)
from app.infrastructure.xiaox.receipts import read_call_receipt
from app.infrastructure.xiaox.tool_names import DIRECT_ACTION_TOOLS, XIAOX_TOOL_NAMES

if TYPE_CHECKING:
    from jsonschema import ValidationError
    from mcp.types import Tool

_CONTROL_TOOLS = frozenset({"conversation", "clarify"})
logger = logging.getLogger(__name__)
_NAVIGATION_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}")
_NAVIGATION_LABEL = re.compile(r"[\w ·&/()（）【】、，+\-]{1,80}")


def desktop_navigation_items(value: object) -> list[dict[str, Any]]:
    """Bound display metadata from this renderer turn before saving the run."""
    items: dict[str, dict[str, Any]] = {}
    for row in value[:128] if isinstance(value, list) else ():
        if not isinstance(row, dict) or row.keys() != {"id", "label", "kind", "breadcrumb"}:
            continue
        key, label, kind, parents = (row[k] for k in ("id", "label", "kind", "breadcrumb"))
        if not isinstance(key, str) or not _NAVIGATION_ID.fullmatch(key) or key in items:
            continue
        if kind not in ("page", "user_action") or not isinstance(parents, list) or len(parents) > 6:
            continue
        if all(
            isinstance(s, str) and s.strip() and _NAVIGATION_LABEL.fullmatch(s) and "//" not in s
            for s in [label, *parents]
        ):
            items[key] = {"id": key, "kind": kind, "label": label, "breadcrumb": parents.copy()}
    return list(items.values())


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


def schema_violation(error: ValidationError) -> dict[str, str | int | float | list[str]]:
    """Show the matching variant's bad field without exposing its instance or message."""
    while error.validator == "oneOf" and error.context and isinstance(error.instance, dict):
        matching = []
        for index, branch in enumerate(error.validator_value):
            if not isinstance(branch, dict):
                continue
            checks = {
                name: field["const"]
                for name, field in (branch.get("properties") or {}).items()
                if isinstance(field, dict) and "const" in field
            }
            if checks and all(
                name in error.instance and error.instance[name] == value
                for name, value in checks.items()
            ):
                matching.append(index)
        if len(matching) != 1:
            break
        child = next(
            (
                item
                for item in error.context
                if item.schema_path and item.schema_path[0] == matching[0]
            ),
            None,
        )
        if child is None:
            break
        error = child
    schema_path = list(error.absolute_schema_path)
    fields = {
        name
        for keyword, name in zip(schema_path, schema_path[1:], strict=False)
        if keyword == "properties"
    }
    path = "$" + "".join(
        f"[{part}]"
        if isinstance(part, int)
        else f".{part}"
        if part in fields and part.isidentifier()
        else ".*"
        for part in list(error.absolute_path)[:12]
    )
    violation: dict[str, str | int | float | list[str]] = {
        "path": path[:180],
        "validator": str(error.validator or "schema")[:32],
    }
    if error.validator == "type":
        from jsonschema import Draft202012Validator

        expected = error.validator_value
        violation["expected"] = expected if isinstance(expected, list) else str(expected)
        violation["received"] = next(
            (
                name
                for name in ("null", "boolean", "string", "array", "object", "integer", "number")
                if Draft202012Validator.TYPE_CHECKER.is_type(error.instance, name)
            ),
            "unknown",
        )
    if (error.validator == "pattern" and len(error.validator_value) <= 256) or error.validator in {
        "maximum",
        "minimum",
        "maxLength",
        "minLength",
        "maxItems",
        "minItems",
    }:
        violation["expected"] = error.validator_value
    if error.validator == "additionalProperties" and not error.schema.get("patternProperties"):
        properties = error.schema.get("properties", {})
        if isinstance(properties, dict) and len(properties) <= 24:
            violation["allowed"] = list(properties)
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [
            name
            for name in error.validator_value
            if name not in error.instance and len(name) <= 48 and name.isidentifier()
        ][:4]
        if missing:
            violation["missing"] = missing
    return violation


def action_schema_violation(
    spec: ToolActionSpecV2, params: dict[str, Any]
) -> dict[str, str | int | float | list[str]]:
    from jsonschema import Draft202012Validator, SchemaError
    from referencing import Registry
    from referencing.exceptions import Unresolvable

    try:
        validator = Draft202012Validator(spec.input_schema, registry=Registry())
        error = next(validator.iter_errors(params), None)
    except (SchemaError, Unresolvable):
        return {"path": "$", "validator": "schema"}
    return schema_violation(error) if error is not None else {}


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
        if (spec.tool_id, spec.action) == ("conversation_history", "read_attachment"):
            from app.application.agent_runtime.conversation_attachments import (
                recalled_conversation_uploads,
            )

            goal = binding.run.metadata.get("runtime_goal_contract") or {}
            request = goal.get("request") or {}
            if not any(
                item.get("source") == "owned_elt_upload" for item in request.get("attachments", [])
            ) and not recalled_conversation_uploads(request):
                return False
        if spec.tool_id == "aiopen":
            from app.application.aiopen.agent_bridge import supports_aiopen_step

            if not supports_aiopen_step(spec.action):
                return False
        allowlist = binding.metadata.get("allowed_actions")
        if allowlist is not None and f"{spec.tool_id}.{spec.action}" not in allowlist:
            return False
        return actor_tool_denial(spec.tool_id, spec.action, binding.context, params or {}) is None

    @contextmanager
    def _scope(self, token: str) -> Iterator[XiaoxBinding]:
        with self.store.scope(token, "mcp") as binding:
            if self.run_id is not None and binding.run_id != self.run_id:
                raise XiaoxBindingError("scope_conflict", "运行凭据不属于此工具入口")
            yield binding

    @classmethod
    def visible_actions(cls, binding: XiaoxBinding, words: list[str]) -> Iterator[ToolActionSpecV2]:
        from app.application.capability_catalog import authorized_tool_specs

        allowed_actions = binding.metadata.get("allowed_actions")
        candidates = None
        if allowed_actions is not None:
            from app.application.agent_orchestrator.tool_spec import build_tool_specs_v2

            allowed = set(allowed_actions)
            candidates = {
                key: spec
                for key, spec in build_tool_specs_v2().items()
                if f"{key[0]}.{key[1]}" in allowed
            }
            if not candidates:
                return
        specs = authorized_tool_specs(binding.context, include_aiopen=True, specs=candidates)
        for _, spec in sorted(specs.items()):
            if words:
                text = f"{spec.tool_id}.{spec.action} {spec.description}".casefold()
                if not any(word in text for word in words):
                    continue
            if cls._allowed(spec, binding):
                yield spec

    def list_tool_definitions(self, token: str) -> list[Tool]:
        with self._scope(token) as binding:
            return mcp_tool_definitions(
                (spec.tool_id, spec.action) for spec in self.visible_actions(binding, [])
            )

    def invoke(self, token: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise XiaoxBindingError("invalid_arguments", "工具参数必须是对象")
        with self._scope(token) as binding:
            if name == "capability_search":
                words = str(arguments.get("query") or "").strip().casefold()[:200].split()
                limit = arguments.get("limit", 12)
                offset = arguments.get("offset", 0)
                if type(limit) is not int or not 1 <= limit <= 30:
                    raise XiaoxBindingError("invalid_arguments", "能力检索数量必须为 1 至 30")
                if type(offset) is not int or offset < 0:
                    raise XiaoxBindingError("invalid_arguments", "能力检索起点必须为非负整数")
                matches = [
                    {
                        "tool_id": spec.tool_id,
                        "action": spec.action,
                        "description": spec.description,
                        "read_only": spec.read_only,
                    }
                    for spec in self.visible_actions(binding, words)
                ]
                if words:
                    matches.sort(
                        key=lambda row: (
                            -sum(
                                word
                                in f"{row['tool_id']}.{row['action']} {row['description']}".casefold()
                                for word in words
                            ),
                            row["tool_id"],
                            row["action"],
                        )
                    )
                end = offset + limit
                # These are display-only rows from this run's renderer. Describe and
                # _execute resolve exclusive authority from the server tool catalog.
                navigation = [
                    row
                    for row in desktop_navigation_items(binding.context.get("desktop_navigation"))
                    if all(
                        word in " ".join([row["id"], *row["breadcrumb"], row["label"]]).casefold()
                        for word in words
                    )
                ]
                return {
                    "success": True,
                    "capabilities": matches[offset:end],
                    "total": len(matches),
                    "next_offset": end if end < len(matches) else None,
                    "desktop_navigation": navigation[offset:end],
                    "navigation_next_offset": end if end < len(navigation) else None,
                }
            if name == "capability_describe":
                spec = self.authorized_action_spec(binding, arguments)
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
                        "approval_required": spec.approval_required,
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
            if name in {"execute_action", "execute_employee", *DIRECT_ACTION_TOOLS}:
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
                    if name == "execute_employee" or name in DIRECT_ACTION_TOOLS:
                        tool_id, action = (
                            ("employee", "execute")
                            if name == "execute_employee"
                            else DIRECT_ACTION_TOOLS[name]
                        )
                        arguments = {
                            "tool_id": tool_id,
                            "action": action,
                            "call_id": arguments.get("call_id"),
                            "schema_digest": arguments.get("schema_digest"),
                            "params": {
                                key: value
                                for key, value in arguments.items()
                                if key not in {"call_id", "schema_digest"}
                            },
                        }
                    return self._execute(binding, arguments)
            raise XiaoxBindingError("unknown_tool", "工具不属于当前运行接口")

    @staticmethod
    def authorized_action_spec(binding: XiaoxBinding, args: dict[str, Any]) -> ToolActionSpecV2:
        """Resolve the same live actor contract for discovery, plan review and execution."""
        from app.application.capability_catalog import authorized_tool_specs

        spec = get_tool_action_spec(str(args.get("tool_id") or ""), str(args.get("action") or ""))
        if spec is not None:
            action_key = (spec.tool_id, spec.action)
            spec = authorized_tool_specs(
                binding.context, include_aiopen=True, specs={action_key: spec}
            ).get(action_key)
        if spec is None or not XiaoxToolBridge._allowed(spec, binding, args.get("params")):
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
            self.authorized_action_spec(binding, call)
        receipt = read_call_receipt(self.store, binding, call)
        saved = self.store.record_call(
            binding.run_id, call_id, child_run_id=receipt.get("run_id", ""), receipt=receipt
        )
        return dict(saved.metadata["calls"][call_id]["receipt"])

    @staticmethod
    def action_parameters(args: dict[str, Any]) -> dict[str, Any]:
        """Reject caller-supplied authority on both proposed and executable actions."""
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
        return params

    def _execute(self, binding: XiaoxBinding, args: dict[str, Any]) -> dict[str, Any]:
        params = self.action_parameters(args)
        spec = self.authorized_action_spec(binding, args)
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        from app.domain.task_lifecycle.execution_mode import CONTEXT_KEY, deny_reason

        blocked = deny_reason(
            binding.context.get(CONTEXT_KEY),
            spec.tool_id,
            spec.action,
            params,
            lookup_spec=get_tool_action_spec,
        )
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
        violation = action_schema_violation(spec, params)
        if not validation.ok or violation:
            error_code = validation.error_code or "schema_validation_failed"
            return {
                "success": False,
                "verified": False,
                "status": "not_started",
                "error_code": error_code,
                "message": (
                    "参数未通过校验，请按当前 input_schema 修正。"
                    if error_code == "schema_validation_failed"
                    else validation.message
                ),
                **({"schema_violation": violation} if violation else {}),
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
        if not isinstance(call_id, str) or not call_id.strip() or len(call_id) > 160:
            raise XiaoxBindingError("invalid_call", "工具调用标识无效")
        safe_read = spec.is_read_only_call(params) and spec.risk == "low"
        review, approval_preview = {}, ""
        isolated_artifact = False
        if (spec.tool_id, spec.action) == ("employee", "execute"):
            from app.application.agent_orchestrator.verification_workbook import (
                WorkbookFormulaSyntaxError,
                WorkbookPlanError,
                review_workbook_write,
                scoped_workbook_employee,
                trusted_workbook_reader,
            )

            workbook_employee = scoped_workbook_employee(params)
            if workbook_employee == WORKBOOK_READER:
                isolated_artifact = trusted_workbook_reader(params)
                # The signed reader only inspects the caller-owned upload; it
                # creates no business write and needs no write approval card.
                safe_read = isolated_artifact
            fingerprint = canonical_digest(
                {"tool_id": spec.tool_id, "action": spec.action, "params": params}
            )
            if workbook_employee == WORKBOOK_WRITER and not any(
                call.get("fingerprint") == fingerprint
                for call in binding.metadata.get("calls", {}).values()
            ):
                context = self._child_context(binding, {"child_task_id": ""})
                try:
                    reviewed, changes = review_workbook_write(params, context)
                except WorkbookFormulaSyntaxError as exc:
                    return {
                        "success": False,
                        "verified": False,
                        "status": "not_started",
                        "error_code": "workbook_formula_syntax_invalid",
                        "field_path": exc.field_path,
                        "message": "工作簿公式未通过语法校验；请修正指定写入项后重试。",
                    }
                except WorkbookPlanError as exc:
                    return {
                        "success": False,
                        "verified": False,
                        "status": "not_started",
                        "error_code": "workbook_plan_invalid",
                        "message": str(exc),
                    }
                except (OSError, ValueError):
                    return {
                        "success": False,
                        "verified": False,
                        "status": "not_started",
                        "error_code": "workbook_plan_review_failed",
                        "message": "无法在原工作簿中核验这份计划。请检查附件和相应工作表范围。",
                    }
                review[WORKBOOK_WRITE_REVIEW] = reviewed
                isolated_artifact = True
                if changes and str(context.get("chat_approval_mode") or "").strip() == "auto":
                    return {
                        "success": False,
                        "verified": False,
                        "status": "not_started",
                        "error_code": "workbook_manual_approval_required",
                        "message": "计划会修改原始数据。请保留这些原值，或由用户切换到手动审批后核对变更。",
                        "required_approval": "manual",
                        "change_count": len(changes),
                        "changes": [
                            {key: change[key] for key in ("sheet", "ref", "source_ref", "kind")}
                            for change in changes[:20]
                        ],
                    }
                if changes:
                    approval_preview = "确认工作簿数据修改\n" + "\n".join(
                        f"{change['sheet']} · {change['ref']}  "
                        f"{json.dumps(change['before'][1], ensure_ascii=False, default=str)} → "
                        f"{json.dumps(change['after'][1], ensure_ascii=False, default=str)}"
                        for change in changes
                    )
        call, created = self.store.claim_call(
            binding.run_id,
            call_id,
            tool_id=spec.tool_id,
            action=spec.action,
            params=params,
            read_only=safe_read,
            generation=binding.metadata["generation"],
            cost_units=spec.cost_units,
            isolated_artifact=isolated_artifact,
        )
        if not created:
            return self._evidence(self.store.get(binding.run_id), call_id)
        context = self._child_context(binding, call)
        context.update(review)
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
                approval_preview=approval_preview,
            ).run
        # The child id is durable before dispatch. A lost response can only read
        # this task; it cannot mint a new approved operation and execute twice.
        self.store.record_call(binding.run_id, call_id, child_run_id=child.run_id)
        try:
            self.store.check_current(binding.run_id, generation=binding.metadata["generation"])
            self._check_schema(self.authorized_action_spec(binding, args), args)
            self._check_gate(binding, spec, params)
        except XiaoxBindingError:
            self.orchestrator.cancel_run(child.run_id, requested_by=binding.run.user_id)
            raise
        if child.status in {"queued", "running"}:
            # 只读子任务必须派发；自动审批模式下的写子任务也不再停在审批断点。
            try:
                self.orchestrator.execute_dispatched_run(child.run_id)
            except Exception:
                logger.exception("Xiaox child dispatch failed: %s", child.run_id)
                # Reuse the orchestrator's durable failure transition. A started
                # effect remains blocked for reconciliation; an untouched read
                # can fail without stranding the parent's call reservation.
                self.orchestrator.fail_dispatched_run(child.run_id, open_effects=not safe_read)
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
        context.pop("desktop_navigation", None)
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
            "_tool_approval_scope",
            WORKBOOK_WRITE_REVIEW,
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


def mcp_tool_definitions(
    visible_actions: Iterable[tuple[str, str]] | None = None,
) -> list[Tool]:
    """Use MCP SDK types; schema is glue around the existing capability catalog."""
    from mcp.types import Tool

    fields = {"tool_id": {"type": "string"}, "action": {"type": "string"}}
    visible = list(visible_actions) if visible_actions is not None else None
    if visible:
        # Keep the schema linear in catalog size. The bridge enforces valid pairs
        # and current permission on every call.
        fields = {
            "tool_id": {"type": "string", "enum": sorted({tool_id for tool_id, _ in visible})},
            "action": {"type": "string", "enum": sorted({action for _, action in visible})},
        }
    definitions = [
        (
            "capability_search",
            "检索当前账号获授权的企业工具，以及本轮桌面提供的可见页面和手动操作入口。query 留空可分页浏览。",
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
    tools = [
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
        if name not in {"execute_employee", *DIRECT_ACTION_TOOLS}
        if visible != [] or name not in {"capability_describe", "execute_action"}
        for description, props, required in [definitions_by_name[name]]
    ]
    if visible is None or ("employee", "execute") in visible:
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        employee = get_tool_action_spec("employee", "execute")
        if employee is not None:
            action = next(tool for tool in tools if tool.name == "execute_action")
            action.input_schema["allOf"] = [
                {
                    "if": {
                        "required": ["tool_id", "action"],
                        "properties": {
                            "tool_id": {"const": "employee"},
                            "action": {"const": "execute"},
                        },
                    },
                    "then": {"properties": {"params": employee.input_schema}},
                }
            ]
            direct_schema = copy.deepcopy(employee.input_schema)
            direct_schema["properties"].update(
                {
                    "call_id": {"type": "string", "minLength": 1, "maxLength": 160},
                    "schema_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                }
            )
            direct_schema["required"] = [
                *direct_schema.get("required", []),
                "call_id",
                "schema_digest",
            ]
            tools.append(
                Tool(
                    name="execute_employee",
                    description=(
                        "直接执行已授权 AI 员工。参数使用 employee.execute 的原生对象契约；"
                        "先从 capability_describe 读取 schema_digest。写入仍走原审批与独立质检。"
                    ),
                    inputSchema=direct_schema,
                )
            )
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    for name, (tool_id, action_name) in DIRECT_ACTION_TOOLS.items():
        if visible is not None and (tool_id, action_name) not in visible:
            continue
        spec = get_tool_action_spec(tool_id, action_name)
        if spec is None:
            continue
        generic = next(tool for tool in tools if tool.name == "execute_action")
        generic.input_schema.setdefault("allOf", []).append(
            {
                "if": {
                    "required": ["tool_id", "action"],
                    "properties": {"tool_id": {"const": tool_id}, "action": {"const": action_name}},
                },
                "then": {"properties": {"params": spec.input_schema}},
            }
        )
        direct_schema = copy.deepcopy(spec.input_schema)
        direct_schema["properties"].update(
            {
                "call_id": {"type": "string", "minLength": 1, "maxLength": 160},
                "schema_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            }
        )
        direct_schema["required"] = [
            *direct_schema.get("required", []),
            "call_id",
            "schema_digest",
        ]
        tools.append(
            Tool(
                name=name,
                description=f"执行已授权的 {tool_id}.{action_name}；参数直接使用原能力契约，先读取 schema_digest。",
                inputSchema=direct_schema,
            )
        )
    return tools
