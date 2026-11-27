"""Approval completion resumes its original thread; GET never executes or certifies goals."""

from __future__ import annotations

import copy
import json

import pytest
from sqlalchemy import func, select

from app.application.agent_orchestrator import AgentOrchestrator, set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_models import AgentRun
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.agent_runtime import gateway
from app.application.agent_runtime.verification_budget import VERIFIER_VERSION
from app.db.models.purchase_unit import PurchaseUnit
from app.domain.task_lifecycle.agent_runtime_contract import (
    GOAL_PROTOCOL,
    build_goal_contract,
    canonical_digest,
    goal_answers,
    goal_evidence_snapshot,
    validate_goal_review,
)
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    classify_runtime_result,
)
from app.infrastructure.xiaox.binding import XiaoxBindingStore
from app.infrastructure.xiaox.tools import XiaoxToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.xiaox_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def receipt_task(runtime_entry, local_tools, monkeypatch, request):
    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )

    state = runtime_entry
    scenario = getattr(request, "param", {})
    monkeypatch.setenv("XCAGI_PRODUCT_SKU", "enterprise")
    monkeypatch.setattr(
        "app.application.agent_orchestrator.approval_grant._consumption_repository",
        lambda: SQLAlchemyApprovalConsumptionRepository(state.actor.factory),
    )
    with state.actor.factory() as db:
        PurchaseUnit.__table__.create(db.get_bind(), checkfirst=True)
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", state.actor.factory
    )
    state.outcome = "completed"

    from app.application.facades.tools_facade import execute_registered_workflow_tool

    def dispatch(tool, action, params):
        assert (tool, action) == ("customers", "create")
        if state.outcome == "failed":
            return {"success": False, "error": "fixture business rejection"}
        result = execute_registered_workflow_tool(tool, action, params)
        if state.outcome == "unknown":
            return {
                "success": False,
                "outcome": "unknown",
                "retryable": False,
                "reconciliation_required": True,
            }
        if state.outcome == "pending":
            return {**result, "success": state.acknowledged_success, "execution_state": "pending"}
        return result

    monkeypatch.setattr(
        "app.application.facades.tools_facade.execute_registered_workflow_tool", dispatch
    )
    operation = {
        "tool_id": "customers",
        "action": "create",
        "params": {"unit_name": "receipt-only"},
    }
    parent = AgentRun(
        user_id=str(state.actor.user_id),
        message=scenario.get("request", "创建客户"),
        status="running",
        intent="xiaox.runtime",
    )
    context = {**state.actor.context, "task_id": parent.run_id, "source": "xiaox_runtime"}
    parent.metadata.update(
        runtime_type="xiaox",
        runtime_context=context,
        runtime_route_identity=state.settings.route.identity,
        runtime_instruction_digest=canonical_digest("original instructions"),
        _xiaox_system_prompt="original instructions",
        _xiaox_input_data=None,
        _xiaox_history=None,
        runtime_allowed_actions=None,
        runtime_requests={},
        runtime_completion_mode="business",
    )
    contract = build_goal_contract(parent)
    parent.metadata.update(runtime_goal_contract=contract, runtime_goal_digest=contract["digest"])
    apply_task_context(parent, context)
    state.repository.save(parent)
    state.queue.enqueue(parent)
    claim = state.queue.claim("original-parent-worker", run_id=parent.run_id, lease_seconds=120)
    assert claim is not None
    store = XiaoxBindingStore(state.repository)
    grant = store.create(
        parent.run_id,
        runtime_config={
            **state.settings.route.runtime_identity(),
            "gate_required": False,
            "runtime": "xiaox",
            "model": state.settings.route.model,
            "runtime_version": "0.171.0",
            "sdk_version": "0.171.0",
            "completion_mode": "business",
            "max_active_seconds": float(state.settings.turn_timeout_seconds),
        },
    )
    store.record_thread(
        parent.run_id, "original-thread", generation=grant.binding.metadata["generation"]
    )
    bridge = XiaoxToolBridge(store, AgentOrchestrator(repository=state.repository))
    receipt = bridge.invoke(
        grant.mcp_token,
        "execute_action",
        {
            "call_id": "only-write",
            **operation,
            "schema_digest": bridge.invoke(
                grant.mcp_token,
                "capability_describe",
                {key: operation[key] for key in ("tool_id", "action")},
            )["capability"]["schema_digest"],
        },
    )
    assert receipt["pending_approval"] is True
    rows = store.receipt_snapshot(parent.run_id)
    result = base_runtime_result(parent.run_id)
    classify_runtime_result(result, rows, {"goal_contract": contract}, "business", "completed")

    def wait(parent, metadata):
        parent.status = "waiting_user"
        parent.final_output["xiaox_result"] = result
        metadata["runtime_status"] = "completed"

    store.update(parent.run_id, wait)
    store.close(parent.run_id, "completed")
    state.queue.finish(
        parent.run_id,
        "original-parent-worker",
        "waiting_approval",
        execution_count=claim.execution_count,
    )
    state.parent_id, state.child_id, state.store = parent.run_id, receipt["run_id"], store

    def complete_child():
        approval = state.client.get(f"/api/agent/runs/{state.child_id}").json()["approval"]["grant"]
        accepted = state.client.post(
            f"/api/agent/runs/{state.child_id}/continue", json={"approval_grant": approval}
        )
        assert accepted.status_code == 202, accepted.text
        state.drain(state.child_id)
        # Simulate a reopened process before the first result read.
        state.repository = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
        set_agent_run_repository_for_tests(state.repository)
        state.store = XiaoxBindingStore(state.repository)
        monkeypatch.setattr(
            "app.application.facades.tools_facade.execute_registered_workflow_tool",
            lambda *a, **kw: pytest.fail("receipt read repeated effect"),
        )

    def effect_count():
        with state.actor.factory() as db:
            return db.scalar(
                select(func.count())
                .select_from(PurchaseUnit)
                .execution_options(skip_tenant_filter=True)
            )

    state.resume_count = 0
    from app.application.agent_runtime.xiaox_runtime import run_xiaox_agent
    from tests.test_application.test_xiaox_runtime import completed

    class Transport:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def start_thread(self, **_options):
            pytest.fail("A completed child must resume the original thread")

        async def resume_thread(self, thread_id, **_options):
            assert thread_id == "original-thread"
            state.resume_count += 1
            return thread_id

        async def stream_turn(self, text, *, goal_feedback=None, output_schema=None):
            if goal_feedback is None:
                assert "创建客户" in text
            else:
                assert text is None and "原目标仍有一项条件待核对" in goal_feedback
            for event in completed(getattr(state, "corrected_answer", "原客户已创建并核验")):
                yield {**event, "thread_id": "original-thread"}

        async def interrupt(self):
            return None

    async def resumed_runtime(**kwargs):
        return await run_xiaox_agent(**kwargs, transport_factory=Transport)

    def review(
        binding,
        _config,
        *,
        rows,
        output,
        consume_format_retry,
        on_progress=None,
        replay_response=None,
    ):
        assert callable(consume_format_retry)
        contract = binding.run.metadata["runtime_goal_contract"]
        snapshot = goal_evidence_snapshot(contract, rows, output, goal_answers(binding.run))
        raw = {
            "goals": [
                {
                    "goal_id": "customer",
                    "source_id": "request",
                    "source": "创建客户",
                    "kind": "write",
                    "status": "satisfied",
                    "evidence_ids": [state.child_id],
                    "reason": "SQL business readback matches the original approved customer",
                }
            ],
            "violations": [],
            "uncovered_sources": [],
            "feedback": "",
        }
        if scenario.get("reply_goal"):
            raw["goals"].append(
                {
                    "goal_id": "verification_explanation",
                    "source_id": "request",
                    "source": scenario["reply_goal"],
                    "kind": "reply",
                    "status": "satisfied",
                    "evidence_ids": ["response"],
                    "reason": "The remaining explanation is bound to the original request",
                }
            )
        reviewed, errors = validate_goal_review(raw, contract, snapshot, output)
        assert not errors, errors
        report = {
            "protocol": GOAL_PROTOCOL,
            "verifier_version": VERIFIER_VERSION,
            "goal_digest": contract["digest"],
            "evidence_digest": snapshot["digest"],
            "response_digest": canonical_digest(output),
            "review": reviewed,
            "status": "verified",
            "accepted": True,
            "feedback": "",
        }
        return {**report, "report_digest": canonical_digest(report)}

    monkeypatch.setattr(gateway, "run_xiaox_agent", resumed_runtime)
    monkeypatch.setattr("app.application.agent_runtime.goal_verifier.verify_runtime_goal", review)
    state.complete_child, state.effect_count = complete_child, effect_count
    return state


