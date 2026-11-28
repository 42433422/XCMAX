"""Original-ledger review reservations, read-only authority and settled replay."""

import copy
import time

import pytest

from app.application.agent_runtime.goal_verifier import verify_runtime_goal
from app.application.agent_runtime.verification_budget import (
    JOB_HEADER,
    JOB_KEY,
    VERIFIER_VERSION,
    initialize_verification_budget,
    phase_deadline,
    verification_reserve,
)
from app.domain.task_lifecycle.agent_runtime_contract import (
    build_goal_contract,
    canonical_digest,
    goal_evidence_snapshot,
    valid_compensation_review,
    validate_goal_review,
)
from app.infrastructure.xiaox.binding import XiaoxBinding, XiaoxBindingError
from app.infrastructure.xiaox.model_gateway import MODEL_PATH, ModelGatewayContractError, _finish
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_xiaox_binding import make_binding
from tests.test_application.test_xiaox_goal_verifier import (
    goal,
    response,
    review,
)
from tests.test_application.test_xiaox_goal_verifier import (
    verifier as verifier,
)
from tests.test_application.test_xiaox_model_gateway import gateway as gateway
from tests.test_application.test_xiaox_model_gateway import post


def reserve(run, metadata, *, calls=24, seconds=120):
    return initialize_verification_budget(
        run, metadata, context_window=32000, max_model_calls=calls, total_seconds=seconds
    )


def reviewing(run, metadata):
    metadata.update(active_phase="verification", generation=1)
    run.metadata[JOB_KEY] = {
        "job_id": "verify-original",
        "generation": 1,
        "state": "running",
        "version": VERIFIER_VERSION,
        "input_digest": "original-evidence",
    }


def post_review(client, **body):
    return client.post(
        MODEL_PATH,
        headers={"authorization": "Bearer model-secret", JOB_HEADER: "verify-original"},
        json={"model": "local-agent", "input": "test", "tools": [], **body},
    )


def test_budget_is_reserved_once_inside_original_limits(gateway):
    _, store, _, _, _ = gateway
    metadata = store.binding.metadata
    budget = reserve(store.run, metadata, calls=4, seconds=40)
    assert budget["model_calls"] == 1 and budget["seconds"] == 10
    assert budget["max_model_calls"] == 3
    assert budget["cost_units"] == 32
    metadata["model_requests"] = {"first-review": {"purpose": "verification", "state": "completed"}}
    assert verification_reserve(metadata) == (1, 32)
    assert reserve(store.run, metadata) == budget
    metadata["model_requests"].update(
        {str(i): {"purpose": "verification", "state": "completed"} for i in range(2)}
    )
    assert verification_reserve(metadata) == (0, 0)
    assert "reserved_cost_units" not in store.run.metadata


@pytest.mark.parametrize("calls", [0, 1])
def test_budget_too_small_for_execution_and_review_is_rejected(gateway, calls):
    _, store, _, _, _ = gateway
    with pytest.raises(XiaoxBindingError) as error:
        reserve(store.run, store.binding.metadata, calls=calls)
    assert error.value.code == "verification_budget_insufficient"
    assert "verification_budget" not in store.binding.metadata


def test_long_judgment_keeps_original_quarter_earmark(gateway):
    _, store, _, _, _ = gateway
    assert reserve(store.run, store.binding.metadata, seconds=540)["seconds"] == 135


@pytest.mark.parametrize(
    "amount,expected_calls,ceiling",
    [(64, 1, 1), (96, 1, 2), (100, 1, 2), (128, 1, 3), (256, 2, 3), (384, 3, 3), (512, 3, 3)],
)
def test_reserve_scales_down_to_original_affordable_cost(gateway, amount, expected_calls, ceiling):
    _, store, _, _, _ = gateway
    store.run.metadata["ai_cost_budget_units"] = amount
    budget = reserve(store.run, store.binding.metadata)
    assert budget["model_calls"] == expected_calls
    assert budget["max_model_calls"] == ceiling
    assert budget["cost_units"] + 32 <= amount


@pytest.mark.parametrize(
    "calls,expected,ceiling", [(2, 1, 1), (3, 1, 2), (4, 1, 3), (8, 2, 3), (12, 3, 3), (24, 3, 3)]
)
def test_reserve_is_bounded_by_a_quarter_of_original_call_limit(gateway, calls, expected, ceiling):
    _, store, _, _, _ = gateway
    budget = reserve(store.run, store.binding.metadata, calls=calls)
    assert budget["model_calls"] == expected and expected < calls
    assert budget["max_model_calls"] == ceiling


