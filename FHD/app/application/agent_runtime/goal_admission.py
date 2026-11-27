"""Bind original host-owned task evidence without planning or model calls."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from app.domain.task_lifecycle.agent_runtime_contract import (
    AgentRuntimeContractError,
    build_goal_contract,
    validate_runtime_goal,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeGoal:
    contract: dict[str, Any]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    question: str = ""


def attach_context_evidence(run: Any, contract: dict[str, Any]) -> None:
    """Project actual admission evidence inside the original goal-freeze SQL CAS.

    This only constructs ledger records; it performs no retrieval or business I/O.
    """
    from app.application.agent_orchestrator.run_models import (
        memory_reference_from_dict,
        retrieval_call_from_dict,
    )
    from app.domain.task_lifecycle.agent_runtime_contract import canonical_digest

    for evidence in contract["request"].get("context_evidence") or []:
        reference = "goal_context_" + canonical_digest([contract["digest"], evidence])[:40]
        common = {
            "query": contract["request"]["text"],
            "status": "completed" if evidence.get("status") == "completed" else "failed",
            "error": "" if evidence.get("status") == "completed" else "recall_unavailable",
            "metadata": {
                "origin": "xiaox.goal_admission",
                "goal_digest": contract["digest"],
                "owner_id": evidence.get("owner_id"),
                "tenant_id": contract["scope"].get("tenant_id"),
                "mod_id": contract["scope"].get("mod_id"),
                "authority": "context_only",
            },
        }
        if evidence.get("source") == "dataset_rag":
            if any(call.call_id == reference for call in run.retrieval_calls):
                continue
            run.retrieval_calls.append(
                retrieval_call_from_dict(
                    {
                        **common,
                        "call_id": reference,
                        "retriever": "dataset_rag",
                        "source": evidence["dataset_id"],
                        "top_k": 5,
                        "chunks": evidence.get("chunks") or [],
                        "citations": evidence.get("citations") or [],
                    }
                )
            )
        elif evidence.get("source") in {"memory_v2", "user_memory_rag"}:
            if any(item.reference_id == reference for item in run.memory_references):
                continue
            run.memory_references.append(
                memory_reference_from_dict(
                    {
                        **common,
                        "reference_id": reference,
                        "source": evidence["source"],
                        "memory_type": evidence["source"],
                        "summary": evidence.get("summary") or "",
                        "hits": evidence.get("hits") or [],
                    }
                )
            )


def _context_evidence(run: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Recall from the current actor's authority, never from caller memory fields."""
    from app.application.agent_task_context import scoped_conversation_user_id
    from app.application.ai_chat.conversation_history import authorized_memory_context
    from app.infrastructure.auth.agent_mod_scope import (
        agent_dataset_access_context,
        validate_actor_context,
    )

    if validate_actor_context(context) is not None:
        return []
    context = {**context, "conversation_id": context.get("conversation_id") or run.run_id}
    authorized = authorized_memory_context(
        scoped_conversation_user_id(run.user_id, context), context
    )
    evidence: list[dict[str, Any]] = []
    if authorized is not None:
        owner, _access = authorized
        try:
            from app.domain.shared_services.user_memory_service import get_user_memory_service

            summary = get_user_memory_service().format_memory_v2_for_prompt(
                user_id=owner, max_items=6
            )
            if summary and "无已确认记忆" not in summary:
                evidence.append(
                    {
                        "source": "memory_v2",
                        "owner_id": owner,
                        "summary": summary,
                        "status": "completed",
                    }
                )
        except RECOVERABLE_ERRORS:
            logger.warning("Xiaox original goal memory recall unavailable", exc_info=True)
            evidence.append({"source": "memory_v2", "owner_id": owner, "status": "unavailable"})
        try:
            from app.application.user_memory_vector_app_service import (
                get_user_memory_rag_app_service,
            )

            rag = get_user_memory_rag_app_service()
            result = rag.query(user_id=owner, query_text=run.message, top_k=3)
            hits = result.get("hits") if isinstance(result, dict) else None
            if isinstance(hits, list) and hits:
                evidence.append(
                    {
                        "source": "user_memory_rag",
                        "owner_id": owner,
                        "hits": hits,
                        "summary": rag.format_for_prompt(
                            user_id=owner, query_text=run.message, hits=hits, max_hits=3
                        ),
                        "status": "completed",
                    }
                )
        except RECOVERABLE_ERRORS:
            logger.warning("Xiaox original goal memory RAG unavailable", exc_info=True)
            evidence.append(
                {"source": "user_memory_rag", "owner_id": owner, "status": "unavailable"}
            )
    dataset_id = str(context.get("knowledge_dataset_id") or context.get("dataset_id") or "").strip()
    if dataset_id:
        try:
            from app.application.dataset_rag_app_service import get_dataset_rag_app_service

            access = agent_dataset_access_context(context)
            result = get_dataset_rag_app_service().query(
                dataset_id=dataset_id,
                query=run.message,
                top_k=5,
                tenant_id=str(access.tenant_id),
                access_context=access,
            )
            evidence.append(
                {
                    "source": "dataset_rag",
                    "dataset_id": dataset_id,
                    "owner_id": str(access.actor_id),
                    "tenant_id": str(access.tenant_id),
                    "mod_id": access.mod_id,
                    "status": "completed" if result.get("success") else "unavailable",
                    "chunks": result.get("chunks") or [] if result.get("success") else [],
                    "citations": result.get("citations") or [] if result.get("success") else [],
                }
            )
        except RECOVERABLE_ERRORS:
            logger.warning("Xiaox original goal knowledge recall unavailable", exc_info=True)
            evidence.append(
                {"source": "dataset_rag", "dataset_id": dataset_id, "status": "unavailable"}
            )
    if validate_actor_context(context) is not None:
        raise AgentRuntimeContractError("runtime_revoked", "召回期间原登录权限已失效")
    if run.metadata.get("runtime_requested_deliverable") == "action_plan":
        from app.infrastructure.xiaox.tools import desktop_navigation_items

        if entries := desktop_navigation_items(context.get("desktop_navigation")):
            evidence.append({"source": "desktop_navigation", "entries": entries})
    from app.application.skills.skill_registry import skill_rules

    rules = skill_rules(run.message)
    if rules:
        evidence.append({"source": "host_skill", "rules": rules, "status": "completed"})
    return evidence