@pytest.mark.parametrize("read_child", [False, True])
def test_approved_child_continues_original_parent_and_requires_independent_review(
    receipt_task, read_child
):
    state = receipt_task
    state.complete_child()
    assert state.effect_count() == 1
    assert state.repository.get(state.parent_id).status != "completed"
    target = state.child_id if read_child else state.parent_id
    response = state.client.get(f"/api/agent/runs/{target}")
    assert response.status_code == 200, response.text
    parent = state.repository.get(state.parent_id)
    assert parent.status == "running", json.dumps(
        {
            "error": parent.error,
            "result": parent.final_output.get("xiaox_result"),
            "child_status": state.repository.get(state.child_id).status,
        },
        ensure_ascii=False,
    )
    assert state.resume_count == 0  # GET only projects receipts.
    assert not parent.final_output["xiaox_result"]["business_completed"]
    from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs

    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    parent = state.drain(state.parent_id)
    assert state.resume_count == 1, parent.final_output.get("xiaox_result")
    assert parent.status == "completed", parent.to_dict()
    result = parent.final_output["xiaox_result"]
    assert result["business_completed"] and result["verified_operations"]
    assert not parent.metadata["xiaox_runtime"].get("goal_format_retry_used")
    assert result["goal_coverage"]["completed"] is True
    assert "等待" not in result["output"]
    assert len(parent.tool_calls) == 1
    assert state.queue.get(parent.run_id).state == "succeeded"
    task = state.repository.get_task(
        user_id=parent.user_id, tenant_id=str(state.actor.tenant_id), task_id=parent.run_id
    )
    assert task.status == "completed"
    before = parent.to_dict()
    assert state.client.get(f"/api/agent/runs/{state.parent_id}").status_code == 200
    assert state.repository.get(state.parent_id).to_dict() == before
    assert state.effect_count() == 1


