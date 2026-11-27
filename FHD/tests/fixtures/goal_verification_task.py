"""Original SQL verification job and signed review fixtures for checkpoint recovery."""

from __future__ import annotations

import copy
import time
from types import SimpleNamespace

import pytest

from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import goal_verification_task as checkpoint
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    build_goal_contract,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
)
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def review_task(trusted_actor, request):
    actor = trusted_actor(role="admin")
    repository = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
    run = AgentRun(str(actor.user_id), "解释库存的含义", status="running", intent="xiaox.runtime")
    run.metadata.update(runtime_type="xiaox", runtime_context=copy.deepcopy(actor.context))
    if getattr(request, "param", "") == "conversation":
        from app.application.task_conversation_store import task_conversation_store

        revision = task_conversation_store.prepare_revision(
            session_id="verification-conversation",
            user_id=actor.user_id,
        )
        run.metadata["runtime_context"].update(
            session_id="verification-conversation",
            conversation_id="verification-conversation",
            local_user_id=actor.user_id,
            _conversation_revision=revision,
        )
    contract = build_goal_contract(run)
    run.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    repository.save(run)
    store = XiaoxBindingStore(repository)
    grant = store.create(
        run.run_id,
        runtime_config={
            "provider_id": "fixture",
            "route_identity": "fixed",
            **(
                {"authorized_model_routes": ["fixed", "qualified-fallback"]}
                if getattr(request, "param", "") == "fallback"
                else {}
            ),
        },
    )
    store.update(
        run.run_id,
        lambda _run, metadata: metadata.update(
            active_seconds=0,
            active_started_at=time.time(),
            deadline_at=time.time() + 60,
        ),
    )
    output = "库存表示当前持有的货物数量。"
    job = checkpoint.begin_verification(
        store,
        run.run_id,
        generation=grant.binding.metadata["generation"],
        rows=[],
        output=output,
    )
    return SimpleNamespace(
        actor=actor,
        repository=repository,
        run_id=run.run_id,
        store=store,
        grant=grant,
        generation=grant.binding.metadata["generation"],
        output=output,
        job=job,
    )


def _review(state, *, status="verified", error_code=""):
    run = state.store.get(state.run_id).run
    contract = run.metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, [], state.output, goal_answers(run))
    body = {
        "protocol": GOAL_PROTOCOL,
        "verifier_version": checkpoint.VERIFIER_VERSION,
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": canonical_digest(state.output),
        "status": status,
        "accepted": status == "verified",
        "mode": "reply",
        "error_code": error_code,
        "attempts": [],
        "feedback": "Synthetic semantic verdict; host checks the original identities.",
        "review": {
            "goals": [
                {
                    "goal_id": "original",
                    "source_id": "request",
                    "source": run.message,
                    "kind": "reply",
                    "status": "satisfied",
                    "evidence_ids": ["response"],
                    "reason": "The candidate explains the original term.",
                }
            ],
            "violations": [],
            "uncovered_sources": [],
            "feedback": "",
        }
        if status in {"verified", "needs_work"}
        else None,
    }
    return {**body, "report_digest": canonical_digest(body)}


def _finish(state, report=None, *, store=None):
    return checkpoint.finish_verification(
        store or state.store,
        state.run_id,
        job_id=state.job["job_id"],
        generation=state.generation,
        review=report or _review(state),
    )
