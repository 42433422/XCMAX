"""Approval completion closes its original parent from SQL receipts, without replay."""

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
from app.db.models.purchase_unit import PurchaseUnit
from app.domain.task_lifecycle.agent_runtime_contract import frozen_goal_digest
from app.domain.task_lifecycle.agent_runtime_results import (
    base_runtime_result,
    classify_runtime_result,
)
from app.infrastructure.codex.binding import CodexBindingStore
from app.infrastructure.codex.tools import CodexToolBridge
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry


@pytest.fixture
def receipt_task(runtime_entry, local_tools, monkeypatch):
    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )

    state = runtime_entry
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

    def dispatch(tool, action, params):
        assert (tool, action) == ("customers", "create")
        if state.outcome == "failed":
            return {"success": False, "error": "fixture business rejection"}
        with state.actor.factory.begin() as db:
            row = PurchaseUnit(unit_name=params["unit_name"], tenant_id=state.actor.tenant_id)
            db.add(row)
            db.flush()
            customer_id = row.id
        if state.outcome == "unknown":
            return {
                "success": False,
                "outcome": "unknown",
                "retryable": False,
                "reconciliation_required": True,
            }
        return {"success": True, "data": {"id": customer_id, "unit_name": params["unit_name"]}}

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
        message="创建客户",
        status="running",
        intent="codex.runtime",
    )
    context = {**state.actor.context, "task_id": parent.run_id, "source": "codex_runtime"}
    parent.metadata.update(
        runtime_type="codex",
        runtime_context=context,
        runtime_expected_operations=[operation],
        runtime_goal_digest=frozen_goal_digest([operation], None),
        runtime_completion_mode="business",
    )
    apply_task_context(parent, context)
    state.repository.save(parent)
    state.queue.enqueue(parent)
    claim = state.queue.claim("original-parent-worker", run_id=parent.run_id, lease_seconds=120)
    assert claim is not None
    store = CodexBindingStore(state.repository)
    grant = store.create(parent.run_id)
    bridge = CodexToolBridge(store, AgentOrchestrator(repository=state.repository))
    receipt = bridge.invoke(
        grant.mcp_token, "execute_action", {"call_id": "only-write", **operation}
    )
    assert receipt["pending_approval"] is True
    rows = store.receipt_snapshot(parent.run_id)
    result = base_runtime_result(parent.run_id)
    classify_runtime_result(
        result, rows, {"expected_operations": [operation]}, "business", "completed"
    )

    def wait(parent, metadata):
        parent.status = "waiting_user"
        parent.final_output["codex_result"] = result
        metadata["runtime_status"] = "completed"

    store.update(parent.run_id, wait)
    store.close(parent.run_id, "completed")
    state.queue.finish(parent.run_id, "original-parent-worker", "waiting_approval")
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
        state.store = CodexBindingStore(state.repository)
        monkeypatch.setattr(
            gateway, "run_runtime_task", lambda **kw: pytest.fail("receipt read started model")
        )
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

    state.complete_child, state.effect_count = complete_child, effect_count
    return state


@pytest.mark.parametrize("read_child", [False, True])
def test_approved_child_read_closes_original_parent_and_queue(receipt_task, read_child):
    state = receipt_task
    state.complete_child()
    assert state.effect_count() == 1
    assert state.repository.get(state.parent_id).status != "completed"
    target = state.child_id if read_child else state.parent_id
    response = state.client.get(f"/api/agent/runs/{target}")
    assert response.status_code == 200, response.text
    parent = state.repository.get(state.parent_id)
    assert parent.status == "completed", parent.to_dict()
    result = parent.final_output["codex_result"]
    assert result["business_completed"] and result["verified_operations"]
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
    assert parent.status == ("blocked" if outcome == "unknown" else "failed"), parent.to_dict()
    assert parent.final_output["codex_result"]["business_completed"] is False
    assert state.queue.get(parent.run_id).state == "failed"
    if outcome == "unknown":
        assert parent.final_output["codex_result"]["reconciliation_required"] is True
        assert state.queue.get(parent.run_id).last_error_code == "needs_verification"
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

    def require_two(parent, metadata):
        goals = parent.metadata["runtime_expected_operations"]
        goals.append(
            {"tool_id": "products", "action": "query", "params": {"keyword": "unexecuted"}}
        )
        digest = frozen_goal_digest(goals, None)
        parent.metadata["runtime_goal_digest"] = metadata["goal_digest"] = digest

    state.store.update(state.parent_id, require_two)
    state.store.receipt_snapshot(state.parent_id)
    original = state.repository.get(state.parent_id)
    forged = copy.deepcopy(original)
    forged.metadata["runtime_expected_operations"] = forged.metadata["runtime_expected_operations"][
        :1
    ]
    digest = frozen_goal_digest(forged.metadata["runtime_expected_operations"], None)
    forged.metadata["runtime_goal_digest"] = forged.metadata["codex_runtime"]["goal_digest"] = (
        digest
    )
    assert state.queue.reconcile_codex_receipts(state.repository, forged) is None
    assert state.repository.get(state.parent_id).to_dict() == original.to_dict()
    state.queue.enqueue(original)
    assert state.queue.claim("active", run_id=state.parent_id, lease_seconds=120)
    assert state.queue.reconcile_codex_receipts(state.repository, original) is None
    assert state.repository.get(state.parent_id).to_dict() == original.to_dict()