@pytest.mark.parametrize("acknowledged_success", [False, True])
def test_acknowledged_pending_effect_waits_then_resumes_only_its_original_parent(
    receipt_task, monkeypatch, acknowledged_success
):
    from app.application.agent_orchestrator import verification_readback
    from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs

    state = receipt_task
    state.outcome, state.acknowledged_success = "pending", acknowledged_success
    readback = verification_readback.verify_independent_result
    source_available = False

    def delayed_readback(**kwargs):
        if not source_available:
            return {"status": "inconclusive", "code": "source_pending", "checks": []}
        return readback(**kwargs)

    monkeypatch.setattr(verification_readback, "verify_independent_result", delayed_readback)
    state.complete_child()
    child = state.repository.get(state.child_id)
    assert child.status == "blocked" and child.metadata["recovery"]["state"] == "result_pending"
    original = copy.deepcopy(child.tool_calls[0].output)
    assert original["execution_state"] == "pending" and state.effect_count() == 1
    response = state.client.get(f"/api/agent/runs/{state.parent_id}")
    assert response.status_code == 200, response.text
    parent = state.repository.get(state.parent_id)
    assert parent.status == "running", parent.final_output
    assert parent.final_output["xiaox_result"]["business_completed"] is False
    assert not parent.final_output["xiaox_result"].get("reconciliation_required")
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    source_available = True
    response = state.client.post(f"/api/agent/runs/{state.child_id}/verify")
    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is True
    child = state.drain(state.child_id)
    assert child.status == "completed", child.to_dict()
    assert child.tool_calls[0].output == original and len(child.tool_calls) == 1
    assert state.client.get(f"/api/agent/runs/{state.parent_id}").status_code == 200
    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    parent = state.drain(state.parent_id)
    assert parent.status == "completed", parent.final_output
    assert parent.final_output["xiaox_result"]["business_completed"] is True
    assert state.resume_count == 1 and state.effect_count() == 1
    assert state.queue.get(parent.run_id).state == "succeeded"