def test_original_small_budget_keeps_a_review_slot_for_compensation_without_reset(gateway):
    _, store, _, _, _ = gateway
    store.run.metadata["ai_cost_budget_units"] = 96
    metadata = store.binding.metadata
    frozen = reserve(store.run, metadata)
    for used in range(3):
        metadata["model_requests"] = {
            str(index): {"purpose": "verification", "state": "completed"} for index in range(used)
        }
        assert verification_reserve(metadata) == ((1, 32) if used < 2 else (0, 0))
        assert reserve(store.run, metadata, calls=100) == frozen
    assert store.run.metadata["ai_cost_budget_units"] == 96


def test_old_frozen_reservation_does_not_receive_new_review_allowance(gateway):
    _, store, _, _, _ = gateway
    metadata = store.binding.metadata
    old = reserve(store.run, metadata, calls=4)
    del old["max_model_calls"]
    metadata["verification_budget"] = copy.deepcopy(old)
    metadata["model_requests"] = {"settled": {"purpose": "verification", "state": "completed"}}
    assert reserve(store.run, metadata) == old
    assert verification_reserve(metadata) == (0, 0)
    assert "max_model_calls" not in metadata["verification_budget"]


@pytest.mark.parametrize("used", [3, 4])
def test_existing_call_use_cannot_be_reset_by_initializing_a_reserve(gateway, used):
    _, store, _, _, _ = gateway
    store.binding.metadata["model_requests"] = {str(i): {"state": "completed"} for i in range(used)}
    with pytest.raises(XiaoxBindingError) as error:
        reserve(store.run, store.binding.metadata, calls=4)
    assert error.value.code == "verification_budget_insufficient"
    assert len(store.binding.metadata["model_requests"]) == used
    assert "verification_budget" not in store.binding.metadata


@pytest.mark.parametrize("amount,spent,held", [(63, 0, 0), (70, 7, 0), (70, 0, 7)])
def test_inadequate_remaining_cost_is_rejected_before_any_call(gateway, amount, spent, held):
    _, store, calls, _, _ = gateway
    store.run.metadata.update(
        ai_cost_budget_units=amount,
        ai_cost_units_total=spent,
        reserved_cost_units=held,
    )
    with pytest.raises(XiaoxBindingError) as error:
        reserve(store.run, store.binding.metadata)
    assert error.value.code == "verification_budget_insufficient"
    assert not calls and not store.binding.metadata.get("model_requests")


def test_execution_cannot_consume_final_review_call_allowance(gateway):
    client, store, calls, _, _ = gateway
    reserve(store.run, store.binding.metadata)
    store.binding.metadata["model_requests"] = {
        str(i): {"state": "completed"} for i in range(store.route_max_model_calls - 3)
    }
    assert post(client).status_code == 429 and not calls
    assert "model_call_limit" not in store.binding.metadata
    reviewing(store.run, store.binding.metadata)
    assert post_review(client).status_code == 200
    assert len(calls) == 1 and verification_reserve(store.binding.metadata) == (2, 64)


def test_execution_cannot_consume_final_review_cost_allowance(gateway):
    client, store, calls, _, _ = gateway
    reserve(store.run, store.binding.metadata)
    store.run.metadata["ai_cost_budget_units"] = 127
    assert post(client).status_code == 402 and not calls
    reviewing(store.run, store.binding.metadata)
    assert post_review(client).status_code == 200
    assert len(calls) == 1 and store.run.metadata["ai_cost_units_total"] == 2


@pytest.mark.parametrize("failure", ["forged", "missing_header", "changed_generation", "stream"])
def test_reserved_review_requires_host_phase_and_matching_job(gateway, failure):
    client, store, calls, _, _ = gateway
    reserve(store.run, store.binding.metadata)
    if failure != "forged":
        reviewing(store.run, store.binding.metadata)
    if failure == "changed_generation":
        store.run.metadata[JOB_KEY]["generation"] = 0
    result = (
        post(client)
        if failure == "missing_header"
        else post_review(client, **({"stream": True} if failure == "stream" else {}))
    )
    assert result.status_code in {400, 403} and not calls


def test_only_host_review_uses_reserved_time_and_never_extends_total_deadline(gateway):
    _, store, _, _, _ = gateway
    metadata = store.binding.metadata
    metadata["execution_deadline_at"] = time.time() - 1
    assert phase_deadline(store.run, metadata) == metadata["execution_deadline_at"]
    reviewing(store.run, metadata)
    assert phase_deadline(store.run, metadata) == metadata["deadline_at"]
    metadata["generation"] = 2
    assert phase_deadline(store.run, metadata) == metadata["execution_deadline_at"]


