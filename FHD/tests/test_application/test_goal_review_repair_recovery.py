"""A settled correction retains its original verdict after process loss."""

from __future__ import annotations

import copy

import pytest

from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime import goal_verification_task as checkpoint
from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.application.agent_runtime.verification_budget import JOB_KEY, VERIFIER_VERSION
from app.domain.task_lifecycle.agent_runtime_contract import (
    canonical_digest,
    goal_evidence_snapshot,
)
from app.domain.task_lifecycle.goal_review_models import GoalReview
from app.infrastructure.xiaox.binding import XiaoxBinding, XiaoxBindingError, XiaoxBindingStore
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.goal_verification_task import review_task as review_task
from tests.fixtures.xiaox_goal_review import goal, receipt, response, review
from tests.fixtures.xiaox_goal_review import verifier as verifier


class ProcessLost(RuntimeError):
    pass


@pytest.mark.parametrize("changed_verdict", [False, True])
@pytest.mark.parametrize("replay_origin", ["progress", "gateway"])
def test_settled_repair_replays_original_verdict_after_sql_reopen(
    review_task, verifier, changed_verdict, replay_origin
):
    state = review_task
    original = review(
        goal(state.store.get(state.run_id).run.message, kind="reply", evidence_ids=["response"]),
        goal(
            state.store.get(state.run_id).run.message,
            kind="constraint",
            status="unmet",
            evidence_ids=["response"],
        ),
    )
    corrected = copy.deepcopy(original)
    corrected["goals"][1]["goal_id"] = "second"
    if changed_verdict:
        corrected["goals"][1]["status"] = "satisfied"
    verifier.replies = [response(original), response(corrected)]

    def observed_request(_request):
        if len(verifier.requests) == 2:
            saved = state.store.get(state.run_id).run.metadata[JOB_KEY]
            assert saved["progress"]["state"] == "requesting"
            assert saved["review_repair"] == saved["progress"]["review_repair"]

    verifier.observe_request = observed_request

    def reserve_retry():
        consumed = False

        def reserve(_run, metadata):
            nonlocal consumed
            consumed = metadata.get("goal_format_retry_used", False) is False
            if consumed:
                metadata["goal_format_retry_used"] = True

        state.store.update(state.run_id, reserve)
        return consumed

    def progress(value):
        if (
            value["state"] == "response_received"
            and value["attempt"] == 2
            and replay_origin == "gateway"
        ):
            # Persist the exact settled gateway ledger shape, then lose the
            # coordinator before it can save its response_received observation.
            state.store.update(
                state.run_id,
                lambda _run, metadata: metadata.setdefault("model_requests", {}).update(
                    {
                        "settled-correction": {
                            "purpose": "verification",
                            "state": "completed",
                            "verification_job_id": state.job["job_id"],
                            "verification_input_digest": state.job["input_digest"],
                            "verification_version": VERIFIER_VERSION,
                            "verification_response": copy.deepcopy(value["response"]),
                            "verification_response_digest": value["response_digest"],
                        }
                    }
                ),
            )
            raise ProcessLost("gateway settled correction before coordinator observation")
        checkpoint.save_verification_progress(
            state.store,
            state.run_id,
            job_id=state.job["job_id"],
            generation=state.generation,
            progress=value,
        )
        if value["state"] == "response_received" and value["attempt"] == 2:
            raise ProcessLost("crash after saving correction, before comparing verdicts")

    with pytest.raises(ProcessLost):
        verify_runtime_goal(
            state.store.get(state.run_id),
            verifier.config,
            rows=[],
            output=state.output,
            consume_format_retry=reserve_retry,
            on_progress=progress,
        )
    assert len(verifier.requests) == 2
    state.store.update(
        state.run_id,
        lambda run, metadata: checkpoint.interrupted_verification(run, metadata, cancelled=False),
    )
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    job = checkpoint.begin_verification(
        reopened,
        state.run_id,
        generation=state.generation,
        rows=[],
        output=state.output,
    )
    assert job["review_repair"]["review"]["goals"][1]["status"] == "unmet"
    if replay_origin == "progress":
        replay = job["progress"]
    else:
        assert "progress" not in job
        saved = reopened.get(state.run_id).metadata["model_requests"]["settled-correction"]
        # xiaox_runtime assembles this envelope from the original gateway row.
        # It intentionally has no repair context, so the job must retain it.
        replay = {
            "state": "response_received",
            "response": saved["verification_response"],
            "verifier_version": VERIFIER_VERSION,
            "response_digest": saved["verification_response_digest"],
            "attempt": 1,
            "input": {
                key: job[key] for key in ("goal_digest", "evidence_digest", "response_digest")
            },
        }
    result = verify_runtime_goal(
        reopened.get(state.run_id),
        verifier.config,
        rows=[],
        output=state.output,
        replay_response=replay,
    )

    assert not result["accepted"]
    assert result["status"] == ("unavailable" if changed_verdict else "needs_work")
    if changed_verdict:
        assert result["error_code"] == "goal_verification_invalid_gap"
        assert result["attempts"][0]["state"] == "repair_changed_judgment"
    assert result["review"]["goals"][1]["status"] == "unmet"
    assert len(verifier.requests) == 2
    assert result["attempts"][0]["replayed_settled_response"]
    assert reopened.get(state.run_id).metadata["goal_format_retry_used"] is True
    assert reopened.get(state.run_id).run.tool_calls == []