@pytest.mark.parametrize(
    "receipt_task",
    [
        {
            "request": "创建客户，并说明原客户的独立核验依据",
            "reply_goal": "说明原客户的独立核验依据",
        }
    ],
    indirect=True,
    ids=["missing_original_explanation"],
)
def test_exhausted_candidate_keeps_diagnostics_and_compensation_reviews_new_answer(
    receipt_task, monkeypatch
):
    from app.application.agent_runtime import goal_verifier
    from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs

    state = receipt_task
    state.complete_child()
    review = goal_verifier.verify_runtime_goal

    def missing_goal(
        binding,
        config,
        *,
        rows,
        output,
        consume_format_retry,
        on_progress=None,
        replay_response=None,
    ):
        report = review(
            binding, config, rows=rows, output=output, consume_format_retry=consume_format_retry
        )
        report.pop("report_digest")
        report.update(status="needs_work", accepted=False, feedback="原目标仍有一项条件待核对")
        # Keep the completed write covered. Only the distinct, original reply
        # obligation is missing; relabeling a successful write cannot authorize
        # its compensation or manufacture a new goal.
        report["review"]["goals"][1]["status"] = "unmet"
        return {**report, "report_digest": canonical_digest(report)}

    monkeypatch.setattr(goal_verifier, "verify_runtime_goal", missing_goal)
    assert resume_ready_xiaox_runs(repository=state.repository) == 1
    blocked = state.drain(state.parent_id)
    before = blocked.final_output["xiaox_result"]
    assert blocked.status == "blocked" and before["retryable"] is True
    assert before["rounds"] == 3 and before["failure_stage"] == "goal_verification"
    assert not blocked.metadata["xiaox_runtime"].get("goal_format_retry_used")
    assert "条件待核对" in before["failure_reason"]
    assert before["goal_response"] == "原客户已创建并核验"
    detail = state.client.get(f"/api/agent/runs/{state.parent_id}")
    assert detail.status_code == 200
    public = json.dumps(detail.json(), ensure_ascii=False)
    assert "条件待核对" not in public
    assert "原客户已创建并核验" not in public
    assert '"goal_response"' not in public
    events = state.client.get(f"/api/agent/runs/{state.parent_id}/events")
    assert events.status_code == 200
    replay = json.dumps(events.json(), ensure_ascii=False)
    assert "runtime.goal.verified" in replay
    assert "条件待核对" not in replay and "原客户已创建并核验" not in replay
    refreshed = state.repository.get(state.parent_id)
    assert refreshed.status == "blocked"
    for field in (
        "failure_stage",
        "failure_kind",
        "failure_reason",
        "active_seconds",
        "model_request_attempts",
    ):
        assert refreshed.final_output["xiaox_result"][field] == before[field]
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    assert state.resume_count == 1 and state.effect_count() == 1
    goal_digest = refreshed.metadata["runtime_goal_digest"]
    generation = refreshed.metadata["xiaox_runtime"]["generation"]
    monkeypatch.setattr(goal_verifier, "verify_runtime_goal", review)
    # Compensation changes the candidate, not the completed business action.
    # An unchanged candidate cannot gain a fourth review of the same evidence.
    state.corrected_answer = "原客户已创建并核验；依据是原审批客户的 SQL 独立回读与回执一致。"
    options = {
        "run_id": state.parent_id,
        "task": "继续原任务",
        "system_prompt": "original instructions",
        "runtime_context": {**state.store.get(state.parent_id).context, "turn_id": "user-retry"},
        "settings": state.settings,
        "completion_mode": "business",
    }
    queued = gateway.run_runtime_task(**options)
    assert queued["execution_state"] == "queued", queued
    assert gateway.run_runtime_task(**options)["deduplicated"] is True
    completed = state.drain(state.parent_id)
    assert completed.status == "completed", completed.final_output
    assert completed.metadata["runtime_goal_digest"] == goal_digest
    assert completed.metadata["xiaox_runtime"]["generation"] == generation + 1
    assert completed.metadata["xiaox_runtime"]["active_seconds"] >= before["active_seconds"]
    assert state.resume_count == 2 and state.effect_count() == 1
    assert completed.final_output["xiaox_result"]["failure_kind"] == ""


