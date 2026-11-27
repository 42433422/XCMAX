"""Conversation history and recallable memory persistence, independent of chat dispatch."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any, Protocol

from app.infrastructure.modstore_transport import safe_route_metadata
from app.utils.operational_errors import RECOVERABLE_ERRORS

if TYPE_CHECKING:
    from app.application.agent_orchestrator.run_models import AgentRun

logger = logging.getLogger(__name__)

_SECRET_TEXT = re.compile(
    r"(?i)(\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|密码|口令)\b\s*[:=]\s*)([^\s,;]+)|"
    r"(\bBearer\s+)[A-Za-z0-9._~+/=-]+"
)
_SECRET_FIELD = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|credential|cookie|authorization|密码|口令)"
)


def _storage_safe(value: Any, *, depth: int = 0) -> Any:
    """Bound persisted transcript metadata and redact credential-like content."""
    if depth >= 8:
        return "[已截断]"
    if isinstance(value, dict):
        return {
            str(key)[:120]: "[已隐藏]"
            if _SECRET_FIELD.search(str(key))
            else _storage_safe(item, depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, list):
        return [_storage_safe(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        bounded = value[:8000]
        return _SECRET_TEXT.sub(
            lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", bounded
        )
    return value


class ConversationStore(Protocol):
    def save_turn(
        self,
        *,
        session_id: str,
        user_id: str,
        messages: list[dict[str, Any]],
        expected_revision: int | None = None,
    ) -> list[int]: ...

    def settle_queued_reply(
        self,
        *,
        session_id: str,
        user_id: str,
        expected_revision: int,
        assistant: dict[str, Any],
        allow_retry_repair: bool = False,
        source_guard: Callable[[Any], AbstractContextManager[bool]] | None = None,
    ) -> int | None: ...


def apply_history_fault(payload: dict[str, Any]) -> dict[str, Any]:
    """开发机故障注入。未设置 XCAGI_HISTORY_FAULT_FILE 时原样返回。"""
    import math
    import time
    from pathlib import Path

    from fastapi import HTTPException

    spec_path = os.environ.get("XCAGI_HISTORY_FAULT_FILE", "").strip()
    if not spec_path:
        return payload
    try:
        spec = Path(spec_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return payload
    if spec.startswith("delay:"):
        try:
            delay = float(spec.split(":", 1)[1] or 0)
        except ValueError:
            return payload
        if math.isfinite(delay) and delay > 0:
            # All callers are sync FastAPI handlers, executed in its worker thread pool.
            time.sleep(min(delay, 30))
        return payload
    if spec in {"500", "502", "504"}:
        raise HTTPException(status_code=int(spec), detail=f"history fault {spec}")
    if spec == "empty":
        cloned = dict(payload)
        cloned["messages"] = []
        cloned["sessions"] = []
        return cloned
    if spec == "partial":
        cloned = dict(payload)
        messages = list(cloned.get("messages") or [])
        sessions = list(cloned.get("sessions") or [])
        cloned["messages"] = messages[:1]
        cloned["sessions"] = sessions[:1]
        return cloned
    return payload


def _stopped_workbook_files(
    repository, run: AgentRun, request_key: str, turn_id: str
) -> list[dict[str, Any]]:
    """Observe the already verified child of the interrupted original queue turn."""
    from app.application.agent_orchestrator.artifact_files import read_verified_run_file
    from app.application.agent_orchestrator.verification_recovery import (
        VerificationRecoveryError,
        _stopped_queue_proof,
    )
    from app.application.agent_orchestrator.verification_workbook import is_workbook_write
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.domain.task_lifecycle.agent_runtime_results import verified_receipt_artifacts
    from app.infrastructure.auth.agent_mod_scope import _bound_actor
    from app.infrastructure.xiaox.binding import XiaoxBindingError, XiaoxBindingStore
    from app.infrastructure.xiaox.receipts import read_call_receipt

    if run.status not in {"blocked", "failed"}:
        return []
    pending = run.metadata.get("_xiaox_queued_request") or {}
    requests = run.metadata.get("runtime_requests") or {}
    request = requests.get(request_key) or {}
    worker_turn = "queue_" + canonical_digest([run.run_id, request_key])
    worker = requests.get(canonical_digest({"turn_id": worker_turn, "owner": run.user_id})) or {}
    generation = pending.get("generation")
    if (
        type(generation) is not int
        or pending.get("state") != "queued"
        or pending.get("request_key") != request_key
        or pending.get("worker_turn_id") != worker_turn
        or request.get("turn_id") != turn_id
        or request.get("state") != "queued"
        or worker.get("turn_id") != worker_turn
        or worker.get("state") not in {"admitted", "interrupted", "returned"}
    ):
        return []

    try:
        proof = _stopped_queue_proof(repository, run)
        if proof is None:
            return []
        _, execution = proof
        if execution.state != "unknown":
            return []
        store = XiaoxBindingStore(repository)
        binding = store.get(run.run_id)
        ledger = binding.metadata
        if (
            binding.run.updated_at != run.updated_at
            or ledger.get("generation") != generation + 1
            or ledger.get("coordinator_active") is not False
            or ledger.get("revoked") is not True
            or str(_bound_actor(binding.context).id) != run.user_id
        ):
            return []
        files = {}
        for call in (ledger.get("calls") or {}).values():
            if (
                call.get("state") != "completed"
                or call.get("generation") != ledger["generation"]
                or call.get("isolated_artifact") is not True
                or (call.get("tool_id"), call.get("action")) != ("employee", "execute")
                or not is_workbook_write(call.get("params") or {})
            ):
                continue
            receipt = read_call_receipt(store, binding, call)
            if (receipt.get("verification") or {}).get("status") != "verified":
                continue
            for file in verified_receipt_artifacts([{**call, "receipt": receipt}]):
                artifact = next(
                    item
                    for item in receipt["artifacts"]
                    if item["artifact_id"] == file["artifact_id"]
                )
                read_verified_run_file(file["run_id"], artifact)
                files[file["uri"]] = file
        return list(files.values())
    except (VerificationRecoveryError, XiaoxBindingError, OSError, ValueError):
        return []


def restore_runtime_history_files(page: dict[str, Any], context: dict[str, Any]) -> None:
    """Project scoped inputs, completed replies and stopped-turn files into the history response."""
    from app.application.agent_orchestrator.run_models import RunContextScope
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_runtime.chat import runtime_chat_files
    from app.application.agent_runtime.chat_file_sources import released_chat_file_sources
    from app.application.agent_runtime.conversation_attachments import original_conversation_uploads
    from app.application.ai_chat.dialogue_memory import conversation_key
    from app.domain.shared_services.conversation_service import queued_chat_binding
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest

    revision = context.get("_conversation_revision")
    if type(revision) is not int or not context["tenant_id"]:
        return
    owner = str(context["local_user_id"])
    scope = RunContextScope(
        str(context["tenant_id"]), context["mod_id"], context["session_id"], revision
    )
    repository = get_agent_run_repository()
    runs = {}
    for row in page["messages"]:
        if row["role"] not in {"user", "assistant"}:
            continue
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        binding, summary, ui = (
            metadata.get(key) or {} for key in ("business_harness", "summary", "ui")
        )
        if not all(isinstance(value, dict) for value in (binding, summary, ui)):
            continue
        # A persisted or client-supplied projection is never historical evidence.
        if "fileSources" in ui:
            del ui["fileSources"]
            row["metadata"] = json.dumps({**metadata, "ui": ui}, ensure_ascii=False)
        run_id, turn_id = binding.get("run_id"), binding.get("turn_id")
        if (
            binding.get("recall_bound") is not True
            or binding.get("conversation_id") != context["session_id"]
            or not isinstance(run_id, str)
            or not isinstance(turn_id, str)
            or summary.get("run_id") != run_id
            or summary.get("turn_id") != turn_id
        ):
            continue
        if row["role"] == "assistant" and (
            (summary.get("status") == "queued" and ui.get("outputArtifacts"))
            or summary.get("action") != "runtime_reply"
            or summary.get("status") not in {"completed", "queued"}
        ):
            continue
        if run_id not in runs:
            runs[run_id] = repository.get(run_id)
        run = runs[run_id]
        if (
            run is None
            or run.user_id != owner
            or run.metadata.get("runtime_type") != "xiaox"
            or not scope.matches(run)
        ):
            continue
        if row["role"] == "user":
            if (run.metadata.get("runtime_context") or {}).get("turn_id") == turn_id:
                uploads = original_conversation_uploads(run)
                if uploads:
                    files = [{"name": item.name, "reference": item.reference} for item in uploads]
                    row["metadata"] = json.dumps(
                        {**metadata, "ui": {**ui, "inputAttachments": files}},
                        ensure_ascii=False,
                    )
            continue
        key = canonical_digest({"turn_id": turn_id, "owner": owner})
        if summary.get("status") == "queued":
            if queued_chat_binding(metadata) == (turn_id, run_id, conversation_key(context)) and (
                files := _stopped_workbook_files(repository, run, key, turn_id)
            ):
                row["content"] = "本轮已结束，原任务结果仍待核对。"
                row["metadata"] = json.dumps(
                    {
                        **metadata,
                        "summary": {**summary, "status": "unknown", "success": False},
                        "ui": {
                            **ui,
                            "workflowAction": "unknown",
                            "execution": {"effect": "unknown", "outcome": "unknown"},
                            "runtimeContinuation": {
                                "runId": None,
                                "status": "unknown",
                                "sessionId": scope.session_id,
                            },
                            "outputArtifacts": files,
                        },
                    },
                    ensure_ascii=False,
                )
            continue
        if run.status != "completed":
            continue
        request = (run.metadata.get("runtime_requests") or {}).get(key) or {}
        result = request.get("result")
        if (
            request.get("state") == "returned"
            and request.get("turn_id") == turn_id
            and isinstance(result, dict)
            and result.get("run_id") == run_id
        ):
            projected: dict[str, Any] = {}
            if not ui.get("outputArtifacts") and (files := runtime_chat_files(result)):
                projected["outputArtifacts"] = files
            if row.get("content") == result.get("output") and (
                sources := released_chat_file_sources(run, result)
            ):
                projected["fileSources"] = sources
            if projected:
                row["metadata"] = json.dumps(
                    {**metadata, "ui": {**ui, **projected}}, ensure_ascii=False
                )


def persist_chat_turn(
    user_id: str,
    message: str,
    context: dict[str, Any],
    response_data: dict[str, Any],
    *,
    store: ConversationStore | None = None,
    _settle_queued: bool = False,
    _repair_retry: bool = False,
    _source_guard: Callable[[Any], AbstractContextManager[bool]] | None = None,
) -> dict[str, Any]:
    """
    在请求携带 session_id / conversation_id 时，将会话与工具结果摘要写入 ai_conversations，
    便于审计与和出货/产品等业务联动检索。
    """
    # Transcript bodies are authoritative; metadata projections may be bounded,
    # but must never silently truncate the original user or assistant message.
    redact = lambda value: _SECRET_TEXT.sub(
        lambda match: f"{match.group(1) or match.group(3)}[已隐藏]", str(value or "")
    )
    message = redact(message)
    raw_inner = response_data.get("data")
    raw_inner = raw_inner if isinstance(raw_inner, dict) else {}
    reply = redact(
        response_data.get("response")
        or raw_inner.get("text")
        or (response_data.get("message") if not response_data.get("success") else "")
    )
    response_data = _storage_safe(response_data)
    session_id = str(context.get("conversation_id") or context.get("session_id") or "").strip()
    if (
        context.get("session_id")
        and context.get("conversation_id")
        and str(context["session_id"]).strip() != str(context["conversation_id"]).strip()
    ):
        raise ValueError("conflicting conversation identifiers")
    if not session_id:
        return {"status": "not_requested"}
    from app.application.task_conversation_store import durable_user_id

    # The web_normal_* id scopes model memory, not the authenticated history owner.
    owners = [
        durable_user_id(context[key]) for key in ("local_user_id", "actor_id") if key in context
    ]
    # Conversation identifiers and body user_id never authorize durable ownership.
    if not owners or None in owners or len(set(owners)) != 1:
        return {"status": "not_authorized"}
    history_user_id = str(owners[0])

    inner = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}
    if not isinstance(inner, dict):
        inner = {}
    inner_payload = inner.get("data") if isinstance(inner.get("data"), dict) else {}
    tool_call = (
        response_data.get("toolCall") if isinstance(response_data.get("toolCall"), dict) else {}
    )
    if not isinstance(inner_payload, dict):
        inner_payload = {}
    if not isinstance(tool_call, dict):
        tool_call = {}
    intent = str(
        inner_payload.get("intent")
        or inner_payload.get("tool_key")
        or tool_call.get("tool_id")
        or inner.get("action")
        or ""
    ).strip()
    from app.application.agent_orchestrator.trace_payloads import _payload_status
    from app.domain.task_lifecycle.results import (
        execution_result_requires_reconciliation,
        execution_result_wait_reason,
    )

    status: str = _payload_status(response_data)
    if status == "waiting_user" and execution_result_wait_reason(response_data) in {
        "authorization",
        "approval",
    }:
        status = "waiting_approval"
    elif status == "blocked" and execution_result_requires_reconciliation(response_data):
        status = "unknown"
    summary = {
        "success": bool(response_data.get("success")),
        "action": inner.get("action"),
        "status": status,
        "intent": intent,
        "toolCall": tool_call or None,
        "plan_id": inner_payload.get("plan_id"),
        "document": (inner_payload.get("document") or {}).get("doc_name")
        if isinstance(inner_payload.get("document"), dict)
        else None,
        "excel_import": inner_payload.get("result")
        if inner_payload.get("intent") == "excel_import_to_db"
        else None,
        "task_id": context.get("task_id"),
        "turn_id": context.get("turn_id"),
        "run_id": response_data.get("run_id")
        or response_data.get("agent_run_id")
        or inner.get("run_id")
        or inner.get("agent_run_id"),
    }
    if context.get("_execution_identity") and context.get("execution_tool"):
        summary["execution_identity"] = str(context["_execution_identity"])
        summary["execution_tool"] = str(context["execution_tool"])
        dispatch = response_data.get("dispatch")
        if isinstance(dispatch, dict):
            summary["dispatch"] = {
                key: str(dispatch[key])
                for key in ("request_id", "task_id", "status")
                if dispatch.get(key) is not None
            }
    from app.application.agent_orchestrator.business_harness import (
        extract_payload_business_result,
    )

    ui_payload = {
        "thinkingSteps": inner_payload.get("thinking_steps")
        or inner.get("thinking_steps")
        or response_data.get("thinking_steps"),
        "todoSteps": inner_payload.get("todo"),
        "workflowAction": status if status != "completed" else inner.get("action") or status,
        "nodeResults": inner_payload.get("node_results"),
        "approvalCard": inner_payload.get("approval_card"),
        "attachments": inner_payload.get("attachments"),
        "outputArtifacts": inner.get("output_artifacts")
        if response_data.get("runtime") == "xiaox" and status == "completed" and summary["success"]
        else None,
        "businessResult": extract_payload_business_result(response_data),
    }
    if status == "unknown":
        ui_payload["execution"] = {"effect": "unknown", "outcome": "unknown"}
    elif response_data.get("execution_started") is False:
        ui_payload["execution"] = {"committed": False, "effect": "none", "outcome": "not_executed"}
    continuation = response_data.get("runtime_context_update")
    if response_data.get("runtime") == "xiaox" and isinstance(continuation, dict):
        ui_payload["runtimeContinuation"] = {
            "runId": continuation.get("agent_runtime_run_id"),
            "status": str(
                continuation.get("status") or response_data.get("execution_state") or status
            ),
            "sessionId": session_id,
        }
    ui_payload = {key: value for key, value in ui_payload.items() if value not in (None, "", [])}
    harness_metadata = {
        "protocol": context.get("business_harness_protocol") or "xcagi.business-harness.v1",
        "task_id": context.get("task_id"),
        "turn_id": context.get("turn_id"),
        "conversation_id": session_id,
        "run_id": summary.get("run_id"),
        "recall_bound": True,
    }
    from app.application.ai_chat.dialogue_memory import conversation_key

    harness_metadata["conversation_key"] = conversation_key(context)
    queued = response_data.get("runtime") == "xiaox" and status == "queued"
    if queued or _settle_queued:
        harness_metadata["queued_reply"] = True
    turn_id = str(context.get("turn_id") or "").strip()
    user_fingerprint = uuid.uuid5(
        uuid.NAMESPACE_URL,
        str(message),
    ).hex
    assistant_fingerprint = uuid.uuid5(
        uuid.NAMESPACE_URL,
        reply,
    ).hex
    user_idempotency_key = (
        f"xcagi.business-harness.v1:{turn_id}:user:{user_fingerprint}" if turn_id else ""
    )
    assistant_idempotency_key = (
        f"xcagi.business-harness.v1:{turn_id}:assistant:{assistant_fingerprint}" if turn_id else ""
    )
    meta_user = json.dumps(
        {
            "role_hint": "user",
            "input_fingerprint": context.get("_conversation_input_fingerprint"),
            "summary": summary,
            "business_harness": harness_metadata,
        },
        ensure_ascii=False,
        default=str,
    )
    clarification_candidates = inner_payload.get("candidates")
    meta_assistant = json.dumps(
        {
            "role_hint": "assistant",
            **(
                {"route_metadata": safe_route_metadata(response_data)}
                if safe_route_metadata(response_data)
                else {}
            ),
            "summary": summary,
            "business_harness": harness_metadata,
            "ui": ui_payload,
            **(
                {"clarification_candidates": clarification_candidates[:20]}
                if isinstance(clarification_candidates, list) and clarification_candidates
                else {}
            ),
        },
        ensure_ascii=False,
        default=str,
    )
    if store is None:
        from app.services import get_conversation_service

        store = get_conversation_service()
    assistant = {
        "role": "assistant",
        "content": reply,
        "intent": intent or "assistant_reply",
        "metadata": meta_assistant,
        "idempotency_key": assistant_idempotency_key,
    }
    if _settle_queued:
        message_id = store.settle_queued_reply(
            session_id=session_id,
            user_id=history_user_id,
            expected_revision=context["_conversation_revision"],
            assistant=assistant,
            allow_retry_repair=_repair_retry,
            **({"source_guard": _source_guard} if _source_guard is not None else {}),
        )
        return {"message_ids": [message_id] if message_id is not None else []}
    message_ids = store.save_turn(
        session_id=session_id,
        user_id=history_user_id,
        expected_revision=context.get("_conversation_revision"),
        messages=[
            {
                "role": "user",
                "content": message,
                "intent": intent or "chat",
                "metadata": meta_user,
                "idempotency_key": user_idempotency_key,
            },
            assistant,
        ],
    )
    if queued and summary.get("run_id") and turn_id:
        reconcile_queued_chat_reply(context, turn_id, str(summary["run_id"]))
    from app.application.ai_chat.active_conversation import remember_active_conversation

    try:
        remember_active_conversation(context, conversation_id=session_id)
    except RECOVERABLE_ERRORS:
        logging.getLogger(__name__).warning(
            "active conversation pointer update failed", exc_info=True
        )
    return {
        "status": "saved",
        "conversation_id": session_id,
        "message_ids": message_ids,
        "revision": context.get("_conversation_revision", 0),
        "turn_id": turn_id,
    }


def reconcile_queued_chat_reply(
    context: dict[str, Any],
    turn_id: str,
    run_id: str,
    *,
    run: AgentRun | None = None,
    publish: bool = True,
) -> bool:
    """Project the committed outcome of the original queue turn into its chat message."""
    from app.application.agent_orchestrator.run_models import RunContextScope
    from app.application.agent_orchestrator.run_repository import get_agent_run_repository
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.application.agent_runtime.gateway import public_runtime_result
    from app.application.ai_chat.queued_chat_delivery import _queued_chat_source_guard
    from app.application.task_conversation_store import durable_user_id
    from app.domain.shared_services.conversation_service import ConversationRevisionError
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest
    from app.infrastructure.tenant_scope import tenant_scope
    from app.request_active_mod_ctx import reset_request_active_mod_id, set_request_active_mod_id

    owner = durable_user_id(context.get("local_user_id") or context.get("actor_id"))
    tenant_id = context.get("tenant_id")
    tenant = durable_user_id(tenant_id)
    mod = str(context.get("mod_id") or "")
    session = str(context.get("conversation_id") or context.get("session_id") or "")
    revision = context.get("_conversation_revision")
    if not owner or (tenant_id and tenant is None) or not session or type(revision) is not int:
        return False
    try:
        repository = get_agent_run_repository()
        if not isinstance(repository, SQLAlchemyAgentRunRepository):
            return False
        observed = run
        run = repository.get(run_id)
        if observed is not None and (run is None or run.to_dict() != observed.to_dict()):
            return False
        if (
            run is None
            or run.run_id != run_id
            or run.user_id != str(owner)
            or run.metadata.get("runtime_type") != "xiaox"
        ):
            return False
        saved_tenant = (run.metadata.get("runtime_context") or {}).get("tenant_id")
        if tenant is None and saved_tenant not in (None, ""):
            return False
        if not RunContextScope(str(tenant or saved_tenant), mod, session, revision).matches(run):
            return False
        key = canonical_digest({"turn_id": turn_id, "owner": run.user_id})
        receipt = (run.metadata.get("runtime_requests") or {}).get(key) or {}
        if receipt.get("turn_id") != turn_id:
            return False
        if receipt.get("state") == "returned":
            result = receipt.get("result")
        else:
            from app.infrastructure.xiaox.queued_runtime import recover_interrupted_queue_request

            result = recover_interrupted_queue_request(repository, run, key)
            if result is not None:
                # Recovery itself commits the original returned receipt. Fence
                # that new snapshot, never the pre-recovery read or a later control.
                run = repository.get(run_id)
                if run is None:
                    return False
                receipt = (run.metadata.get("runtime_requests") or {}).get(key) or {}
                if receipt.get("state") != "returned" or receipt.get("result") != result:
                    return False
        repair_retry = False
        pending = run.metadata.get("_xiaox_queued_request") or {}
        latest = (run.metadata.get("runtime_requests") or {}).get(pending.get("request_key"), {})
        if (
            run.status == "completed"
            and receipt.get("state") == "returned"
            and isinstance(result, dict)
            and result.get("ok") is False
            and pending.get("request_key") != key
            and pending.get("task") == run.message
            and pending.get("input_data") == run.metadata.get("_xiaox_input_data")
            and pending.get("answer_to_waiting_input") is False
            and latest.get("state") == "returned"
            and isinstance(latest.get("result"), dict)
            and latest["result"].get("ok") is True
            and latest["result"].get("execution_state") == "completed"
            and latest["result"].get("output")
            == (run.final_output.get("xiaox_result") or {}).get("output")
        ):
            # A same-input retry has its own receipt; the original chat turn must
            # follow that terminal outcome without replacing unrelated later turns.
            result = latest["result"]
            repair_retry = True
        if not publish or not isinstance(result, dict) or result.get("run_id") != run_id:
            return False
        if (
            run.status in {"paused", "cancelled", "rejected"}
            and result.get("execution_state") != run.status
        ):
            return False
        payload = runtime_chat_payload(public_runtime_result(result), conversation_id=session)
        token = set_request_active_mod_id(mod)
        try:
            with tenant_scope(tenant):
                ack = persist_chat_turn(
                    str(owner),
                    "",
                    {**context, "turn_id": turn_id},
                    payload,
                    _settle_queued=True,
                    _repair_retry=repair_retry,
                    _source_guard=lambda db: _queued_chat_source_guard(db, run),
                )
                return bool(ack["message_ids"])
        finally:
            reset_request_active_mod_id(token)
    except ConversationRevisionError:
        return False
    except RECOVERABLE_ERRORS:
        logger.warning("queued chat reply could not update its original receipt", exc_info=True)
        return False


def retry_stored_chat_turn(
    context: dict[str, Any], turn_id: str, expected_revision: int
) -> dict[str, Any]:
    """Repair only the original authenticated receipt; never re-enter the planner."""
    from app.application.ai_chat.dialogue_memory import mark_history_persisted, stored_turn_receipt
    from app.domain.shared_services.conversation_service import ConversationRevisionError

    receipt = stored_turn_receipt(context, turn_id)
    if receipt is None:
        raise LookupError("本轮原始回执不可用，请核对历史；不会重新执行任务。")
    if receipt["revision"] != expected_revision:
        raise ConversationRevisionError("会话已经修改，请重新读取历史。")
    context = {
        **context,
        "turn_id": turn_id,
        "_conversation_revision": expected_revision,
        "_conversation_input_fingerprint": receipt.get("input_fingerprint"),
    }
    ack = persist_chat_turn(
        str(context["local_user_id"]), receipt["message"], context, receipt["payload"]
    )
    mark_history_persisted(context, turn_id, ack)
    return {
        "success": True,
        "saved": ack["status"] == "saved",
        "durable": ack["status"] == "saved",
        **ack,
    }


def authorized_memory_context(
    user_id: str, context: dict[str, Any], *, write: bool = False
) -> tuple[str, dict[str, Any] | None] | None:
    """Validate a live actor and return its stable cross-session memory namespace.

    Dataset/Persy capture additionally needs server-derived dataset permissions;
    ordinary personal memory requires actor ownership, not a dataset grant.
    """
    from app.application.agent_task_context import (
        scoped_conversation_user_id,
        scoped_personal_memory_id,
    )
    from app.application.task_conversation_store import durable_user_id
    from app.infrastructure.auth.agent_mod_scope import (
        AgentModAuthorizationError,
        agent_dataset_access_context,
        validate_actor_context,
    )
    from app.utils.operational_errors import RECOVERABLE_ERRORS

    if validate_actor_context(context) is not None:
        return None
    owner = durable_user_id(context.get("user_id"))
    if (
        owner is None
        or not (context.get("local_user_id") or context.get("actor_id"))
        or any(
            durable_user_id(context[key]) != owner
            for key in ("local_user_id", "actor_id")
            if key in context
        )
    ):
        return None
    if not context.get("session_id") and not context.get("conversation_id"):
        return None
    normalized = str(user_id or "").strip()
    if normalized != scoped_conversation_user_id(normalized, context):
        return None
    access = None
    if context.get("_dataset_access_context_trusted") or context.get("_dataset_access_context"):
        access_errors: tuple[type[Exception], ...] = (
            AgentModAuthorizationError,
        ) + RECOVERABLE_ERRORS
        try:
            principal = agent_dataset_access_context(context)
        except access_errors:
            return None
        required = "dataset.write" if write else "dataset.read"
        if principal.is_admin or required in principal.permissions:
            access = principal.to_dict()
    memory_namespace = scoped_personal_memory_id(context)
    if not memory_namespace:
        return None
    return memory_namespace, access


def persist_recallable_chat_turn(
    *,
    user_id: str,
    message: str,
    source: str | None,
    context: dict[str, Any],
    response_data: dict[str, Any],
) -> None:
    if context.get("memory_capture_enabled") is False or not response_data.get("success"):
        return
    authorized = authorized_memory_context(user_id, context, write=True)
    if authorized is None:
        return
    _memory_namespace, access_context = authorized
    if access_context is None and context.get("persy_memory_scope") == "tenant":
        return  # A private-memory capability never authorizes a tenant-wide write.
    raw_inner = response_data.get("data")
    inner: dict[str, Any] = raw_inner if isinstance(raw_inner, dict) else {}
    action = str(response_data.get("action") or inner.get("action") or "").strip().lower()
    if action in {
        "error",
        "error_fallback",
        "fallback",
        "goodbye",
        "greeting",
        "help",
        "requires_token",
    }:
        return
    sensitive = re.compile(
        "(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|验证码|密码|密钥)",
        re.I,
    )
    assistant_text = str(response_data.get("response") or "").strip()
    if not assistant_text:
        if not isinstance(inner, dict):
            inner = {}
        assistant_text = str(inner.get("text") or inner.get("message") or "").strip()
    if not assistant_text or sensitive.search(f"{message}\n{assistant_text}"):
        return
    # Raw dialogue remains in the conversation store. Only active, scoped
    # MemoryV2 records supply long-term evidence.
    from app.application.persy_memory_app_service import get_persy_memory_app_service

    service = get_persy_memory_app_service()
    if access_context is not None:
        captured = service.capture_conversation_turn(
            access_context=access_context,
            user_message=message,
            assistant_message=assistant_text,
            session_id=str(context.get("session_id") or context.get("conversation_id") or ""),
            source=str(source or "chat"),
            scope=str(context.get("persy_memory_scope") or "user"),
        )
    else:
        captured = service.capture_personal_turn(
            user_id=user_id,
            context=context,
            user_message=message,
            assistant_message=assistant_text,
            source=str(source or "chat"),
        )
    if isinstance(captured, dict) and not captured.get("success"):
        logger.warning(
            "memory candidate capture incomplete: %s",
            captured.get("errors") or captured.get("error_code"),
        )
