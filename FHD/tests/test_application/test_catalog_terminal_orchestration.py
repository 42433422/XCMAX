"""Terminal consumer tests backed by real signed catalog effects and readback."""

from copy import deepcopy

import pytest

from app.application.agent_orchestrator.business_harness import (
    BUSINESS_HARNESS_PROTOCOL,
    ensure_terminal_business_result,
)
from app.application.agent_orchestrator.catalog_product_edit import action_context
from app.application.agent_orchestrator.orchestrator import (
    AgentOrchestrator,
    _verified_catalog_terminal,
)
from app.application.agent_orchestrator.run_lifecycle import requires_retry_reconciliation
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.mod_sdk import catalog_product_store as store
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_catalog_product_edits import (
    authority_images,
    dispatch,
    prepare,
    request,
    rows,
)
from tests.test_application.test_catalog_product_edits import (
    catalog as catalog,
)
from tests.test_application.test_owned_mixed_source_substrate import host as host


class RecordedTerminal:
    """Deliver a real result to StepExecution without dispatching a second effect."""

    def __init__(self, output):
        self.output = output
        self.calls = 0

    def execute_with_deadline(self, _step, *, runtime_context, deadline_monotonic):
        self.calls += 1
        return deepcopy(self.output)


def consume(c, run, result, monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "0")
    repo = InMemoryAgentRunRepository()
    run = deepcopy(run)
    run.status = "running"
    run.steps[0].status = "pending"
    repo.save(run)
    adapter = RecordedTerminal(result)
    orchestrator = AgentOrchestrator(repository=repo, tool_executor=adapter)
    orchestrator._execute_ready_steps(
        run,
        runtime_context=run.metadata["runtime_context"],
        approved_step_id=run.steps[0].step_id,
    )
    repo.save(run)
    return run, orchestrator, adapter


@pytest.mark.parametrize("fresh", [True, False])
def test_verified_current_save_completes_without_clearing_replay_fence(
    catalog, monkeypatch, tmp_path, fresh
):
    c = catalog
    run, _ = prepare(c)
    result, run = dispatch(c, run)
    if not fresh:
        result = store.verify_catalog_action(run.steps[0].params, action_context(run))
    before = authority_images(c)
    completed, orchestrator, adapter = consume(c, run, result, monkeypatch, tmp_path)
    assert completed.status == "completed"
    assert completed.steps[0].status == "completed"
    assert completed.steps[0].output["fresh_save"] is fresh
    assert completed.metadata["non_retryable"] is True
    assert requires_retry_reconciliation(completed)
    assert adapter.calls == 1
    assert authority_images(c) == before
    assert len(rows(c)) == 2
    projected = ensure_terminal_business_result(completed)
    assert projected["success"] is True
    if not fresh:
        assert "未重新保存" in projected["summary"]
    assert orchestrator.execute_dispatched_run(completed.run_id).status == "completed"
    assert adapter.calls == 1


def test_historical_save_remains_nonretryable_and_never_becomes_fresh_success(
    catalog, monkeypatch, tmp_path
):
    c = catalog
    first, _ = prepare(c)
    assert dispatch(c, first)[0]["success"]
    second, _ = prepare(c, request(c, price="13.00", period=("2026-03-01", "2026-04-01")))
    assert dispatch(c, second)[0]["success"]
    result = store.verify_catalog_action(first.steps[0].params, action_context(first))
    assert result["outcome"] == "historical_saved"
    before = authority_images(c)
    run, _, adapter = consume(c, first, result, monkeypatch, tmp_path)
    assert run.status == "completed"
    assert requires_retry_reconciliation(run)
    projected = ensure_terminal_business_result(run)
    assert projected["success"] is False
    assert "当前已有后续变更；本次未保存" in projected["summary"]
    assert run.steps[0].output["fresh_save"] is False
    assert adapter.calls == 1
    assert authority_images(c) == before
    run.final_output["business_result"] = {
        "protocol": BUSINESS_HARNESS_PROTOCOL,
        "success": True,
        "summary": "saved",
    }
    assert ensure_terminal_business_result(run)["success"] is False


