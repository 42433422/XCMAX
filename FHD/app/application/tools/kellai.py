"""Kellai tools use the existing Agent approval, account and channel boundaries."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode

from app.application import kellai_binding_app_service as binding
from app.application.kellai_binding_app_service import request_kellai
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
from app.infrastructure.kellai_client import KellaiRequestError


def delivery_request_id(run_id: str, step_id: str) -> str:
    """Stable original action identity; this grants no permission to send."""
    return "agent_" + hashlib.sha256(f"{run_id}:{step_id}".encode()).hexdigest()[:48]


def _approved_request_id(
    params: dict[str, Any],
    context: dict[str, Any],
    connection: dict[str, Any] | None = None,
) -> str:
    """Revalidate the persisted approved action, never model-supplied approval flags."""
    from app.application.agent_orchestrator.approval_grant import _params_hash
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    run = get_agent_run_repository().get(str(context.get("run_id") or ""))
    if run is None or run.user_id != str(context.get("user_id") or ""):
        raise PermissionError("发送需要当前账号的已批准任务")
    stored_context = run.metadata.get("runtime_context") or {}
    step = next((item for item in run.steps if item.step_id == context.get("step_id")), None)
    receipt = run.metadata.get("approval_receipt") or {}
    connection_digest = binding.connection_identity_sha256(connection)
    if (
        run.status not in {"running", "queued", "retrying"}
        or str(stored_context.get("tenant_id") or "") != str(context.get("tenant_id") or "")
        or step is None
        or (step.tool_id, step.action, step.params) != ("kellai", "send", params)
        or (receipt.get("step_id"), receipt.get("tool_id"), receipt.get("action"))
        != (step.step_id, "kellai", "send")
        or not receipt.get("approved_by")
        or not connection_digest
        or receipt.get("kellai_connection_sha256") != connection_digest
    ):
        raise PermissionError("发送内容或收件人与已批准任务不一致")
    if receipt.get("grant_id"):
        from app.db import HostSessionLocal
        from app.db.models.agent_approval import AgentApprovalConsumption

        with HostSessionLocal() as db:
            consumption = db.get(AgentApprovalConsumption, receipt["grant_id"])
            if (
                consumption is None
                or consumption.run_id != run.run_id
                or consumption.step_id != step.step_id
                or receipt.get("params_sha256") != _params_hash(step)
            ):
                raise PermissionError("发送审批凭据无效")
    elif receipt.get("approval_request_id"):
        from app.application.workflow.approval_persistence import (
            load_workflow_snapshot_for_execution,
        )
        from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict

        snapshot = load_workflow_snapshot_for_execution(receipt["approval_request_id"])
        approved = plan_from_dict(snapshot.get("plan")) if snapshot else None
        plan = plan_from_dict(run.metadata.get("plan"))
        node = (
            next((item for item in plan.nodes if item.node_id == step.node_id), None)
            if plan
            else None
        )
        if (
            not snapshot
            or snapshot.get("agent_run_id") != run.run_id
            or snapshot.get("approved_step_id") not in {step.step_id, step.node_id}
            or approved is None
            or plan is None
            or plan_fingerprint(approved) != plan_fingerprint(plan)
            or receipt.get("plan_sha256") != plan_fingerprint(plan)
            or node is None
            or (node.tool_id, node.action, node.params) != ("kellai", "send", params)
        ):
            raise PermissionError("发送审批计划已变化")
    else:
        raise PermissionError("缺少发送审批凭据")
    return delivery_request_id(run.run_id, step.step_id)


def execute_kellai(action: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_spec import validate_tool_call

    validation = validate_tool_call("kellai", action, params)
    if not validation.ok:
        return {
            "success": False,
            "error_code": validation.error_code,
            "message": validation.message,
        }
    request_id = ""
    try:
        actor = _bound_actor(context)
        scope = {
            "channels": "channels.read",
            "contacts": "messages.read",
            "messages": "messages.read",
            "send": "messages.send",
            "receipt": "messages.send",
        }[action]
        connection = binding.scoped_connection(
            actor=int(actor.id), tenant_id=str(context.get("tenant_id") or ""), scope=scope
        )
        body = None
        if action == "send":
            request_id = _approved_request_id(params, context, connection)
            body = {**params, "client_request_id": request_id}
            path = "messages/send"
        elif action == "receipt":
            path = f"messages/requests/{params['client_request_id']}"
        elif action == "messages":
            query = urlencode(
                {"connection_id": params["connection_id"], "limit": params.get("limit", 30)}
            )
            path = f"contacts/{params['customer_id']}/messages?{query}"
        elif action == "contacts":
            path = f"contacts?limit={params.get('limit', 50)}"
        else:
            path = "channels"
        result = request_kellai(path, connection, body)
        if action in {"send", "receipt"}:
            data = result.get("data") or {}
            status = str(data.get("status"))
            provider_state = data.get("provider_state")
            visible_status = (
                provider_state
                if status == "accepted"
                and isinstance(provider_state, str)
                and provider_state in {"sent", "delivered", "read", "failed"}
                else status
            )
            return {
                "success": status in {"accepted", "delivered"} and visible_status != "failed",
                # Provider acceptance/delivery is a domain receipt, not an
                # execution envelope. Keep the full original receipt for the
                # host's independent readback; acceptance alone cannot pass it.
                "data": {"request_id": data.get("request_id"), "delivery_receipt": data},
                "message": {
                    "accepted": "渠道已受理，尚无送达确认",
                    "sent": "渠道已发送，尚无送达确认",
                    "delivered": "渠道确认送达",
                    "read": "渠道确认已读",
                    "failed": "渠道确认发送失败",
                    "requires_desktop_execution": "此渠道需要在客来来桌面端执行，当前请求未外发",
                }.get(visible_status, f"渠道状态：{status}"),
                "retryable": False,
                **(
                    {"outcome": "unknown", "reconciliation_required": True}
                    if status in {"sending", "unknown"}
                    else {}
                ),
            }
        return result
    except AgentModAuthorizationError:
        return {
            "success": False,
            "error_code": "tool_identity_required",
            "message": "客来来工具需要当前账号的有效登录绑定",
        }
    except binding.KellaiAuthorizationError as exc:
        return {"success": False, "error_code": "kellai_scope_required", "message": str(exc)}
    except PermissionError as exc:
        return {"success": False, "error_code": "approval_required", "message": str(exc)}
    except KellaiRequestError as exc:
        return {
            "success": False,
            "error_code": "kellai_unavailable",
            "message": str(exc),
            "retryable": False,
            **(
                {
                    "outcome": "unknown",
                    "reconciliation_required": True,
                    "data": {
                        "request_id": request_id,
                        "delivery_receipt": {"request_id": request_id, "status": "unknown"},
                    },
                }
                if request_id
                else {}
            ),
        }
