"""Public errors retain failure/state contracts without exposing backend diagnostics."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.application.admin_control.protocols import ErrorPolicy
from app.fastapi_routes.admin_control.profiles import UserProfiles
from app.fastapi_routes.admin_control.synchronization import Synchronization

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
def test_shared_chat_failure_boundary_preserves_top_level_execution_receipt(
    outcome, committed
):
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
    assert runtime["execution_state"] == (
        "unknown" if next_state == "unknown" else "partial"
    )

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