def test_verified_rejection_stays_not_saved_and_nonretryable(catalog, monkeypatch, tmp_path):
    c = catalog
    run, _ = prepare(c)
    with c.factory() as db:
        db.connection().exec_driver_sql("UPDATE products SET name='changed-after-review'")
        db.commit()
    result, run = dispatch(c, run)
    assert result["operation_outcome"] == "rejected_no_effect"
    before = authority_images(c)
    rejected, _, adapter = consume(c, run, result, monkeypatch, tmp_path)
    assert rejected.status == "completed"
    assert requires_retry_reconciliation(rejected)
    projected = ensure_terminal_business_result(rejected)
    assert projected["success"] is False
    assert "已核验无副作用" in projected["summary"]
    assert rejected.steps[0].output["fresh_save"] is False
    assert rejected.steps[0].output["current_matches"] is False
    assert "未保存" in rejected.steps[0].output["message"]
    assert adapter.calls == 1
    assert authority_images(c) == before
    rejected.final_output["business_result"] = {
        "protocol": BUSINESS_HARNESS_PROTOCOL,
        "success": True,
        "summary": "saved",
    }
    projected = ensure_terminal_business_result(rejected)
    assert projected["success"] is False
    assert "已核验无副作用" in projected["summary"]


def completed_shape(run, output):
    run = deepcopy(run)
    step = run.steps[0]
    step.status = "completed"
    step.output = deepcopy(output)
    run.metadata["non_retryable"] = True
    run.tool_calls = [
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            params=deepcopy(step.params),
            status="completed",
            output=deepcopy(output),
        )
    ]
    return run


@pytest.mark.parametrize(
    "change",
    [
        "foreign-tool",
        "foreign-action",
        "action-id",
        "run-id",
        "step-id",
        "product-id",
        "bool-product-id",
        "operation-id",
        "method",
        "unverified",
        "bool-proof",
        "epoch",
        "reconciliation",
        "recovery",
        "extra-step",
        "call-mismatch",
        "missing-data",
    ],
)
def test_malformed_or_foreign_terminal_results_never_bypass_nonretryable(catalog, change):
    c = catalog
    run, _ = prepare(c)
    result, run = dispatch(c, run)
    run = completed_shape(run, result)
    step = run.steps[0]
    output = step.output
    if change == "foreign-tool":
        step.tool_id = "business_db"
    elif change == "foreign-action":
        step.action = "read"
    elif change == "action-id":
        output["business_action_id"] = "another-action"
    elif change == "run-id":
        run.run_id = "foreign-run"
    elif change == "step-id":
        step.step_id = "foreign-step"
    elif change in {"product-id", "bool-product-id", "operation-id"}:
        key = "operation_id" if change == "operation-id" else "id"
        output["data"][key] = True if change == "bool-product-id" else "foreign"
    elif change == "method":
        output["business_verification"]["method"] = "unrelated"
    elif change in {"unverified", "bool-proof"}:
        output["business_verification"]["verified"] = 1 if change == "bool-proof" else False
    elif change == "epoch":
        output["business_verification"]["epoch"] = "foreign"
    elif change == "reconciliation":
        output["reconciliation_required"] = True
    elif change == "recovery":
        run.metadata["recovery"] = {"state": "manual_reconciliation_required"}
    elif change == "extra-step":
        run.steps.append(
            AgentStep(node_id="extra", tool_id="catalog_products_v1", action="append_price")
        )
    elif change == "missing-data":
        output["data"] = None
    if change != "call-mismatch":
        run.tool_calls[0].output = deepcopy(output)
    else:
        run.tool_calls[0].output["business_action_id"] = "different"
    before = authority_images(c)
    assert not _verified_catalog_terminal(run, step)
    assert requires_retry_reconciliation(run)
    assert authority_images(c) == before


