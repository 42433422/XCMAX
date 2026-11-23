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
    "outcome,committed", [("partial", True), ("unknown", False), ("not_executed", False)]
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
    "outcome,committed", [("partial", True), ("unknown", False), ("not_executed", False)]
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

def test_shared_chat_actual_workflow_builder_partial_write_requires_reconciliation():
    """A completed write followed by a failed step is not a safe voice retry."""
    from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin
    from app.fastapi_routes.ai_intent import _public_unified_chat_payload

    class Formatter(AIChatWorkflowResponseMixin):
        @staticmethod
        def _format_workflow_tool_success_line(_step, _params):
            return ["- 写入完成"]

        @staticmethod
        def _workflow_output_message(_output):
            return "写入完成"

    plan = SimpleNamespace(
        intent="materials_shipment",
        plan_id="original-plan",
        todo_steps=[],
        nodes=[],
        metadata={},
    )
    run = SimpleNamespace(
        run_id="original-run",
        status="failed",
        metadata={},
        artifacts=[],
        tool_calls=[],
        steps=[
            SimpleNamespace(
                node_id="write-material",
                status="completed",
                tool_id="materials",
                action="create",
                output={"success": True, "material_id": 17},
                duration_ms=1,
            ),
            SimpleNamespace(
                node_id="failed-shipment",
                status="failed",
                tool_id="shipment_records",
                action="create",
                output={"success": False, "error": PRIVATE},
                duration_ms=1,
            ),
        ],
    )
    raw = Formatter()._format_agent_run_response(plan, run)
    assert raw["success"] is False
    assert raw["execution"]["committed"] is True
    assert raw["execution"]["effect"] == "partial"
    assert raw["execution"]["outcome"] == "partial"
    assert "execution" not in raw["data"]["data"]

    public = _public_unified_chat_payload(raw)
    assert public["success"] is False
    assert public["run_id"] == "original-run"
    assert public["plan_id"] == "original-plan"
    assert public["execution"] == {
        "committed": True,
        "effect": "partial",
        "outcome": "partial",
    }
    assert public["requires_reconciliation"] is True
    assert public["retryable"] is False
    assert public["_http_status"] == 409
    assert "勿重复提交" in public["message"]
    assert PRIVATE not in json.dumps(public, ensure_ascii=False)