def test_repository_rejection_keeps_candidate_out_of_durable_public_result(receipt_task):
    from app.application.agent_orchestrator.business_harness import UNEXECUTED_ORDER_ERROR

    state = receipt_task
    parent = AgentRun(user_id=str(state.actor.user_id), message="创建销售订单", status="completed")
    parent.metadata["runtime_type"] = "xiaox"
    candidate = "候选正文：销售订单已经创建。"
    parent.final_output["xiaox_result"] = {
        **base_runtime_result(parent.run_id),
        "ok": True,
        "business_completed": True,
        "output": candidate,
        "goal_response": candidate,
        "session_messages": [{"role": "assistant", "content": candidate}],
    }
    state.repository.save(parent)
    stored = state.repository.get(parent.run_id)
    result = stored.final_output["xiaox_result"]
    assert stored.status == "failed" and stored.error == UNEXECUTED_ORDER_ERROR
    assert result["ok"] is False and result["business_completed"] is False
    assert result["goal_response"] == candidate and result["session_messages"] == []
    public = gateway.public_runtime_result(stored.to_dict())
    assert candidate not in json.dumps(public, ensure_ascii=False)


@pytest.mark.parametrize(
    "pending",
    ["coordinator", "model_reserved", "model_unknown", "lease", "open_effect", "queue_unknown"],
)
def test_unfinished_owner_or_model_cannot_be_closed_by_read(receipt_task, pending):
    state = receipt_task
    state.complete_child()
    if pending in {"open_effect", "queue_unknown"}:
        from app.db.models.agent import AgentTaskExecutionRecord
        from app.domain.task_lifecycle.control import SessionBook

        with state.queue.transaction() as db:
            execution = db.get(AgentTaskExecutionRecord, state.parent_id)
            if pending == "queue_unknown":
                execution.last_error_code = "needs_verification"
            else:
                book = SessionBook(db)
                body = book.get("agent", str(state.actor.tenant_id), state.parent_id)
                body["effects"] = ["unsettled-external-effect"]
                book.put("agent", str(state.actor.tenant_id), state.parent_id, body)
        # Snapshot settlement is legitimate; the queue guard must refuse the
        # subsequent completion even when independently verified children exist.
        state.store.receipt_snapshot(state.parent_id)
    elif pending == "lease":
        state.queue.enqueue(state.repository.get(state.parent_id))
        assert state.queue.claim("another-worker", run_id=state.parent_id, lease_seconds=120)
    else:

        def block(_run, metadata):
            if pending == "coordinator":
                metadata["coordinator_active"] = True
            else:
                metadata["model_requests"] = {"pending": {"state": pending.removeprefix("model_")}}

        state.store.update(state.parent_id, block)
    before = state.repository.get(state.parent_id).to_dict()
    assert state.client.get(f"/api/agent/runs/{state.parent_id}").status_code == 200
    after = state.repository.get(state.parent_id).to_dict()
    if pending in {"open_effect", "queue_unknown"}:
        # The existing receipt cache may touch its timestamp; no state, result,
        # event or queue promotion is allowed while the parent effect is unsettled.
        before.pop("updated_at")
        after.pop("updated_at")
        assert state.queue.get(state.parent_id).state == "waiting_approval"
    assert after == before
    assert state.effect_count() == 1


@pytest.mark.parametrize("outcome", ["failed", "unknown"])
def test_child_failure_and_unknown_are_never_promoted(receipt_task, outcome):
    state = receipt_task
    state.outcome = outcome
    state.complete_child()
    response = state.client.get(f"/api/agent/runs/{state.parent_id}")
    assert response.status_code == 200, response.text
    parent = state.repository.get(state.parent_id)
    assert parent.status == "blocked", parent.to_dict()
    assert parent.final_output["xiaox_result"]["business_completed"] is False
    # A failed tool without an original no-effect receipt is uncertain even
    # when this fixture knows no row was written. Neither case may be replayed.
    assert parent.final_output["xiaox_result"]["execution_state"] == "unknown"
    assert parent.final_output["xiaox_result"]["reconciliation_required"] is True
    assert state.queue.get(parent.run_id).state == "unknown"
    assert state.queue.get(parent.run_id).last_error_code == "needs_verification"
    assert state.queue.claim("another-worker", lease_seconds=120) is None
    assert state.effect_count() == (1 if outcome == "unknown" else 0)