def _repair_context(verifier):
    contract = verifier.run.metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, verifier.rows, verifier.output)
    identity = {
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": canonical_digest(verifier.output),
    }
    original = review(goal(), goal("再查询second", evidence_ids=["child-second"]))
    context = checkpoint.review_repair_checkpoint(
        identity,
        GoalReview.model_validate(original).model_dump(),
        {
            "review": original,
            "errors": ["goal_id_duplicate:first"],
            "allowed_fields": ["goal_id", "source_id", "source"],
        },
    )
    return identity, context


@pytest.mark.parametrize(
    "mutation", ["digest", "input", "version", "verdict_shape", "allowed_fields", "error_kind"]
)
def test_repair_checkpoint_rejects_stale_or_malformed_context(verifier, mutation):
    identity, context = _repair_context(verifier)
    if mutation == "digest":
        context["review"]["goals"][1]["status"] = "unmet"
    elif mutation == "input":
        context["input"]["response_digest"] = "different-candidate"
    elif mutation == "version":
        context["verifier_version"] = VERIFIER_VERSION - 1
    elif mutation == "verdict_shape":
        context["review"]["goals"][1]["status"] = "unknown"
    elif mutation == "allowed_fields":
        context["wire"]["allowed_fields"].append("status")
    else:
        context["wire"]["errors"] = ["goal_receipt_invalid:second"]
    if mutation != "digest":
        context["digest"] = canonical_digest(
            {key: value for key, value in context.items() if key != "digest"}
        )
    verifier.run.metadata[JOB_KEY] = {"review_repair": context}

    with pytest.raises(ValueError):
        checkpoint.restore_review_repair(verifier.run, None, identity)


def test_repair_context_sources_must_agree_and_restore_is_detached(verifier):
    identity, context = _repair_context(verifier)
    verifier.run.metadata[JOB_KEY] = {"review_repair": context}
    replay = {"review_repair": copy.deepcopy(context)}
    restored = checkpoint.restore_review_repair(verifier.run, replay, identity)
    assert restored == context and restored is not context
    restored["review"]["goals"][0]["status"] = "unmet"
    assert context["review"]["goals"][0]["status"] == "satisfied"
    replay["review_repair"]["review"]["goals"][0]["reason"] = "different original judgment"
    replay["review_repair"]["digest"] = canonical_digest(
        {key: value for key, value in replay["review_repair"].items() if key != "digest"}
    )
    with pytest.raises(ValueError):
        checkpoint.restore_review_repair(verifier.run, replay, identity)


def test_changed_input_starts_a_new_job_without_the_old_repair(review_task, verifier):
    state = review_task
    _, context = _repair_context(verifier)
    state.store.update(
        state.run_id, lambda run, _metadata: run.metadata[JOB_KEY].update(review_repair=context)
    )
    job = checkpoint.begin_verification(
        state.store,
        state.run_id,
        generation=state.generation,
        rows=[],
        output=state.output + " 新成稿。",
    )
    assert job["job_id"] != state.job["job_id"]
    assert "review_repair" not in job
    assert job["attempts"] == 1


def test_restored_repair_without_a_settled_response_cannot_request_another_call(verifier):
    _, context = _repair_context(verifier)
    verifier.run.metadata[JOB_KEY] = {"review_repair": context}
    verifier.run.metadata["xiaox_runtime"]["goal_format_retry_used"] = True

    result = verifier.verify()

    assert result["status"] == "unavailable" and not result["accepted"]
    assert result["error_code"] == "goal_verification_invalid_gap"
    assert verifier.requests == []