def test_child_envelope_leaves_review_cost_and_review_phase_cannot_dispatch(trusted_actor):
    store, run, grant = make_binding(trusted_actor())

    def initialize(parent, metadata):
        parent.metadata["ai_cost_budget_units"] = 100
        reserve(parent, metadata)

    store.update(run.run_id, initialize)
    kwargs = {
        "tool_id": "products",
        "action": "query",
        "params": {},
        "read_only": True,
        "generation": grant.binding.metadata["generation"],
    }
    child, created = store.claim_call(run.run_id, "child", **kwargs)
    assert created and child["budget_units"] == child["reservation_units"] == 68
    assert store.get(run.run_id).run.metadata["reserved_cost_units"] == 68
    store.update(run.run_id, reviewing)
    with pytest.raises(XiaoxBindingError) as error:
        store.authenticate(grant.mcp_token, "mcp")
    assert error.value.code == "verification_only"
    assert store.authenticate(grant.model_token, "model").run_id == run.run_id
    with pytest.raises(XiaoxBindingError) as error:
        store.claim_call(run.run_id, "another-child", **kwargs)
    assert error.value.code == "verification_only"


def test_gateway_keeps_settled_review_before_response_and_rejects_overwrite(gateway):
    client, store, calls, raw, _ = gateway
    reserve(store.run, store.binding.metadata)
    reviewing(store.run, store.binding.metadata)
    assert post_review(client).status_code == 200
    request_id, row = next(iter(store.binding.metadata["model_requests"].items()))
    assert row["verification_input_digest"] == "original-evidence"
    assert row["verification_response"] == raw
    assert row["verification_response_digest"] == canonical_digest(raw)
    changed = {**raw, "id": "different-response"}
    with pytest.raises(ModelGatewayContractError) as error:
        _finish(
            store,
            store.run.run_id,
            request_id,
            usage=row["usage"],
            usage_key=row["usage_key"],
            verification_response=changed,
        )
    assert error.value.code == "verification_response_conflict"
    assert row["verification_response"] == raw and len(calls) == len(store.run.llm_calls) == 1


def test_unsettled_review_never_becomes_replayable(gateway):
    client, store, calls, raw, _ = gateway
    reserve(store.run, store.binding.metadata)
    reviewing(store.run, store.binding.metadata)
    raw.pop("usage")
    assert post_review(client).status_code == 502
    assert post_review(client).status_code == 409
    row = next(iter(store.binding.metadata["model_requests"].values()))
    assert row["state"] == "unknown" and "verification_response" not in row
    assert len(calls) == 1


def check(verifier, **kwargs):
    return verify_runtime_goal(
        XiaoxBinding(verifier.run),
        verifier.config,
        rows=verifier.rows,
        output=verifier.output,
        **kwargs,
    )


def test_settled_progress_replays_without_second_model_request(verifier):
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    progress = []
    first = check(verifier, on_progress=progress.append)
    assert first["accepted"] and [item["state"] for item in progress] == [
        "requesting",
        "response_received",
    ]
    second = check(verifier, replay_response=progress[-1])
    assert second["accepted"] and len(verifier.requests) == 1
    assert second["attempts"][0]["replayed_settled_response"]


def test_host_review_header_and_pre_request_checkpoint_precede_model_io(verifier):
    metadata = verifier.run.metadata["xiaox_runtime"]
    reserve(verifier.run, metadata)
    reviewing(verifier.run, metadata)
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    progress = []

    def observed_request(request):
        assert progress[-1]["state"] == "requesting"
        assert request.headers[JOB_HEADER] == "verify-original"

    verifier.observe_request = observed_request
    assert check(verifier, on_progress=progress.append)["accepted"]
    assert progress[-1]["state"] == "response_received"


@pytest.mark.parametrize("change", ["evidence", "response", "version"])
def test_replay_refuses_changed_evidence_response_or_verifier(verifier, change):
    verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    progress = []
    check(verifier, on_progress=progress.append)
    original = copy.deepcopy(progress[-1])
    if change == "evidence":
        verifier.rows[0]["receipt"]["message"] = "changed-receipt"
    elif change == "response":
        original["response"]["id"] = "changed-response"
    else:
        original["verifier_version"] += 1
    result = check(verifier, replay_response=original)
    assert not result["accepted"] and result["error_code"] == "goal_verification_evidence_changed"
    assert len(verifier.requests) == 1