def test_foreign_http_owner_cannot_trigger_reconciliation(receipt_task, trusted_actor):
    state = receipt_task
    state.complete_child()
    stranger = trusted_actor(role="user")
    before = state.repository.get(state.parent_id).to_dict()
    response = state.client.get(f"/api/agent/runs/{state.parent_id}", headers=stranger.headers)
    assert response.status_code == 403
    assert state.repository.get(state.parent_id).to_dict() == before


def test_foreign_child_receipt_cannot_complete_the_parent(receipt_task):
    from app.db.models.agent import AgentRunRecord

    state = receipt_task
    state.complete_child()
    with state.actor.factory.begin() as db:
        record = db.get(AgentRunRecord, state.child_id)
        payload = json.loads(record.payload_json)
        payload["user_id"] = "other-owner"
        record.user_id, record.payload_json = "other-owner", json.dumps(payload)
    assert state.client.get(f"/api/agent/runs/{state.parent_id}").status_code == 200
    assert state.repository.get(state.parent_id).status != "completed"
    assert state.queue.get(state.parent_id).state == "waiting_approval"


def test_queue_reconciliation_cannot_shrink_goal_or_bypass_active_lease(receipt_task):
    state = receipt_task
    state.complete_child()

    state.store.receipt_snapshot(state.parent_id)
    original = state.repository.get(state.parent_id)
    forged = copy.deepcopy(original)
    forged.message = "伪造更小的目标"
    forged.metadata["runtime_goal_contract"] = build_goal_contract(forged)
    digest = forged.metadata["runtime_goal_contract"]["digest"]
    forged.metadata["runtime_goal_digest"] = forged.metadata["xiaox_runtime"]["goal_digest"] = (
        digest
    )
    assert state.queue.reconcile_xiaox_receipts(state.repository, forged) is None
    assert state.repository.get(state.parent_id).to_dict() == original.to_dict()
    state.queue.enqueue(original)
    assert state.queue.claim("active", run_id=state.parent_id, lease_seconds=120)
    assert state.queue.reconcile_xiaox_receipts(state.repository, original) is None
    assert state.repository.get(state.parent_id).to_dict() == original.to_dict()


def test_waiting_input_rows_do_not_starve_later_approval_continuations(receipt_task):
    from app.db.models.agent import AgentRunRecord
    from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs

    state = receipt_task
    state.complete_child()
    older = AgentRun(
        user_id=str(state.actor.user_id),
        message="等待用户补充",
        status="waiting_user",
        intent="xiaox.runtime",
    )
    older.metadata.update(runtime_type="xiaox", runtime_context=state.actor.context)
    state.repository.save(older)
    with state.actor.factory() as db:
        db.get(AgentRunRecord, older.run_id).updated_at = "2000-01-01T00:00:00+00:00"
        db.commit()
    cursor = {}
    assert resume_ready_xiaox_runs(repository=state.repository, limit=1, cursor=cursor) == 0
    assert cursor["run_id"] == older.run_id
    assert resume_ready_xiaox_runs(repository=state.repository, limit=1, cursor=cursor) == 1
    assert state.queue.get(state.parent_id).state == "queued"
    assert state.effect_count() == 1


