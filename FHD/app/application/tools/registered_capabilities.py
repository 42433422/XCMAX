"""Model-facing ERP capabilities from the approval-gated workflow registry."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

from app.application.workflow.workflow_types import normalize_workflow_risk
from app.utils.json_safe import json_safe
from app.utils.operational_errors import RECOVERABLE_ERRORS

ERP_CAPABILITY_TOOL_NAME = "execute_erp_capability"
logger = logging.getLogger(__name__)


def _workflow_registry() -> dict[str, Any]:
    from resources.config.risk_actions_loader import get_workflow_tools_from_registry

    registry = get_workflow_tools_from_registry()
    return registry if isinstance(registry, dict) else {}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return bool(value)
    return True


def _capability_catalog_lines(registry: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for tool_id in sorted(registry):
        tool = registry.get(tool_id)
        tool_data: dict[str, Any] = tool if isinstance(tool, dict) else {}
        actions = tool_data.get("actions")
        if not isinstance(actions, dict):
            continue
        action_bits = []
        for action, spec in sorted(actions.items()):
            risk = str((spec or {}).get("risk") or "low").lower()
            action_bits.append(f"{action}({risk})")
        description = str(tool_data.get("description") or "").strip()
        suffix = f" — {description}" if description else ""
        lines.append(f"{tool_id}: {', '.join(action_bits)}{suffix}")
    return lines


def registered_capability_catalog() -> dict[str, Any]:
    """Return a compact, model-safe view of every registered product capability."""

    registry = _workflow_registry()
    capabilities: list[dict[str, Any]] = []
    for tool_id in sorted(registry):
        tool = registry.get(tool_id)
        tool_data: dict[str, Any] = tool if isinstance(tool, dict) else {}
        actions = tool_data.get("actions")
        if not isinstance(actions, dict):
            continue
        capabilities.append(
            {
                "tool_id": tool_id,
                "description": str(tool_data.get("description") or ""),
                "actions": {
                    str(action): {
                        "risk": str((spec or {}).get("risk") or "low").lower(),
                        "required_params": list((spec or {}).get("required_params") or []),
                        "idempotent": bool((spec or {}).get("idempotent", False)),
                    }
                    for action, spec in sorted(actions.items())
                    if isinstance(spec, dict)
                },
            }
        )
    return {
        "capability_count": len(capabilities),
        "capability_ids": [row["tool_id"] for row in capabilities],
        "capabilities": capabilities,
    }


def build_registered_capability_tool_definition() -> dict[str, Any]:
    """Build the single model tool which covers all registered ERP functions."""

    registry = _workflow_registry()
    catalog = _capability_catalog_lines(registry)
    catalog_text = "\n".join(catalog)
    return {
        "type": "function",
        "function": {
            "name": ERP_CAPABILITY_TOOL_NAME,
            "description": (
                "执行已登记的 ERP 产品能力。只能使用下方 capability catalog 中的 "
                "tool_id 与 action；params 必须只包含该动作需要的业务参数。低风险动作会执行，"
                "中高风险动作会沿用产品审批流；不得把内部 HTTP、账号鉴权、权限管理或系统密钥 "
                "当作 capability 调用。调用前要确认用户意图，执行后依据返回的 success 与 approval "
                "结果如实回复。\n\nCapability catalog:\n"
                f"{catalog_text}"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_id": {
                        "type": "string",
                        "enum": sorted(registry),
                        "description": "ERP 产品能力 ID。",
                    },
                    "action": {
                        "type": "string",
                        "description": "所选 tool_id 支持的动作；精确名称见 capability catalog。",
                    },
                    "params": {
                        "type": "object",
                        "description": "该动作的业务参数。不会接受 _runtime_context 或鉴权注入字段。",
                        "additionalProperties": True,
                    },
                },
                "required": ["tool_id", "action"],
            },
        },
    }


def extend_workflow_tool_registry(
    registry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Append the product capability tool without making a second hard-coded catalog."""

    try:
        return [*registry, build_registered_capability_tool_definition()]
    except RECOVERABLE_ERRORS:
        return registry