@pytest.mark.parametrize("mutation", ["input", "digest"])
def test_replayed_correction_refuses_changed_persisted_repair_context(verifier, mutation):
    identity, context = _repair_context(verifier)
    corrected = copy.deepcopy(context["wire"]["review"])
    corrected["goals"][1]["goal_id"] = "second"
    raw = response(corrected)
    if mutation == "input":
        context["input"]["response_digest"] = "different-candidate"
        context["digest"] = canonical_digest(
            {key: value for key, value in context.items() if key != "digest"}
        )
    else:
        context["review"]["goals"][1]["reason"] = "Changed after checkpoint"
    verifier.run.metadata[JOB_KEY] = {"review_repair": context}

    result = verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        replay_response={
            "state": "response_received",
            "verifier_version": VERIFIER_VERSION,
            "input": identity,
            "response": raw,
            "response_digest": canonical_digest(raw),
        },
    )

    assert not result["accepted"]
    assert result["error_code"] == "goal_verification_evidence_changed"
    assert verifier.requests == []


def test_empty_repair_context_does_not_disable_an_original_response_replay(verifier):
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    progress = []
    first = verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        on_progress=progress.append,
    )
    replay = copy.deepcopy(progress[-1])
    replay["review_repair"] = None
    result = verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        replay_response=replay,
    )

    assert first["accepted"] and result["accepted"]
    assert len(verifier.requests) == 1


@pytest.mark.parametrize("correction", ["malformed", "still_invalid"])
def test_replayed_second_correction_cannot_reserve_a_third_request(verifier, correction):
    identity, context = _repair_context(verifier)
    verifier.run.metadata[JOB_KEY] = {"review_repair": context}
    raw = response(
        context["wire"]["review"], text="not JSON" if correction == "malformed" else None
    )
    reservations = []
    result = verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        consume_format_retry=lambda: reservations.append(True) or True,
        replay_response={
            "state": "response_received",
            "verifier_version": VERIFIER_VERSION,
            "input": identity,
            "response": raw,
            "response_digest": canonical_digest(raw),
        },
    )

    assert result["status"] == "unavailable" and not result["accepted"]
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["replayed_settled_response"]
    assert result["error_code"] == (
        "goal_verification_format_invalid"
        if correction == "malformed"
        else "goal_verification_invalid_gap"
    )
    assert verifier.requests == reservations == []


@pytest.mark.parametrize("mutation", ["answer", "receipt"])
def test_sql_input_drift_blocks_a_second_request_from_a_detached_binding(
    review_task, verifier, mutation
):
    state = review_task
    binding = state.store.get(state.run_id)
    original = review(
        goal(binding.run.message, kind="reply", evidence_ids=["response"]),
        goal(binding.run.message, kind="reply", evidence_ids=["response"]),
    )
    corrected = copy.deepcopy(original)
    corrected["goals"][1]["goal_id"] = "second"
    verifier.replies = [response(original), response(corrected)]

    def reserve_retry():
        consumed = False

        def reserve(run, metadata):
            nonlocal consumed
            state.store._validate_current(run, metadata, state.generation)
            consumed = metadata.get("goal_format_retry_used", False) is False
            if consumed:
                metadata["goal_format_retry_used"] = True

        state.store.update(state.run_id, reserve)
        return consumed

    def progress(value):
        checkpoint.save_verification_progress(
            state.store,
            state.run_id,
            job_id=state.job["job_id"],
            generation=state.generation,
            progress=value,
        )
        if value["state"] == "response_received" and value["attempt"] == 1:

            def change_live_input(run, metadata):
                if mutation == "answer":
                    run.add_event(
                        "runtime.input_answered",
                        "补答",
                        {"question": "范围", "answer": "改为解释储备"},
                    )
                else:
                    metadata.setdefault("calls", {})["late-read"] = receipt("late-read")

            state.store.update(state.run_id, change_live_input)

    with pytest.raises(XiaoxBindingError) as blocked:
        verify_runtime_goal(
            binding,
            verifier.config,
            rows=[],
            output=state.output,
            consume_format_retry=reserve_retry,
            on_progress=progress,
        )

    assert blocked.value.code == "goal_verification_changed"
    assert len(verifier.requests) == 1 and len(verifier.replies) == 1
    retained = state.store.get(state.run_id).run.metadata[JOB_KEY]["progress"]
    assert retained["state"] == "response_received" and retained["attempt"] == 1
