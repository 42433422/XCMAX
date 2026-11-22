"""RAG's actual cognition consumer, private reproductions and independent citation checks.

Reuse GrowthBook allocation, original SQL/outbox and promptfoo. Citation integrity
proves that references name authorized supplied chunks, not factual correctness,
customer acceptance or business success. No extra model call or budget is created.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from modstore_server import rag_service
from modstore_server.customer_service_tools import json_loads
from modstore_server.models import OutboxEvent, User, get_session_factory
from modstore_server.retort_experiment_surfaces import RAG_MEASUREMENT, RAG_RESOURCE

START = "rag.cognition.started"
COMPLETED = "rag.cognition.completed"


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _policies():
    if not os.getenv("MODSTORE_RETORT_PROTOCOLS"):
        return []
    from modstore_server.retort_evolution_api import _templates

    return [
        p
        for template in _templates().values()
        if (p := template.get("training_candidate") or {})
        and p.get("surface") == "rag_context_prompt"
        and p.get("resource_id") == RAG_RESOURCE
    ]


def _policy(db, subject):
    policies = [
        p
        for p in _policies()
        if subject in (p.get("growthbook", {}).get("lifecycle") or {}).get("cohort_user_ids", [])
    ]
    if len(policies) != 1:
        return None
    owner = db.get(User, policies[0].get("owner_id"))
    if (
        owner is None
        or not owner.is_admin
        or owner.deleted_at
        or owner.account_state in {"disabled", "suspended", "blocked", "deleted"}
    ):
        return None
    return policies[0]


def _context_valid(context):
    try:
        sources = [rag_service.RetrievedChunk(**s) for s in context["sources"]]
        messages = context["messages"]
        return (
            0 < len(sources) <= 50
            and all(c.content.strip() and c.doc_id and c.chunk_id for c in sources)
            and len({(c.collection_id, c.doc_id, c.chunk_id) for c in sources}) == len(sources)
            and context["block"] == rag_service.format_retrieved_block(sources)
            and bool(messages)
            and all(
                isinstance(m, dict)
                and m.get("role") in {"system", "user", "assistant"}
                and isinstance(m.get("content"), str)
                for m in messages
            )
            and context["system_index"]
            == next((i for i, m in enumerate(messages) if m["role"] == "system"), -1)
        )
    except (KeyError, TypeError, ValueError):
        return False


def _authorized(db, subject, context):
    user = db.get(User, subject, populate_existing=True)
    if (
        user is None
        or user.deleted_at
        or getattr(user, "is_active", True) is False
        or user.account_state in {"disabled", "suspended", "blocked", "deleted"}
    ):
        return False
    visible = {
        int(c.id): (str(c.owner_kind), str(c.owner_id))
        for c in rag_service.visible_collection_ids(
            db, user_id=subject, employee_id=context.get("employee_id")
        )
    }
    return all(
        visible.get(s["collection_id"]) == (s["owner_kind"], s["owner_id"])
        for s in context["sources"]
    )


def prepare(
    messages, chunks, *, user_id, employee_id, task, provider, model, allow_experiment=True
):
    """Freeze exact authorized input and exposure before the existing billed call."""
    if not chunks:
        return list(messages), None
    context = {
        "messages": deepcopy(messages),
        "sources": [c.to_dict() for c in chunks],
        "block": rag_service.format_retrieved_block(chunks),
        "system_index": next((i for i, m in enumerate(messages) if m.get("role") == "system"), -1),
        "employee_id": employee_id,
        "provider": provider,
        "model": model,
    }
    default = rag_service.RAG_SYSTEM_PROMPT
    if (
        not _context_valid(context)
        or not 1 <= len(task) <= 20000
        or len(json.dumps(context).encode()) > 200000
    ):
        return rag_service.inject_rag_into_messages(messages, chunks), None
    from modstore_server.eventing.db_outbox import enqueue
    from modstore_server.retort_experiment_runtime import (
        _enqueue_exposure,
        require_live_assignment,
        select_variant,
    )

    prompt, assignment = (
        select_variant(
            surface="rag_context_prompt",
            resource_id=RAG_RESOURCE,
            subject_id=user_id,
            default_value=default,
        )
        if allow_experiment
        else (default, None)
    )
    with get_session_factory()() as db:
        policy = _policy(db, user_id)
        if policy is None and assignment is None:
            return rag_service.inject_rag_into_messages(messages, chunks, intro=prompt), None
        if not _authorized(db, user_id, context):
            raise ValueError("rag_source_authorization_changed")
        if assignment is not None:
            require_live_assignment(db, assignment)
        observation_id = assignment["observation_id"] if assignment else str(uuid4())
        attempt = {
            "observation_id": observation_id,
            "user_id": user_id,
            "resource_id": RAG_RESOURCE,
            "measurement_scope": RAG_MEASUREMENT,
            "task": task,
            "context": context,
            "context_sha256": _digest(context),
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "training_policy_sha256": _digest(policy) if policy else "",
            "assignment": assignment,
        }
        enqueue(db, START, observation_id, attempt, event_id=f"{START}:{observation_id}")
        if assignment is not None and assignment.get("assignment_stage") != "approved_rollout":
            _enqueue_exposure(db, assignment)
        db.commit()
    return rag_service.inject_rag_into_messages(messages, chunks, intro=prompt), attempt


def get_assert(output, context):
    """Independent, deterministic metric over the exact supplied source snapshot."""
    source = context.get("vars", {}).get("generation_context") or {}
    if not _context_valid(source):
        reason = "rag_source_evidence_invalid"
    elif not isinstance(output, str) or not output.strip():
        reason = "rag_answer_empty"
    else:
        refs = [int(x) for x in re.findall(r"\[(\d+)\]", output)]
        reason = (
            "rag_citations_missing"
            if not refs
            else (
                "rag_citation_out_of_range"
                if any(n < 1 or n > len(source["sources"]) for n in refs)
                else ""
            )
        )
    return {"pass": not reason, "score": int(not reason), "reason": reason or RAG_MEASUREMENT}


def complete(attempt, *, result, duration_ms):
    """Persist the producer's outcome and independent measurement atomically; never replay."""
    from modstore_server.eventing.db_outbox import enqueue
    from modstore_server.retort_experiment_runtime import (
        enqueue_observation,
        require_live_assignment,
    )

    with get_session_factory()() as db:
        start = (
            db.query(OutboxEvent)
            .filter_by(event_id=f"{START}:{attempt['observation_id']}", producer="modstore-python")
            .first()
        )
        if (
            start is None
            or json_loads(start.payload_json, {}) != attempt
            or attempt["context_sha256"] != _digest(attempt["context"])
        ):
            raise ValueError("rag_original_request_changed")
        output = result.get("content") if isinstance(result, dict) else None
        check = get_assert(output, {"vars": {"generation_context": attempt["context"]}})
        model_ok = isinstance(result, dict) and result.get("ok") is True
        if not model_ok:
            check = {"pass": False, "reason": "rag_model_failed"}
        permitted = _authorized(db, attempt["user_id"], attempt["context"])
        if not permitted:
            check = {"pass": False, "reason": "rag_source_authorization_changed"}
        assignment = attempt.get("assignment")
        admitted = (
            permitted
            and bool(assignment)
            and assignment.get("assignment_stage") != "approved_rollout"
        )
        if assignment:
            try:
                require_live_assignment(db, assignment)
            except ValueError:
                admitted = False
        evidence = {
            key: attempt[key]
            for key in (
                "observation_id",
                "user_id",
                "resource_id",
                "measurement_scope",
                "context_sha256",
                "prompt_sha256",
            )
        } | {
            "output_sha256": hashlib.sha256(str(output or "").encode()).hexdigest(),
            "success": check["pass"],
            "reason": check["reason"],
            "business_verified": False,
            "metric_admitted": admitted,
            "training_eligible": model_ok and permitted and not check["pass"],
            "completed_at": datetime.now(UTC).isoformat(),
        }
        existing = (
            db.query(OutboxEvent)
            .filter_by(event_id=f"{COMPLETED}:{attempt['observation_id']}")
            .first()
        )
        if existing:
            previous = json_loads(existing.payload_json, {})
            if any(
                previous.get(k) != evidence.get(k)
                for k in ("context_sha256", "output_sha256", "prompt_sha256")
            ):
                raise ValueError("rag_original_result_changed")
            return previous
        enqueue(
            db,
            COMPLETED,
            attempt["observation_id"],
            evidence,
            event_id=f"{COMPLETED}:{attempt['observation_id']}",
        )
        if assignment and admitted:
            enqueue_observation(
                db,
                {**assignment, "rag_evidence_sha256": _digest(evidence)},
                result={"ok": check["pass"], "error": check["reason"] if not check["pass"] else ""},
                duration_ms=duration_ms,
            )
        db.commit()
        return evidence


