"""Account-scoped Kellai adapter; business contracts live in the common registry.

Adapted from XCMAX #3435 (fcd6fb230db2); provider contract: kellai #2 (8cf46e8).
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.application import kellai_binding_app_service as binding
from app.infrastructure.auth.agent_mod_scope import AgentModAuthorizationError, _bound_actor
from app.infrastructure.kellai_client import KellaiRequestError, request_kellai


class KellaiReceiptPending(RuntimeError):
    pass


def _connection(context: dict[str, Any], action: str) -> dict[str, Any]:
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

    actor = _bound_actor(context)
    spec = get_tool_action_spec("kellai", action)
    scope = str((spec.policy if spec else {}).get("provider_scope") or "")
    if not scope:
        raise binding.KellaiAuthorizationError("客来来能力未登记")
    return binding.scoped_connection(
        actor=int(actor.id), tenant_id=str(context.get("tenant_id") or ""), scope=scope
    )


def connection_scope(context: dict[str, Any], action: str) -> dict[str, Any]:
    """Stable approval identity, with no credential or provider endpoint disclosure."""
    try:
        connection = _connection(context, action)
    except (AgentModAuthorizationError, binding.KellaiAuthorizationError):
        return {"available": False}
    return {
        "available": True,
        "connection_id": str(connection["connection_id"]),
        "user_id": str(connection["xcmax_user_id"]),
        "tenant_id": str(connection.get("xcmax_tenant_id") or ""),
        "provider_actor_id": str((connection.get("authorized_by") or {}).get("id") or ""),
        "scopes": sorted(connection.get("authorized_scopes") or []),
    }


def _request_id(context: dict[str, Any]) -> str:
    if not context.get("run_id") or not context.get("step_id"):
        raise PermissionError("发送需要原始任务和步骤标识")
    return (
        "agent_"
        + hashlib.sha256(f"{context['run_id']}:{context['step_id']}".encode()).hexdigest()[:48]
    )


def _approved_request_id(params: dict[str, Any], context: dict[str, Any]) -> str:
    from app.application.agent_orchestrator.approval_grant import (
        approval_scope_matches,
        execution_scope_claims,
    )
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository

    run = get_agent_run_repository().get(str(context.get("run_id") or ""))
    step = (
        next((s for s in run.steps if s.step_id == context.get("step_id")), None) if run else None
    )
    receipt = (run.metadata.get("approval_receipt") or {}) if run else {}
    if (
        run is None
        or step is None
        or run.user_id != str(context.get("user_id") or "")
        or run.status not in {"running", "queued", "retrying"}
        or (step.tool_id, step.action, step.params) != ("kellai", "send", params)
        or not receipt.get("approved_by")
        or not approval_scope_matches(run, step)
        or any(
            receipt.get(key) != value
            for key, value in execution_scope_claims(context, "kellai", "send").items()
        )
    ):
        raise PermissionError("发送需要当前账号、渠道绑定、收件人和内容一致的已批准任务")
    return _request_id(context)


def verify_kellai_receipt(
    params: dict[str, Any], context: dict[str, Any], output: dict[str, Any]
) -> dict[str, Any]:
    """Independent GETs only: match delivery and the original persisted message."""
    from app.application.agent_orchestrator.business_action_ledger import canonical_hash

    request_id = _request_id(context)
    if output.get("request_id") != request_id or output.get("connection_scope") != connection_scope(
        context, "send"
    ):
        raise ValueError("发送回执或渠道绑定与原任务不一致")
    connection = _connection(context, "send")
    receipt = request_kellai(f"messages/requests/{request_id}", connection)["data"]
    original = output.get("provider_receipt") or {}
    if (
        receipt.get("request_id") != request_id
        or not receipt.get("message_id")
        or original.get("message_id") != receipt["message_id"]
        or (
            original.get("provider_message_id")
            and original["provider_message_id"] != receipt.get("provider_message_id")
        )
    ):
        raise ValueError("渠道回执的消息标识与原请求不一致")
    if (
        receipt.get("status") != "accepted"
        or receipt.get("provider_state") not in {"delivered", "read"}
        or receipt.get("persisted") is not True
        or not receipt.get("provider_message_id")
    ):
        raise KellaiReceiptPending("渠道尚未给出完整送达证据")
    conversation_connection = _connection(context, "conversations")
    if conversation_connection.get("connection_id") != connection["connection_id"]:
        raise ValueError("查询期间渠道绑定已变化")
    data = request_kellai(
        f"customers/{params['customer_id']}/conversations?limit=100", conversation_connection
    )["data"]
    matches = [row for row in data.get("messages", []) if row.get("id") == receipt["message_id"]]
    expected = {
        key: params[key] for key in ("customer_id", "channel_type", "contact_id", "content")
    }
    if len(matches) != 1 or data.get("customer_id") != params["customer_id"]:
        raise ValueError("未找到原客户的唯一发送消息")
    message = matches[0]
    if (
        any(message.get(key) != value for key, value in expected.items())
        or message.get("direction") != "outbound"
        or (message.get("metadata") or {}).get("delivery_request_id") != request_id
    ):
        raise ValueError("实际消息的收件人或内容与批准请求不一致")
    if output["connection_scope"] != connection_scope(context, "send"):
        raise ValueError("核验期间渠道绑定已变化")
    return {
        "request_id": request_id,
        "message_id": receipt["message_id"],
        "provider_message_id": receipt["provider_message_id"],
        "provider_state": receipt["provider_state"],
        "connection_id": connection["connection_id"],
        "message_sha256": canonical_hash(expected),
    }


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
        connection = _connection(context, action)
        if action == "send":
            request_id = _approved_request_id(params, context)
            scope = connection_scope(context, action)
            result = request_kellai(
                "messages/send", connection, {**params, "client_request_id": request_id}
            )
            output: dict[str, Any] = {
                "success": False,
                "execution_state": "pending",
                "retryable": False,
                "request_id": request_id,
                "connection_scope": scope,
                "provider_receipt": result.get("data") or {},
                "message": "渠道回执待核验，请查询原请求，勿重新发送。",
            }
            receipt = result.get("data")
            if not isinstance(receipt, dict):
                output.update(
                    execution_state="unknown",
                    error_code="kellai_receipt_unconfirmed",
                    reconciliation_required=True,
                )
                return output
            if receipt.get("provider_state") == "failed" or receipt.get("status") in {
                "failed",
                "rejected",
                "cancelled",
                "requires_desktop_execution",
            }:
                output["execution_state"] = "failed"
                output["message"] = (
                    "此渠道需要在客来来桌面端执行，当前请求未外发。"
                    if receipt.get("status") == "requires_desktop_execution"
                    else "渠道确认原请求失败、拒绝或取消；未重新发送。"
                )
            elif receipt.get("status") == "unknown":
                output.update(execution_state="unknown", requires_reconciliation=True)
            else:
                try:
                    verify_kellai_receipt(params, context, output)
                except KellaiReceiptPending:
                    pass
                else:
                    output.update(
                        success=True, execution_state="completed", message="已独立核验原消息送达。"
                    )
            return output
        if action == "receipt":
            result = request_kellai(f"messages/requests/{params['client_request_id']}", connection)
            return {
                "success": True,
                "provider_receipt": result["data"],
                "message": "已读取原请求回执；渠道受理或发送不代表已送达。",
            }
        path = (
            f"customers/{params['customer_id']}/conversations?limit={params.get('limit', 30)}"
            if action == "conversations"
            else f"customers?limit={params.get('limit', 50)}"
            if action == "customers"
            else "data-status"
            if action == "data_status"
            else "channels"
        )
        return request_kellai(path, connection)
    except AgentModAuthorizationError:
        return {
            "success": False,
            "error_code": "tool_identity_required",
            "message": "客来来工具需要有效登录绑定",
        }
    except binding.KellaiAuthorizationError as exc:
        return {"success": False, "error_code": "kellai_scope_required", "message": str(exc)}
    except PermissionError as exc:
        return {"success": False, "error_code": "approval_required", "message": str(exc)}
    except (KellaiRequestError, ValueError) as exc:
        return {
            "success": False,
            "error_code": "kellai_receipt_unconfirmed",
            "message": str(exc),
            "retryable": False,
            **(
                {
                    "execution_state": "unknown",
                    "request_id": request_id,
                    "requires_reconciliation": True,
                }
                if request_id
                else {}
            ),
        }
