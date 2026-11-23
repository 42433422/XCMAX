"""Verify the original customer delivery through existing scoped read endpoints."""

from __future__ import annotations

from urllib.parse import quote

from app.application.agent_orchestrator.business_action_ledger import canonical_hash
from app.application.agent_orchestrator.verification_readback import _report


def original_delivery_receipt(run, step, output: dict) -> dict | None:
    """Find only the original adapter receipt, including the deadline wrapper."""
    from app.application.tools.kellai import delivery_request_id

    if (step.tool_id, step.action) != ("kellai", "send"):
        return None
    expected = delivery_request_id(run.run_id, step.step_id)
    current = output
    for _ in range(8):
        if not isinstance(current, dict):
            break
        data = current.get("data")
        claimed = data.get("delivery_receipt") if isinstance(data, dict) else None
        if isinstance(claimed, dict):
            return claimed if claimed.get("request_id") == expected else None
        nested = current.get("reconciliation_evidence")
        if not isinstance(nested, dict):
            break
        current = nested
    return None


def can_observe_kellai_delivery(run, step, call) -> bool:
    """A stopped unknown delivery can gain evidence, never permission to resend."""
    from app.domain.task_lifecycle.results import execution_result_requires_reconciliation

    return bool(
        step.status == call.status == "failed"
        and call.output.get("success") is False
        and call.output.get("retryable") is False
        and execution_result_requires_reconciliation(call.output)
        and original_delivery_receipt(run, step, call.output)
    )


def verify_kellai_delivery(run, step, call, context: dict) -> dict:
    from app.application import kellai_binding_app_service as binding
    from app.application.tools.kellai import delivery_request_id
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.infrastructure.kellai_client import request_kellai

    source = "kellai_original_delivery"
    output = call.output
    request_id = delivery_request_id(run.run_id, step.step_id)
    claimed = original_delivery_receipt(run, step, output)
    if claimed is None:
        return _report("failed", "result_delivery_identity_mismatch", source)
    actor = _bound_actor(context)
    actor_id, tenant_id = int(actor.id), str(context.get("tenant_id") or "")
    connection = binding.scoped_connection(
        actor=actor_id, tenant_id=tenant_id, scope="messages.send"
    )
    approved_connection = (call.metadata.get("verification_contract") or {}).get(
        "kellai_connection_sha256"
    )
    if (
        not approved_connection
        or binding.connection_identity_sha256(connection) != approved_connection
    ):
        return _report("failed", "result_delivery_connection_changed", source)
    receipt = request_kellai(f"messages/requests/{request_id}", connection).get("data")
    if not isinstance(receipt, dict) or receipt.get("request_id") != request_id:
        return _report("inconclusive", "result_delivery_receipt_unavailable", source)
    if (
        receipt.get("status") in {"failed", "cancelled", "rejected"}
        or receipt.get("provider_state") == "failed"
    ):
        return _report("failed", "result_delivery_failed", source, request_id=request_id)
    if (
        receipt.get("status") not in {"accepted", "delivered"}
        or receipt.get("provider_state") not in {"delivered", "read"}
        or receipt.get("persisted") is not True
        or not receipt.get("provider_message_id")
        or not receipt.get("message_id")
    ):
        return _report(
            "inconclusive",
            "result_delivery_confirmation_pending",
            source,
            request_id=request_id,
            delivery_state=str(receipt.get("provider_state") or receipt.get("status") or "unknown"),
        )
    if any(
        claimed.get(key) and claimed[key] != receipt.get(key)
        for key in ("message_id", "provider_message_id")
    ):
        return _report("failed", "result_delivery_identity_mismatch", source)
    # A matching provider ID alone does not prove the approved customer,
    # recipient and content. Read the original scoped message projection too.
    connection = binding.scoped_connection(
        actor=actor_id, tenant_id=tenant_id, scope="customer_conversations.read"
    )
    if binding.connection_identity_sha256(connection) != approved_connection:
        return _report("failed", "result_delivery_connection_changed", source)
    params = step.params
    data = request_kellai(
        f"customers/{params['customer_id']}/conversations?message_id="
        f"{quote(str(receipt['message_id']), safe='')}&limit=1",
        connection,
    ).get("data")
    if not isinstance(data, dict) or data.get("customer_id") != params["customer_id"]:
        return _report("inconclusive", "result_delivery_message_unavailable", source)
    rows = data.get("messages")
    messages = (
        [row for row in rows if isinstance(row, dict) and row.get("id") == receipt["message_id"]]
        if isinstance(rows, list)
        else []
    )
    if len(messages) != 1:
        return _report("inconclusive", "result_delivery_message_unavailable", source)
    message = messages[0]
    metadata = message.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("delivery_request_id") != request_id
        or metadata.get("provider_message_id") != receipt["provider_message_id"]
        or message.get("direction") != "outbound"
        or type(message.get("customer_id")) is not int
        or any(
            message.get(key) != params[key]
            for key in ("customer_id", "channel_type", "contact_id", "content")
        )
    ):
        return _report("failed", "result_delivery_message_mismatch", source)
    return _report(
        "verified",
        "result_verified",
        source,
        request_id=request_id,
        message_id=receipt["message_id"],
        provider_message_id=receipt["provider_message_id"],
        delivery_state=receipt["provider_state"],
        approved_params_sha256=canonical_hash(params),
        message_sha256=canonical_hash({key: message[key] for key in params}),
        delivery_verified=True,
    )