def prepare_runtime_goal(
    binding: Any, *, history: list[dict[str, Any]] | None = None
) -> RuntimeGoal:
    """Resolve owned attachments, never infer a plan or grant business authority."""
    from app.application.agent_orchestrator.attachment_inputs import (
        AttachmentInputError,
        resolve_attachment_context,
    )

    run = binding.run
    existing = run.metadata.get("runtime_goal_contract")
    if existing is not None:
        validate_runtime_goal(run)
        return RuntimeGoal(contract=copy.deepcopy(existing))
    context = binding.context
    answered = [event for event in run.events if event.event_type == "runtime.input_answered"]
    # Only upload references cross this boundary. Paths/analysis supplied by a
    # caller remain quoted user data and cannot become verified file evidence.
    for attached in [
        run.metadata.get("_xiaox_input_data"),
        *(e.data.get("input_data") for e in answered),
    ]:
        if isinstance(attached, dict) and "attachment_upload_ids" in attached:
            context["attachment_upload_ids"] = copy.deepcopy(attached["attachment_upload_ids"])
    try:
        _context, artifacts = resolve_attachment_context(context)
    except AttachmentInputError as exc:
        return RuntimeGoal(contract=build_goal_contract(run, history=history), question=str(exc))
    evidence = _context_evidence(run, context)
    if not artifacts:
        from app.application.agent_runtime.conversation_attachments import (
            EVIDENCE_SOURCE,
            conversation_upload_context,
            conversation_upload_directory,
        )

        if previous := conversation_upload_directory(run, context):
            directory: dict[str, Any] = {"source": EVIDENCE_SOURCE, "entries": previous}
            if verified_read := conversation_upload_context(run, context, previous):
                key = "verified_reads" if isinstance(verified_read, list) else "verified_read"
                directory[key] = verified_read
            evidence.append(directory)
    return RuntimeGoal(
        contract=build_goal_contract(
            run,
            history=history,
            attachments=artifacts,
            context_evidence=evidence,
        ),
        artifacts=artifacts,
    )