def resolve_registered_capability_call(args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize one model tool call against the SSOT registry."""

    payload = dict(args or {})
    tool_id = str(payload.get("tool_id") or payload.get("capability_id") or "").strip()
    params = payload.get("params")
    if not isinstance(params, dict):
        return {"success": False, "error": "params 必须是 JSON 对象"}
    params = dict(params)
    # Runtime context and authorization are injected only by the host workflow,
    # never accepted from a model-generated tool argument.
    params.pop("_runtime_context", None)
    registry = _workflow_registry()
    tool = registry.get(tool_id)
    if not isinstance(tool, dict):
        return {
            "success": False,
            "error": f"未登记的 ERP capability: {tool_id or '(empty)'}",
            "available_tool_ids": sorted(registry),
        }

    from app.services.tools_execution.registry import _normalize_action

    action = _normalize_action(str(payload.get("action") or ""), params)
    actions = tool.get("actions")
    spec = actions.get(action) if isinstance(actions, dict) else None
    if not isinstance(spec, dict):
        return {
            "success": False,
            "error": f"未登记的 capability action: {tool_id}.{action or '(empty)'}",
            "available_actions": sorted(actions) if isinstance(actions, dict) else [],
        }
    required = [str(key) for key in spec.get("required_params") or [] if str(key)]
    missing = [key for key in required if not _has_value(params.get(key))]
    if missing:
        return {
            "success": False,
            "error": f"缺少参数：{', '.join(missing)}",
            "tool_id": tool_id,
            "action": action,
            "required_params": required,
        }
    if (tool_id, action) == ("inventory", "stock_in"):
        from app.domain.app_pure.inventory_inputs import validate_stock_in_request

        try:
            validate_stock_in_request(params)
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "tool_id": tool_id,
                "action": action,
            }
    if tool_id == "sales" and action in {"quote", "create_order"}:
        from app.application.sales_quote_inputs import validated_quote_request

        try:
            validated_quote_request(params)
        except ValueError as exc:
            return {
                "success": False,
                "error": str(exc),
                "tool_id": tool_id,
                "action": action,
            }
    return {
        "success": True,
        "tool_id": tool_id,
        "action": action,
        "params": params,
        "risk": str(spec.get("risk") or "low").lower(),
        "idempotent": bool(spec.get("idempotent", False)),
        "required_params": required,
        "description": str(tool.get("description") or ""),
    }


def execute_registered_capability(
    args: dict[str, Any] | None,
    *,
    workspace_root: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    require_approval: bool = False,
) -> str:
    """Execute a registered product operation through risk and approval gates."""

    resolved = resolve_registered_capability_call(args)
    if not resolved.get("success"):
        return json.dumps(resolved, ensure_ascii=False)

    from app.application.agent_orchestrator.tool_permission import actor_tool_denial
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    tool_id = str(resolved["tool_id"])
    action = str(resolved["action"])
    params = dict(resolved["params"])
    context: dict[str, Any] = dict(runtime_context or {})
    if denial := actor_tool_denial(tool_id, action, context, params):
        return json.dumps(denial, ensure_ascii=False, default=json_safe)
    key = str(context.get("idempotency_key") or context.get("turn_id") or "").strip()
    call_id = str(context.get("call_id") or "").strip()
    session_id = str(context.get("conversation_id") or context.get("session_id") or "").strip()
    if (
        not key
        and call_id
        and (session_id or context.get("parent_run_id") or context.get("run_id"))
    ):
        key = call_id
    stable_request = bool(key)
    spec = get_tool_action_spec(tool_id, action)
    if not key:
        if not spec or not (spec.read_only or spec.risk == "low" and spec.idempotent):
            return json.dumps(
                {
                    "success": False,
                    "execution_state": "blocked",
                    "retryable": False,
                    "error_code": "task_identity_required",
                    "message": "写操作需要稳定的 turn_id 或 idempotency_key，尚未执行。",
                },
                ensure_ascii=False,
            )
        key = uuid.uuid4().hex
    legacy_approval_request_id = ""
    if tool_id in {"customers", "products"} and action == "batch_delete":
        from app.infrastructure.auth.agent_mod_scope import _bound_actor
        from app.infrastructure.tenant_scope import current_tenant_id

        try:
            actor = _bound_actor(context)
            tenant = current_tenant_id()
            if (
                not tenant
                or str(tenant) != str(context.get("tenant_id"))
                or not key
                or actor_tool_denial(tool_id, action, context) is not None
            ):
                raise ValueError("删除操作缺少有效身份、权限或请求标识")
            identity = json.dumps([tenant, str(actor.id), key, tool_id, action], ensure_ascii=False)
            legacy_approval_request_id = hashlib.sha256(identity.encode()).hexdigest()
        except RECOVERABLE_ERRORS:
            return json.dumps(
                {"success": False, "error": "删除操作身份或请求标识无效"},
                ensure_ascii=False,
            )
    actor_id = str(
        context.get("user_id") or context.get("local_user_id") or context.get("actor_id") or ""
    ).strip()
    if not actor_id:
        return json.dumps(
            {
                "success": False,
                "error": "ERP capability 缺少已认证的调用人上下文，未执行",
                "error_code": "tool_identity_required",
                "execution_status": "not_started",
                "retryable": False,
                "tool_id": tool_id,
                "action": action,
            },
            ensure_ascii=False,
        )
    identity = json.dumps(
        [
            str(context.get("tenant_id") or ""),
            actor_id,
            session_id or str(context.get("parent_run_id") or context.get("run_id") or ""),
            key,
            call_id,
        ],
        ensure_ascii=False,
    )
    digest = hashlib.sha256(identity.encode()).hexdigest()
    task_id = f"task_erp_{digest[:40]}"
    parent_task = str(context.get("task_id") or "")
    if parent_task and parent_task != task_id:
        context.setdefault("parent_task_id", parent_task)
    if context.get("agent_run_id") or context.get("run_id"):
        context.setdefault("parent_run_id", str(context.get("agent_run_id") or context["run_id"]))
    context["task_id"] = task_id
    approval_request_id = hashlib.sha256(f"{task_id}:approval".encode()).hexdigest()
    plan_id = f"erp-capability-{digest}"
    plan = PlanGraph(
        plan_id=plan_id,
        intent=f"ERP Agent 请求执行 {tool_id}.{action}",
        todo_steps=[f"执行已登记产品能力 {tool_id}.{action}"],
        nodes=[
            WorkflowNode(
                node_id="registered_capability",
                tool_id=tool_id,
                action=action,
                params=params,
                risk=normalize_workflow_risk(str(resolved["risk"])),
                idempotent=bool(resolved["idempotent"]),
                description=str(resolved["description"]),
            )
        ],
        risk_level=normalize_workflow_risk(str(resolved["risk"])),
        metadata={"source": "erp_agent_capability_tool"},
    )
    # 合并调用方（已认证会话）传入的上下文，而不是凭空重建，否则审批申请人无法解析。
    # 安全约束：申请人标识只能来自调用方会话；params 由模型产生，
    # 因此**不得**从 params 读取 local_user_id / actor_id / user_id。
    context["source"] = "erp_agent_capability_tool"
    context["workspace_root"] = workspace_root
    context.setdefault("message", str(params.get("user_request") or params.get("message") or ""))
    from app.application.agent_orchestrator.unified_task import (
        UnifiedTaskConflictError,
        UnifiedTaskResult,
        publish_task_run,
    )

    try:
        from app.application.agent_orchestrator import AgentOrchestrator
        from app.application.workflow import get_approval_service

        approvals = get_approval_service()
        required_nodes = approvals.get_approval_required_nodes(plan)
        required_ids = [node.node_id for node in required_nodes]
        if require_approval:
            required_ids = [node.node_id for node in plan.nodes]
        if required_ids:
            plan.metadata["approval_required_node_ids"] = required_ids
        orchestrator = AgentOrchestrator()
        legacy_run = None
        if legacy_approval_request_id:
            from app.application.workflow.approval_persistence import load_legacy_capability_run

            legacy_found, legacy_run = load_legacy_capability_run(
                legacy_approval_request_id,
                read_run=orchestrator.get_run,
                user_id=actor_id,
                runtime_context=context,
                tool_id=tool_id,
                action=action,
                params=params,
            )
            if legacy_found and legacy_run is None:
                return json.dumps(
                    {
                        "success": False,
                        "execution_state": "unknown",
                        "requires_reconciliation": True,
                        "retryable": False,
                        "error_code": "legacy_approval_identity_unverified",
                        "approval_request_id": legacy_approval_request_id,
                        "message": "旧审批的执行身份尚未完整确认，请核对原审批；未创建或执行新任务。",
                    },
                    ensure_ascii=False,
                )
        if legacy_run is not None:
            publication = UnifiedTaskResult(run=legacy_run, deduplicated=True)
        else:
            options: dict[str, Any] = {
                "user_id": actor_id,
                "message": str(context.get("message") or ""),
                "plan": plan,
                "runtime_context": context,
                "persist": False,
            }
            agent_run = (
                orchestrator.start_task_from_plan(**options)
                if require_approval
                else orchestrator.start_run_from_plan(**options, auto_execute=False)
            )
            if required_ids:
                # Publish the approval identity with the winning run, before dispatch.
                agent_run.metadata["approval_request_id"] = approval_request_id
            publication = publish_task_run(
                orchestrator=orchestrator,
                run=agent_run,
                tool_id=tool_id,
                action=action,
                params=params,
                risk=str(resolved["risk"]),
                idempotent=bool(resolved["idempotent"]),
                runtime_context=context,
            )
        agent_run = publication.run
    except UnifiedTaskConflictError:
        return json.dumps(
            {
                "success": False,
                "execution_state": "blocked",
                "retryable": False,
                "error_code": "task_idempotency_conflict",
                "message": "原任务标识已绑定其他参数或 Mod 范围，未再次执行。",
            },
            ensure_ascii=False,
        )
    except RECOVERABLE_ERRORS:
        return json.dumps(
            {
                "success": False,
                "error": "ERP capability 执行被中断，请核对原调用结果",
                "error_code": "capability_execution_interrupted",
                "outcome": "unknown",
                "execution_state": "unknown",
                "retryable": False,
                "reconciliation_required": True,
                "tool_id": tool_id,
                "action": action,
            },
            ensure_ascii=False,
        )

    capability = {
        key: resolved[key] for key in ("tool_id", "action", "risk", "idempotent", "required_params")
    }
    response = {
        "success": False,
        "capability": capability,
        "agent_run_id": agent_run.run_id,
        "run_id": agent_run.run_id,
        "task_id": (agent_run.metadata.get("task_context") or {}).get("task_id"),
        "deduplicated": publication.deduplicated,
        "retryable": False,
    }
    if legacy_run is not None:
        response["approval_request_id"] = legacy_approval_request_id
    if not publication.deduplicated and not require_approval:
        try:
            agent_run = orchestrator.execute_dispatched_run(agent_run.run_id) or agent_run
        except RECOVERABLE_ERRORS:
            try:
                orchestrator.fail_dispatched_run(agent_run.run_id)
            except RECOVERABLE_ERRORS:
                logger.exception(
                    "capability reconciliation was not persisted run=%s", agent_run.run_id
                )
                response["reconciliation_persistence"] = "unavailable"
            response.update(
                execution_state="unknown",
                requires_reconciliation=True,
                message="执行回执尚未确认，请查询原任务，勿重复提交。",
            )
            return json.dumps(response, ensure_ascii=False, default=json_safe)
    from app.application.agent_orchestrator.trace_payloads import _payload_status
    from app.application.workflow.workflow_types import plan_from_dict
    from app.domain.task_lifecycle.results import execution_result_pending_state

    plan = plan_from_dict(agent_run.metadata.get("plan")) or plan
    required_ids = list((plan.metadata or {}).get("approval_required_node_ids") or [])
    outputs = {
        "agent_status": agent_run.status,
        "output": agent_run.final_output,
        "outputs": [step.output for step in agent_run.steps],
        "requires_reconciliation": (agent_run.metadata.get("recovery") or {}).get("state")
        == "manual_reconciliation_required",
    }
    state = execution_result_pending_state(outputs) or _payload_status(outputs)
    if (
        state != "unknown"
        and agent_run.status == "waiting_user"
        and any(
            step.status == "waiting_user" and step.node_id in required_ids
            for step in agent_run.steps
        )
    ):
        state = "waiting_approval"
    response.update(
        execution_state=state,
        success=state == "completed",
        plan_id=agent_run.plan_id,
        execution_accepted=state not in {"completed", "failed", "cancelled", "rejected"},
    )
    if state == "unknown":
        response.update(requires_reconciliation=True, message="执行结果尚未确认，请查询原任务。")
    if not stable_request:
        response["idempotency_scope"] = "original_task_only"
    if agent_run.status == "waiting_user" and state != "unknown":
        waiting = next((step for step in agent_run.steps if step.status == "waiting_user"), None)
        if waiting and waiting.node_id in required_ids:
            node = next((item for item in plan.nodes if item.node_id == waiting.node_id), None)
            request_id = ""
            try:
                if node is None or (node.tool_id, node.action, node.params) != (
                    waiting.tool_id,
                    waiting.action,
                    waiting.params,
                ):
                    raise RuntimeError("审批节点与完整计划不一致")
                if publication.deduplicated:
                    from app.application.workflow.approval_persistence import (
                        find_pending_approval_for_run,
                    )

                    request_id = find_pending_approval_for_run(
                        agent_run,
                        approved_step_id=waiting.node_id,
                        request_ids=(approval_request_id, legacy_approval_request_id),
                    )
                    if not request_id:
                        raise RuntimeError("原审批回执尚未确认")
                else:
                    request_id = str(agent_run.metadata.get("approval_request_id") or "")
                    if not request_id:
                        raise RuntimeError("原任务未绑定审批请求标识")
                    request = approvals.create_approval_request(
                        plan_id=plan.plan_id,
                        node=node,
                        runtime_context={**context, "_approval_agent_run_required": True},
                        plan=plan,
                        require_persistence=True,
                        request_id=request_id,
                    )
                    request_id = str(request.request_id or "").strip()
                    if not request_id or not approvals.attach_pending_agent_run(
                        request_id, agent_run_id=agent_run.run_id, approved_step_id=waiting.node_id
                    ):
                        raise RuntimeError("AgentRun 未关联到审批请求")
            except RECOVERABLE_ERRORS:
                response.update(
                    message="ERP 操作已暂停，但审批请求未能安全保存；未执行等待审批的步骤。",
                    run_status=agent_run.status,
                    execution_state="unknown",
                    execution_accepted=False,
                    requires_reconciliation=True,
                )
            else:
                response.update(
                    execution_state="waiting_approval",
                    pending_approval=True,
                    approval_request_id=request_id,
                    message="该 ERP 操作已创建审批请求，审批前不会执行。",
                )
        else:
            response.update(
                requires_confirmation=True,
                message="该 ERP 操作已在 AgentRun 中安全暂停，等待确认后继续。",
                run_status=agent_run.status,
            )
    else:
        from app.domain.task_lifecycle.results import (
            agent_node_output,
            execution_result_requires_reconciliation,
        )

        output = agent_node_output(agent_run, "registered_capability")
        response.update(
            success=state == "completed" and output.get("success") is True,
            message=str(output.get("message") or agent_run.error or "该 ERP 操作未完成。"),
            run_status=agent_run.status,
            result=output,
        )
        for key in (
            "outcome",
            "execution_status",
            "retryable",
            "reconciliation_required",
            "error_code",
        ):
            if key in output:
                response[key] = output[key]
        if execution_result_requires_reconciliation(output):
            response.update(
                success=False,
                outcome="unknown",
                retryable=False,
                reconciliation_required=True,
            )
    return json.dumps(response, ensure_ascii=False, default=json_safe)


__all__ = [
    "ERP_CAPABILITY_TOOL_NAME",
    "build_registered_capability_tool_definition",
    "execute_registered_capability",
    "extend_workflow_tool_registry",
    "registered_capability_catalog",
    "resolve_registered_capability_call",
]