def failure_records(*, days=14):
    """Read private, exact reproductions only under the current cohort and source grants."""
    from sqlalchemy import select

    if not _policies():
        return []
    records = []
    baseline = hashlib.sha256(rag_service.RAG_SYSTEM_PROMPT.encode()).hexdigest()
    with get_session_factory()() as db:
        rows = db.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.event_name == COMPLETED,
                OutboxEvent.producer == "modstore-python",
                OutboxEvent.created_at >= datetime.now(UTC) - timedelta(days=max(1, days)),
            )
            .order_by(OutboxEvent.id.desc())
            .limit(10000)
        )
        for row in rows:
            evidence = json_loads(row.payload_json, {})
            if (
                evidence.get("training_eligible") is not True
                or evidence.get("prompt_sha256") != baseline
            ):
                continue
            start = (
                db.query(OutboxEvent)
                .filter_by(event_id=f"{START}:{row.aggregate_id}", producer="modstore-python")
                .first()
            )
            original = json_loads(start.payload_json, {}) if start else {}
            policy = _policy(db, evidence.get("user_id"))
            if (
                not policy
                or original.get("observation_id") != row.aggregate_id
                or evidence.get("observation_id") != row.aggregate_id
                or original.get("user_id") != evidence.get("user_id")
                or original.get("prompt_sha256") != baseline
                or original.get("training_policy_sha256") != _digest(policy)
                or original.get("context_sha256") != evidence.get("context_sha256")
                or _digest(original.get("context")) != evidence.get("context_sha256")
                or not _context_valid(original.get("context"))
                or not _authorized(db, evidence["user_id"], original["context"])
            ):
                continue
            records.append(
                {
                    "surface": "rag_context_prompt",
                    "resource_id": RAG_RESOURCE,
                    "status": "failed",
                    "error": evidence["reason"],
                    "task_excerpt": original["task"],
                    "generation_context": original["context"],
                    "prompt_sha256": baseline,
                    "user_id": evidence["user_id"],
                    "validation_errors": [evidence["reason"]],
                    "timestamp": evidence["completed_at"],
                    "run_id": "rag-cognition:" + row.aggregate_id,
                }
            )
    return records


_PREFIX = "{% set rag_instruction %}{% raw %}"
_SUFFIX = r"""{% endraw %}{% endset %}[
{% if generation_context.system_index < 0 %}{"role":"system","content":{{ (rag_instruction + "\n\n" + generation_context.block) | dump }}},{% endif %}
{% for message in generation_context.messages %}{% if loop.index0 == generation_context.system_index %}{"role":"system","content":{{ ((message.content + "\n\n" if message.content.trim() else "") + rag_instruction + "\n\n" + generation_context.block) | dump }}}{% else %}{{ message | dump }}{% endif %}{% if not loop.last %},{% endif %}{% endfor %}]"""


def prompt_document(prompt):
    if "{% endraw" in prompt:
        raise ValueError("invalid_training_prompt_template")
    return _PREFIX + prompt + _SUFFIX


def prompt_value(document):
    if not document.startswith(_PREFIX) or not document.endswith(_SUFFIX):
        raise ValueError("training_prompt_hash_mismatch")
    return document[len(_PREFIX) : -len(_SUFFIX)]
