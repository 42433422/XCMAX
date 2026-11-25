"""Public errors retain failure/state contracts without exposing backend diagnostics."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.application.admin_control.protocols import ErrorPolicy
from app.fastapi_routes.admin_control.profiles import UserProfiles
from app.fastapi_routes.admin_control.synchronization import Synchronization
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.test_application.test_codex_tools import _invoke
from tests.test_application.test_codex_tools import bridge_setup as bridge_setup

PRIVATE = "Traceback /private/state.sqlite token=secret-boundary-test"
ERRORS = ErrorPolicy(lambda: (OSError, ValueError, RuntimeError), logging.getLogger(__name__))


def _fail(*args, **kwargs):
    raise OSError(PRIVATE)


def test_profile_database_failure_is_private_and_success_keeps_identity_mapping():
    profiles = UserProfiles(
        errors=ERRORS, valid_tiers=lambda: {"personal"}, gate=lambda _: None, repository=_fail
    )
    for response in (
        asyncio.run(profiles.admin_list_user_profiles(None)),
        asyncio.run(profiles.admin_set_user_profile(None, 7, {"username": "alice"})),
    ):
        assert response.status_code == 500
        assert PRIVATE not in response.body.decode()
        assert json.loads(response.body)["success"] is False
    row = {"username": "alice", "market_user_id": 7, "tier": "personal"}
    profiles._repository = lambda: nullcontext(SimpleNamespace(list_profiles=lambda: [row]))
    result = asyncio.run(profiles.admin_list_user_profiles(None))
    assert result["success"] is True
    assert result["by_market_user_id"]["7"] == result["data"]["alice"]
    assert result["data"]["alice"]["tier"] == "personal"


def test_sync_failure_stays_visible_without_exposing_database_error():
    sync = Synchronization(
        errors=ERRORS,
        store=_fail,
        poll_interval=lambda: 0,
        remote_host=lambda: "localhost",
        remote_port=lambda: 1,
        stream=None,
    )
    result = asyncio.run(sync.sync_changes(0, 10))
    assert result == {"success": True, "data": [], "count": 0, "note": "同步变更暂时无法读取"}
    response = asyncio.run(sync.sync_receive({"entity": "fixture"}))
    assert response.status_code == 500
    assert json.loads(response.body)["success"] is False
    assert PRIVATE not in response.body.decode()

    async def read_error_event():
        async def connected():
            return False

        events = sync._sync_sse_generator(SimpleNamespace(is_disconnected=connected), 17)
        assert json.loads((await anext(events))[6:])["cursor"] == 17
        event = json.loads((await anext(events))[6:])
        await events.aclose()
        return event

    assert asyncio.run(read_error_event()) == {"type": "error", "message": "同步数据暂时不可用"}
    changes = [{"id": 18, "entity": "fixture"}]
    sync._store = lambda: SimpleNamespace(get_changes=lambda **_: changes)
    assert asyncio.run(sync.sync_changes(17, 10))["data"] == changes


def test_semantic_router_failure_has_safe_status_and_can_be_reloaded(monkeypatch):
    from app.domain.shared_services import intent_semantic_router as router

    monkeypatch.setattr(router, "_router", None)
    monkeypatch.setattr(router, "_router_error", "")
    monkeypatch.setattr(router, "_route_count", 0)
    monkeypatch.setattr(router, "_intent_by_tool", {})
    monkeypatch.setattr(router, "semantic_enabled", lambda: True)
    monkeypatch.setattr(router, "_build_router", _fail)
    assert router.get_semantic_router() is None
    status = router.semantic_router_status()
    assert status["loaded"] is False and status["error"] == "semantic_router_unavailable"
    assert PRIVATE not in json.dumps(status)
    ready = SimpleNamespace(routes=["search"])
    monkeypatch.setattr(router, "_build_router", lambda: (ready, {"search": "search"}))
    router.reload_semantic_router()
    assert router.get_semantic_router() is ready
    assert router.semantic_router_status()["error"] is None


@pytest.mark.parametrize("failed", [False, True])
def test_approval_executor_outcome_and_ledger_do_not_store_exception_text(
    tmp_path, monkeypatch, failed
):
    from app.application.autonomy import approval_resume as approval

    ledger = tmp_path / "approvals.jsonl"
    monkeypatch.setenv("XCAGI_AUTONOMY_APPROVAL_LEDGER_PATH", str(ledger))
    monkeypatch.setattr(approval, "append_autonomy_audit", lambda _: None)
    row = {"action_id": "fixture", "action": "fixture", "state": "approved", "approver": "owner"}
    approval._append_ledger(row)
    executor = _fail if failed else lambda _: {"ok": True, "receipt": "accepted"}
    monkeypatch.setattr(approval, "_claim_action", lambda *a, **kw: (row, executor))
    result = approval.resume_action("fixture", approver="owner")
    assert result["state"] == ("execution_failed" if failed else "executed")
    assert result["outcome"]["ok"] is (not failed)
    if failed:
        assert result["outcome"]["error"] == "action_execution_failed"
    else:
        assert result["outcome"]["receipt"] == "accepted"
    assert PRIVATE not in ledger.read_text()
    assert approval.get_action_state("fixture")["state"] == result["state"]


def test_memory_filter_failure_has_code_and_does_not_leak_store_diagnostics():
    from app.application.dataset_rag_app_service import DatasetAccessContext
    from app.application.persy_memory_app_service import PersyMemoryApplicationService

    def invalid_filter(*args, **kwargs):
        raise ValueError(PRIVATE)

    store = SimpleNamespace(list_memories=invalid_filter)
    service = PersyMemoryApplicationService(store)
    access = DatasetAccessContext(
        actor_id="7", tenant_id="2", permissions=frozenset({"dataset.read"})
    )
    result = service.list_memories(access_context=access)
    assert result == {
        "success": False,
        "message": "memory status or type filter is invalid",
        "error_code": "persy_memory_invalid_filter",
    }
    store.list_memories = lambda *args, **kwargs: []
    result = service.list_memories(access_context=access)
    assert result["success"] is True and result["memories"] == []


def test_domain_validation_messages_preserve_actionable_input_errors():
    from app.application.sales_quote_inputs import validated_quote_request
    from app.domain.app_pure.inventory_inputs import validate_stock_in_request

    stock = {"product_id": 1, "warehouse_id": 2, "quantity": PRIVATE}
    with pytest.raises(ValueError, match="^入库数量必须是有效正数$"):
        validate_stock_in_request(stock)
    stock["quantity"] = 2
    assert validate_stock_in_request(stock) is None
    quote = {
        "customer_id": 1,
        "items": [{"model_number": "demo", "quantity": PRIVATE, "unit_price": 10}],
    }
    with pytest.raises(ValueError, match="^第 1 项数量必须是有效数字$"):
        validated_quote_request(quote)
    quote["items"][0]["quantity"] = 2
    assert validated_quote_request(quote)[0]["quantity"] == 2


def test_shared_chat_boundary_keeps_successful_waiting_confirmation_reply():
    from app.fastapi_routes.ai_intent import _public_unified_chat_payload

    reply = {
        "success": True,
        "response": "请选择目标表后继续",
        "run_id": "waiting-run",
        "data": {
            "action": "workflow_waiting",
            "data": {
                "approval_request_id": "waiting-approval",
                "questions": ["确认目标表"],
                "execution": {"committed": False, "effect": "partial", "outcome": "unknown"},
            },
        },
    }
    assert _public_unified_chat_payload(reply) is reply


@pytest.mark.parametrize(
    "outcome,committed",
    [("partial", True), ("unknown", False), ("not_executed", False)],
)
def test_shared_chat_failure_boundary_preserves_nested_execution_receipt(outcome, committed):
    from app.fastapi_routes.ai_intent import _public_unified_chat_payload

    execution = {
        "committed": committed,
        "effect": "none" if outcome == "not_executed" else outcome,
        "outcome": outcome,
    }
    result = _public_unified_chat_payload(
        {
            "success": False,
            "response": PRIVATE,
            "run_id": "existing-run",
            "data": {
                "data": {
                    "plan_id": "existing-plan",
                    "approval_request_id": "existing-approval",
                    "execution": {**execution, "error": PRIVATE},
                }
            },
        }
    )
    assert result["data"]["data"]["execution"] == execution
    assert (
        result["run_id"] == "existing-run" and result["approval_request_id"] == "existing-approval"
    )
    assert result["plan_id"] == "existing-plan" and PRIVATE not in json.dumps(result)
    if outcome == "not_executed":
        assert result["execution_state"] == "not_executed"
        assert result.get("requires_reconciliation") is not True
    else:
        assert result["_http_status"] == 409
        assert result["requires_reconciliation"] and result["retryable"] is False


@pytest.mark.parametrize(
    "outcome,committed",
    [("partial", True), ("unknown", False), ("not_executed", False)],
)
def test_shared_chat_failure_boundary_preserves_top_level_execution_receipt(outcome, committed):
    """Actual workflow response builder emits a root execution receipt on failure."""
    from app.fastapi_routes.ai_intent import _public_unified_chat_payload

    execution = {
        "committed": committed,
        "effect": "none" if outcome == "not_executed" else outcome,
        "outcome": outcome,
    }
    result = _public_unified_chat_payload(
        {
            "success": False,
            "response": PRIVATE,
            "run_id": "existing-run",
            "execution": {**execution, "internal_diagnostic": PRIVATE},
            "data": {
                "data": {
                    "plan_id": "existing-plan",
                    "approval_request_id": "existing-approval",
                }
            },
        }
    )
    assert result["execution"] == execution
    assert result["data"]["data"]["execution"] == execution
    assert result["run_id"] == "existing-run"
    assert result["plan_id"] == "existing-plan"
    assert result["approval_request_id"] == "existing-approval"
    assert PRIVATE not in json.dumps(result)
    if outcome == "not_executed":
        assert result["execution_state"] == "not_executed"
        assert result.get("requires_reconciliation") is not True
    else:
        assert result["_http_status"] == 409
        assert result["requires_reconciliation"] is True
        assert result["retryable"] is False


@pytest.mark.parametrize("next_state", ["unknown", "failed", "cancelled"])
def test_shared_chat_current_runtime_partial_write_requires_reconciliation(next_state):
    """The current Codex runtime retains confirmed writes after later failures."""
    from app.application.agent_runtime.chat import runtime_chat_payload
    from app.domain.task_lifecycle.agent_runtime_results import classify_runtime_result
    from app.fastapi_routes.ai_intent import _public_unified_chat_payload

    rows = [
        {
            "state": "completed",
            "read_only": False,
            "tool_id": "materials",
            "action": "create",
            "call_id": "original-material-write",
            "receipt": {"status": "completed", "success": True, "verified": True},
        },
        {
            "state": next_state,
            "read_only": False,
            "tool_id": "shipment_records",
            "action": "create",
            "call_id": "original-shipment-write",
            "receipt": {"status": next_state, "success": False, "error": PRIVATE},
        },
    ]
    runtime = {"run_id": "original-run", "output": PRIVATE}
    assert classify_runtime_result(runtime, rows, {}, "business", "failed") == "blocked"
    assert runtime["business_receipts"][0]["receipt"]["verified"] is True
    assert runtime["execution_state"] == ("unknown" if next_state == "unknown" else "partial")

    transport = runtime_chat_payload(runtime, conversation_id="original-session")
    assert transport["runtime_context_update"]["agent_runtime_run_id"] == "original-run"
    assert transport["requires_reconciliation"] is True
    public = _public_unified_chat_payload(transport)
    assert public["success"] is False
    assert public["run_id"] == "original-run"
    assert public["requires_reconciliation"] is True
    assert public["retryable"] is False
    assert public["_http_status"] == 409
    assert "勿重复提交" in public["message"]
    assert PRIVATE not in json.dumps(public, ensure_ascii=False)


@pytest.mark.parametrize("read_only", [True, None])
def test_failed_step_only_discards_prior_effect_when_proven_read_only(read_only):
    """Unknown effect kind is not an authorization to restart completed work."""
    from app.domain.task_lifecycle.agent_runtime_results import classify_runtime_result

    prior = {
        "state": "completed",
        "receipt": {"status": "completed", "success": True, "verified": True},
    }
    if read_only is not None:
        prior["read_only"] = read_only
    rows = [
        prior,
        {"state": "failed", "receipt": {"status": "failed", "success": False}},
    ]
    result = {"run_id": "original-run"}
    classified = classify_runtime_result(result, rows, {}, "business", "failed")
    if read_only is True:
        assert classified == "failed"
        assert result.get("reconciliation_required") is not True
    else:
        assert classified == "blocked"
        assert result["execution_state"] == "partial"
        assert result["reconciliation_required"] is True
        assert result["retryable"] is False


@pytest.fixture
def recovered_bound_receipts(bridge_setup, monkeypatch, tmp_path):
    """Original host rejection and independently read-back write, both actually approved."""
    from app.application.agent_orchestrator.approval_consumption_repository import (
        SQLAlchemyApprovalConsumptionRepository,
    )
    from app.utils.resilience import rate_limiter
    from tests.test_application.test_agent_user_decision_pause import _approve_and_execute

    setup = bridge_setup
    # This regression asserts persisted receipt recovery, not process isolation:
    # run the real tool in-process so host-specific worker spawn cannot fail setup.
    executor = setup.bridge.orchestrator._tool_executor

    from app.utils.operational_errors import BOUNDARY_ERRORS

    def execute_in_process(step, *, runtime_context, deadline_monotonic):
        try:
            return executor.execute(step, runtime_context=runtime_context)
        except BOUNDARY_ERRORS as exc:
            import traceback

            print(traceback.format_exc()[:4000])
            print(
                f"RECEIPT_TOOL_FAILURE {type(exc).__name__}: {exc} "
                f"cwd={os.getcwd()} db_url={os.environ.get('DATABASE_URL')} "
                f"data_dir={os.environ.get('XCAGI_DATA_DIR')} "
                f"tool={step.tool_id}.{step.action}"
            )
            raise

    executor.execute_with_deadline = execute_in_process
    import weakref
    from pathlib import Path

    from app.application.agent_orchestrator import task_execution_repository

    # A prior test's open queue repository may point at a cleaned temp database.
    monkeypatch.setattr(task_execution_repository, "_OPEN_REPOSITORIES", weakref.WeakSet())
    monkeypatch.setattr(task_execution_repository, "_task_execution_repository", None)
    monkeypatch.delenv("XCAGI_OWNED_SOURCE_PROFILE", raising=False)
    data_dir = Path(os.environ.get("XCAGI_DATA_DIR") or tmp_path / "app-data")
    data_dir.mkdir(parents=True, exist_ok=True)
    owner_engine = setup.actor.factory.kw["bind"]
    owner_path = Path(str(owner_engine.url.database))
    owner_path.parent.mkdir(parents=True, exist_ok=True)
    owner_path.touch(exist_ok=True)
    from app.db.db_base import Base

    Base.metadata.create_all(owner_engine, checkfirst=True)
    for target in (
        "app.mod_sdk.erp_repository_registry.resolve_customers_session",
        "app.application.customer_app_service.get_customers_session",
        "app.application.customer_crud_mixin.get_customers_session",
        "app.application.customer_relationship_mixin.get_customers_session",
        "app.application.customer_transfer_mixin.get_customers_session",
    ):
        monkeypatch.setattr(target, setup.actor.factory, raising=False)
    monkeypatch.setenv("XCAGI_TOOL_IDEMPOTENCY_PATH", str(tmp_path / "original-claims.sqlite"))
    monkeypatch.setattr(
        "app.application.customer_app_service.get_customers_session", setup.actor.factory
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.approval_grant._consumption_repository",
        lambda: SQLAlchemyApprovalConsumptionRepository(setup.actor.factory),
    )
    endpoint = "agent-tool:customers.create"
    monkeypatch.setitem(
        rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(120)
    )
    for _ in range(120):
        assert rate_limiter.check_rate_limit(str(setup.actor.tenant_id), endpoint)["allowed"]

    for call_id in ("original-rejection", "verified-write"):
        pending = _invoke(
            setup.bridge,
            setup.grant.mcp_token,
            "execute_action",
            {
                "call_id": call_id,
                "tool_id": "customers",
                "action": "create",
                "params": {"unit_name": call_id},
            },
        )
        assert pending["pending_approval"] is True
        _approve_and_execute(
            setup.bridge.orchestrator,
            setup.store.repository.get(pending["run_id"]),
            setup.actor,
        )
        receipt = _invoke(
            setup.bridge, setup.grant.mcp_token, "task_evidence", {"call_id": call_id}
        )
        if call_id == "original-rejection":
            assert receipt["status"] == "failed" and receipt["success"] is False
            assert receipt["execution"] == {"outcome": "not_executed", "committed": False}
            monkeypatch.setitem(
                rate_limiter._rate_limiters, endpoint, rate_limiter._InMemoryRateLimiter(120)
            )
        else:
            assert receipt["success"] is True and receipt["verified"] is True, (
                receipt.get("status"),
                receipt.get("error_code"),
                receipt.get("error_type"),
                receipt.get("error"),
                receipt.get("execution"),
            )
    return setup


@pytest.mark.parametrize(
    "case,completed",
    [
        ("proven", True),
        # An added history row does not establish a second authorized invocation
        # of this bridge's single frozen action, even if both outputs assert no effect.
        ("history_proven", False),
        ("missing_proof", False),
        ("committed", False),
        ("unknown", False),
        ("effect", False),
        ("nested_committed", False),
        ("nested_missing_proof", False),
        ("nested_invalid_proof", False),
        ("success", False),
        ("nested_success", False),
        ("record_mismatch", False),
        ("output_mismatch", False),
        ("missing_record", False),
        ("history_unknown", False),
        ("history_success", False),
        ("history_mismatch", False),
        ("cancelled", False),
        ("rejected", False),
        ("stale_goal", False),
        ("missing_goal", False),
    ],
)
def test_recovered_write_no_effect_receipt_requires_verified_goal(
    recovered_bound_receipts, case, completed
):
    """Reopen real frozen receipts; corrupt storage must never manufacture recovery proof."""
    from app.application.agent_orchestrator.result_verification import (
        _binding_valid,
        bind_execution_receipt,
        freeze_verification_contract,
    )
    from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.db.models.agent import AgentRunRecord
    from app.domain.task_lifecycle.agent_runtime_contract import (
        GOAL_PROTOCOL,
        canonical_digest,
        goal_evidence_snapshot,
        goal_report_coverage,
    )
    from app.domain.task_lifecycle.agent_runtime_results import (
        base_runtime_result,
        classify_runtime_result,
    )
    from app.infrastructure.codex.binding import CodexBindingStore

    setup = recovered_bound_receipts
    repository = setup.store.repository
    original = repository.get(setup.run.run_id)
    calls = setup.store.get(original.run_id).metadata["calls"]
    child = repository.get(calls["original-rejection"]["child_run_id"])
    step, record = child.steps[0], child.tool_calls[0]
    output = copy.deepcopy(step.output)
    if case == "missing_proof":
        output.pop("execution")
    elif case == "committed":
        output["execution"]["committed"] = True
    elif case == "unknown":
        output["execution"]["outcome"] = "unknown"
    elif case == "effect":
        output["execution"]["effect"] = "changed"
    elif case == "success":
        output["success"] = True
    elif case == "nested_success":
        output["data"] = {"success": True}
    elif case == "nested_committed":
        output["result"] = {"execution": {"outcome": "partial", "committed": True}}
    elif case == "nested_missing_proof":
        output["result"] = {"execution": {}}
    elif case == "nested_invalid_proof":
        output["result"] = {"execution": "unbound model assertion"}
    step.output, record.output = copy.deepcopy(output), copy.deepcopy(output)
    if output != repository.get(child.run_id).steps[0].output:
        # Keep these contradictory envelopes internally bound so rejection must
        # come from their semantics, not merely from a stale output digest.
        bind_execution_receipt(record)
        assert _binding_valid(
            child,
            step,
            record,
            child.metadata["runtime_context"],
            record.metadata["verification_contract"],
        )
    records = [record]
    if case == "record_mismatch":
        record.params = {"name": "other-operation"}
    elif case == "output_mismatch":
        record.output["error"] = "different_execution"
    elif case == "missing_record":
        records = []
    elif case.startswith("history_"):
        historical = copy.deepcopy(record)
        historical.call_id += "-previous"
        historical.output["error"] = "earlier_attempt"
        if case == "history_unknown":
            historical.output.update(status="unknown")
        elif case == "history_success":
            historical.output.update(success=True)
        elif case == "history_mismatch":
            historical.params = {"name": "other-operation"}
        freeze_verification_contract(
            child,
            step,
            historical,
            get_tool_action_spec(step.tool_id, step.action),
            child.metadata["runtime_context"],
        )
        bind_execution_receipt(historical)
        records.insert(0, historical)
    child.tool_calls = records
    if case in {"cancelled", "rejected"}:
        child.status = case
    # Only fault injection bypasses normal frozen-record persistence. No test
    # fabricates a successful business receipt or a production approval grant.
    with setup.actor.factory.begin() as db:
        stored = db.get(AgentRunRecord, child.run_id)
        stored.payload_json = json.dumps(child.to_dict(), ensure_ascii=False, default=str)
        stored.status = child.status
    reopened = CodexBindingStore(SQLAlchemyAgentRunRepository(session_factory=setup.actor.factory))
    rows = reopened.receipt_snapshot(original.run_id)
    failed = next(row for row in rows if row["call_id"] == "original-rejection")
    verified = next(row for row in rows if row["call_id"] == "verified-write")
    assert verified["receipt"]["success"] is True and verified["receipt"]["verified"] is True
    produced = failed["receipt"]
    assert produced["success"] is False and produced["verified"] is False
    if case in {"proven", "stale_goal", "missing_goal"}:
        assert produced.get("execution") == {
            "outcome": "not_executed",
            "committed": False,
        }
    else:
        assert "execution" not in produced
    contract = original.metadata["runtime_goal_contract"]
    output = "已完成原客户记录并核验"
    snapshot = goal_evidence_snapshot(contract, rows, output)
    report = {
        "protocol": GOAL_PROTOCOL,
        "goal_digest": contract["digest"],
        "evidence_digest": snapshot["digest"],
        "response_digest": canonical_digest(output),
        "status": "verified",
        "accepted": True,
        "review": {
            "goals": [
                {
                    "goal_id": "customer-goal",
                    "source_id": "request",
                    "source": original.message,
                    "kind": "write",
                    "status": "satisfied",
                    "evidence_ids": [verified["child_run_id"]],
                    "reason": "独立核验最终写入",
                }
            ],
            "violations": [],
            "uncovered_sources": [],
            "feedback": "",
        },
    }
    report["report_digest"] = canonical_digest(report)
    assert goal_report_coverage(contract, rows, output, None, report)["completed"] is True
    if case == "stale_goal":
        report["evidence_digest"] = "stale-evidence"
    elif case == "missing_goal":
        report = {}

    result = {**base_runtime_result(original.run_id), "output": output}
    state = classify_runtime_result(
        result,
        rows,
        {"goal_contract": contract, "goal_verification": report},
        "business",
        "completed",
    )
    if completed:
        assert state == "completed"
        assert result["ok"] is True and result["business_completed"] is True
        assert result.get("reconciliation_required") is not True
    else:
        assert state == "blocked"
        assert result["execution_state"] in {"partial", "unknown"}
        assert result["reconciliation_required"] is True
        assert result["retryable"] is False