def test_late_unknown_snapshot_cannot_erase_newer_verified_child_receipt(receipt_task, monkeypatch):
    from app.application.agent_orchestrator import verification_readback
    from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs
    from app.infrastructure.xiaox.receipts import read_call_receipt

    state = receipt_task
    readback = verification_readback.verify_independent_result
    source_available = False

    def delayed_readback(**kwargs):
        if not source_available:
            return {"status": "inconclusive", "code": "source_pending", "checks": []}
        return readback(**kwargs)

    monkeypatch.setattr(verification_readback, "verify_independent_result", delayed_readback)
    state.complete_child()
    binding = state.store.get(state.parent_id)
    call = binding.metadata["calls"]["only-write"]
    # The first reader observes a stopped, still unverified write, then stalls
    # before publishing its observation. It has no authority to retry the write.
    older = read_call_receipt(state.store, binding, call)
    assert older["status"] == "unknown" and older["child_updated_at"]
    assert state.effect_count() == 1
    source_available = True
    response = state.client.post(f"/api/agent/runs/{state.child_id}/verify")
    assert response.status_code == 200, response.text
    assert response.json()["verification"]["accepted"] is True
    state.drain(state.child_id)
    current = state.store.receipt_snapshot(state.parent_id)[0]["receipt"]
    assert current["status"] == "completed" and current["verified"] is True
    assert older["child_updated_at"] < current["child_updated_at"]

    # Another process has committed the newer receipt. The delayed reader must
    # preserve it even though its own earlier observation was conservative.
    reopened = XiaoxBindingStore(SQLAlchemyAgentRunRepository(session_factory=state.actor.factory))
    reopened.record_call(state.parent_id, "only-write", receipt=older)
    parent = reopened.get(state.parent_id)
    assert parent.metadata["calls"]["only-write"]["receipt"] == current
    assert not parent.run.metadata.get("non_retryable")
    assert resume_ready_xiaox_runs(repository=reopened.repository) == 1
    assert state.queue.get(state.parent_id).state == "queued"
    assert state.effect_count() == 1


@pytest.mark.parametrize("reason", ["cancelled", "paused"])
def test_durable_revocation_survives_a_missing_final_state_write(receipt_task, reason):
    from app.infrastructure.xiaox.receipt_projection import (
        refresh_xiaox_receipts,
        resume_ready_xiaox_runs,
    )

    state = receipt_task
    # Runtime cleanup revokes first and releases ownership even if the final run
    # write fails. The older waiting status is not authority to undo that stop.
    state.complete_child()
    state.store.close(state.parent_id, reason)
    stopped = state.repository.get(state.parent_id)
    assert stopped.status in {"waiting_user", "running"}
    assert stopped.metadata["xiaox_runtime"]["close_reason"] == reason
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    assert (
        refresh_xiaox_receipts(stopped, repository=state.repository).to_dict() == stopped.to_dict()
    )
    assert state.queue.get(state.parent_id).state == "waiting_approval"
    assert state.resume_count == 0 and state.effect_count() == 1


def test_failed_wakeup_transaction_recovers_after_reopen_without_losing_child(
    receipt_task, monkeypatch
):
    from sqlalchemy.exc import OperationalError

    from app.infrastructure.xiaox.receipt_projection import resume_ready_xiaox_runs

    state = receipt_task
    state.complete_child()
    enqueue = state.queue.enqueue_in_session

    def interrupt_after_enqueue(*args, **kwargs):
        enqueue(*args, **kwargs)
        raise OperationalError("commit continuation", {}, OSError("connection interrupted"))

    monkeypatch.setattr(state.queue, "enqueue_in_session", interrupt_after_enqueue)
    assert resume_ready_xiaox_runs(repository=state.repository) == 0
    previous = state.repository.get(state.parent_id)
    assert previous.final_output["xiaox_result"]["exit_status"] == "continuation_pending"
    assert previous.metadata["runtime_requests"] == {}
    assert state.queue.get(state.parent_id).state == "waiting_approval"
    monkeypatch.setattr(state.queue, "enqueue_in_session", enqueue)
    reopened = SQLAlchemyAgentRunRepository(session_factory=state.actor.factory)
    assert resume_ready_xiaox_runs(repository=reopened) == 1
    assert resume_ready_xiaox_runs(repository=reopened) == 0
    resumed = reopened.get(state.parent_id)
    assert len(resumed.metadata["runtime_requests"]) == 1
    assert (
        resumed.metadata["xiaox_runtime"]["calls"]["only-write"]["child_run_id"] == state.child_id
    )
    assert state.queue.get(state.parent_id).state == "queued"
    assert state.resume_count == 0 and state.effect_count() == 1