def test_self_reported_verification_cannot_replace_signed_receipt(catalog):
    c = catalog
    run, _ = prepare(c)
    result, run = dispatch(c, run)
    run = completed_shape(run, result)
    with c.factory() as db:
        db.connection().exec_driver_sql(
            "UPDATE workflow_plans SET runtime_context='{}' WHERE intent='catalog_products_v1'"
        )
        db.commit()
    before = authority_images(c)
    assert not _verified_catalog_terminal(run, run.steps[0])
    assert requires_retry_reconciliation(run)
    assert authority_images(c) == before


@pytest.mark.parametrize("change", ["method", "action-id", "reconciliation"])
def test_orchestrator_still_blocks_malformed_terminal_output(
    catalog, monkeypatch, tmp_path, change
):
    c = catalog
    run, _ = prepare(c)
    result, run = dispatch(c, run)
    if change == "method":
        result["business_verification"]["method"] = "unrelated"
    elif change == "action-id":
        result["business_action_id"] = "foreign-action"
    else:
        result["reconciliation_required"] = True
    before = authority_images(c)
    blocked, _, adapter = consume(c, run, result, monkeypatch, tmp_path)
    assert blocked.status == "blocked"
    assert requires_retry_reconciliation(blocked)
    assert ensure_terminal_business_result(blocked) == {}
    assert adapter.calls == 1
    assert authority_images(c) == before


def test_later_legitimate_edit_downgrades_stale_fresh_save_projection(
    catalog, monkeypatch, tmp_path
):
    c = catalog
    first, _ = prepare(c)
    saved, first = dispatch(c, first)
    second, _ = prepare(c, request(c, price="13.00", period=("2026-03-01", "2026-04-01")))
    assert dispatch(c, second)[0]["success"]
    before = authority_images(c)
    run, _, _ = consume(c, first, saved, monkeypatch, tmp_path)
    assert run.status == "completed"
    assert run.steps[0].status == "completed"  # Immutable original execution fact.
    assert run.steps[0].output["fresh_save"] is True
    projection = run.final_output["node_outputs"][run.steps[0].node_id]
    assert projection["outcome"] == "historical_saved"
    assert projection["fresh_save"] is False
    assert run.tool_calls[0].output == run.steps[0].output
    assert ensure_terminal_business_result(run)["success"] is False
    assert requires_retry_reconciliation(run)
    assert authority_images(c) == before


def test_pending_host_cas_cannot_be_completed_from_source_receipt_flags(catalog):
    c = catalog
    run, _ = prepare(c)
    result, run = dispatch(c, run)
    run = completed_shape(run, result)
    with c.actor.factory.begin() as db:
        db.connection().exec_driver_sql(
            "UPDATE workflow_plans SET status='pending' "
            "WHERE plan_id LIKE 'catalog-price-operation-v1:%'"
        )
    before = authority_images(c)
    assert _verified_catalog_terminal(run, run.steps[0]) is None
    assert requires_retry_reconciliation(run)
    assert authority_images(c) == before


@pytest.mark.parametrize("field", ["outcome", "operation_outcome", "binding", "runtime"])
def test_invalid_terminal_shapes_fail_closed_without_readback(field):
    step = AgentStep(
        node_id="catalog-price-review",
        tool_id="catalog_products_v1",
        action="append_price",
        params={"action": "append_price"},
        status="completed",
        output={"outcome": "success", "operation_outcome": "saved"},
    )
    run = AgentRun(
        user_id="1",
        message="shape-only negative",
        steps=[step],
        metadata={
            "catalog_price_binding": {},
            "runtime_context": {},
            "non_retryable": True,
        },
    )
    if field in {"binding", "runtime"}:
        run.metadata["catalog_price_binding" if field == "binding" else "runtime_context"] = []
    else:
        step.output[field] = {}
    assert _verified_catalog_terminal(run, step) is None
    assert requires_retry_reconciliation(run)