def test_old_verifier_report_cannot_skip_current_review(verifier):
    valid = response(review(goal(), goal("再查询second", goal_id="second")))
    verifier.replies = [valid, valid]
    report = check(verifier)
    report["verifier_version"] = VERIFIER_VERSION - 1
    report["report_digest"] = canonical_digest(
        {k: v for k, v in report.items() if k != "report_digest"}
    )
    verifier.run.metadata["runtime_goal_verification"] = report
    assert check(verifier)["accepted"] and len(verifier.requests) == 2


@pytest.mark.parametrize("defect", ["new_goal", "source_id", "evidence", "schema"])
@pytest.mark.parametrize("persisted", [False, True])
def test_invalid_gap_cannot_become_new_or_cached_compensation(verifier, defect, persisted):
    verifier.rows = verifier.rows[:1]
    raw = review(
        goal(),
        goal("再查询second", goal_id="second", status="unmet", evidence_ids=[]),
        feedback="仅补原始second查询。",
    )
    contract = verifier.run.metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, verifier.rows, verifier.output)
    assert valid_compensation_review(raw, contract, snapshot, verifier.output)
    if persisted:
        verifier.replies = [response(raw)]
        previous = check(verifier)
        assert previous["status"] == "needs_work"
        raw = previous["review"]
    missing = raw["goals"][1]
    if defect == "new_goal":
        missing["source"] = "新建未经原请求要求的付款"
    elif defect == "source_id":
        missing["source_id"] = "history"
    elif defect == "evidence":
        missing["evidence_ids"] = ["child-does-not-exist"]
    else:
        missing["kind"] = "approve_and_pay"
    assert not valid_compensation_review(raw, contract, snapshot, verifier.output)
    if persisted:
        previous["report_digest"] = canonical_digest(
            {key: value for key, value in previous.items() if key != "report_digest"}
        )
        verifier.run.metadata["runtime_goal_verification"] = copy.deepcopy(previous)
    else:
        verifier.replies = [response(raw)]
    result = check(verifier)
    assert result["status"] == "unavailable" and not result["accepted"]
    assert result["error_code"] == (
        "goal_verification_format_invalid"
        if defect == "schema" and not persisted
        else "goal_verification_invalid_gap"
    )
    assert len(verifier.requests) == 1
    assert verifier.rows[0]["receipt"]["verified"]


def test_compensation_validation_allows_original_unmet_objective_without_declaring_success(
    verifier,
):
    verifier.run.metadata["runtime_context"]["_runtime_goal_constraints"] = {
        "objective": "查询second"
    }
    contract = build_goal_contract(verifier.run)
    verifier.run.metadata["runtime_goal_contract"] = contract
    verifier.rows = verifier.rows[:1]
    raw = review(
        goal(),
        goal(
            "查询second", goal_id="second", source_id="objective", status="unmet", evidence_ids=[]
        ),
    )
    snapshot = goal_evidence_snapshot(contract, verifier.rows, verifier.output)
    assert valid_compensation_review(raw, contract, snapshot, verifier.output)
    _, completion_errors = validate_goal_review(raw, contract, snapshot, verifier.output)
    assert completion_errors
    verifier.replies = [response(raw)]
    result = check(verifier)
    assert result["status"] == "needs_work" and not result["accepted"]
    assert result["review"]["goals"][1]["source_id"] == "objective"


@pytest.mark.parametrize("defect", [None, "evidence_id", "source_excerpt"])
def test_unmet_file_goal_can_lack_complete_input_but_cannot_supply_fabricated_citations(
    verifier,
    defect,
):
    raw = review(
        {**goal(), "file_basis": "independent"},
        {
            **goal("再查询second", goal_id="second", status="unmet", evidence_ids=[]),
            "file_basis": "complete",
            "file_citations": [
                {
                    "evidence_id": "current-file",
                    "source_excerpt": "已读取局部内容",
                    "response_excerpt": verifier.output,
                }
            ],
        },
    )
    file_evidence = {
        "current-file": {"text": "已读取局部内容，其余尚待核对。", "coverage": {"truncated": True}}
    }
    contract = verifier.run.metadata["runtime_goal_contract"]
    snapshot = goal_evidence_snapshot(contract, verifier.rows[:1], verifier.output)
    if defect:
        raw["goals"][1]["file_citations"][0][defect] = "fabricated"
    assert valid_compensation_review(
        raw,
        contract,
        snapshot,
        verifier.output,
        file_evidence=file_evidence,
    ) is (defect is None)
    _, errors = validate_goal_review(
        raw,
        contract,
        snapshot,
        verifier.output,
        file_evidence=file_evidence,
    )
    assert errors  # A real partial source still does not satisfy the original goal.
