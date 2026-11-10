"""Locks the chat failure chain: visible model text, preview gate, and idempotent retry."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.application.chat_turn_guard import (
    chunk_display_text,
    is_bulk_destructive,
    joined_display_text,
    mutation_block,
    mutation_policy,
    note_tool_result,
    prepare_turn,
    reset_turn_ledger,
)
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.fixture(autouse=True)
def _isolated_turn_ledger():
    reset_turn_ledger()
    yield
    reset_turn_ledger()


def test_keeps_displayable_text_and_rejects_whitespace_or_reasoning():
    assert joined_display_text(["  ", "已保留正文"]) == "  已保留正文"
    assert joined_display_text([" \n\t"]) is None
    choice = SimpleNamespace(
        delta=SimpleNamespace(content=None, reasoning_content="只是思考"),
        message=SimpleNamespace(content="客户仍在，未删除。"),
    )
    assert chunk_display_text(choice) == "客户仍在，未删除。"
    reasoning_only = SimpleNamespace(
        delta=SimpleNamespace(content=None, reasoning_content="只是思考"), message=None
    )
    assert chunk_display_text(reasoning_only) == ""


def test_unknown_agent_effect_survives_public_chat_sanitization():
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin
    from app.application.workflow.workflow_types import PlanGraph
    from app.fastapi_routes.ai_intent import _public_unified_chat_payload

    step = AgentStep(
        node_id="write",
        tool_id="customers",
        action="create",
        status="failed",
        error="private database detail",
        output={"success": False, "outcome": "unknown", "reconciliation_required": True},
    )
    run = AgentRun(user_id="1", message="新增客户", status="blocked", steps=[step])
    plan = PlanGraph(plan_id="test", intent="customer_write", nodes=[])
    payload = AIChatWorkflowResponseMixin()._format_agent_run_response(plan, run)
    public = _public_unified_chat_payload(payload)
    assert payload["requires_reconciliation"] is True and payload["retryable"] is False
    assert public["execution_state"] == "unknown" and public["retryable"] is False
    assert public["run_id"] == run.run_id
    assert "勿重复提交" in public["message"] and "private database detail" not in str(public)
    for status in ("pending_approval", "running", "queued"):
        pending = {"success": True, "data": {"status": status}}
        assert _public_unified_chat_payload(pending) == pending


def test_unknown_result_reaches_authenticated_unified_chat(trusted_actor, monkeypatch):
    import json

    from app.fastapi_routes import ai_intent

    actor = trusted_actor(role="admin")
    monkeypatch.setattr(
        "app.domain.app_pure.ai_chat_helpers.unified_chat_single_payload",
        lambda *args, **kwargs: {
            "success": False,
            "requires_reconciliation": True,
            "error": "private database detail",
        },
    )
    monkeypatch.setattr(ai_intent, "_attach_unified_chat_run", lambda payload, **kwargs: payload)
    response = ai_intent.ai_chat_unified_alias(actor.request, {"message": "新增客户"})
    public = json.loads(response.body)
    assert response.status_code == 409
    assert public["requires_reconciliation"] is True and public["retryable"] is False
    assert "勿重复提交" in public["message"] and "private database detail" not in str(public)


def test_bulk_preview_names_scope_and_does_not_call_the_model(monkeypatch):
    from app.application.ai_chat_app_service import AIChatApplicationService

    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (4, 9, "customers-4", "products-9"),
    )
    service = object.__new__(AIChatApplicationService)
    service._process_chat_impl = MagicMock()
    result = service.process_chat(
        "user-1",
        "清理全部客户和产品",
        context={
            "tenant_id": "XCAGI-ENTERPRISE-DEMO",
            "turn_id": "turn-1",
            "scope_counts": {"customers": 4, "products": 9},
        },
    )
    service._process_chat_impl.assert_not_called()
    assert result["execution"]["committed"] is False
    assert result["execution"]["effect"] == "preview"
    assert "XCAGI-ENTERPRISE-DEMO" in result["response"]
    assert "客户 4 条" in result["response"]
    assert "产品 9 条" in result["response"]
    assert "尚未写入" in result["response"]
    assert is_bulk_destructive("删除所有订单")
    assert not is_bulk_destructive("删除这个客户")


def test_model_reply_is_visible_after_langgraph():
    import json
    from unittest.mock import Mock

    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
    from app.application.workflow.planner import LLMWorkflowPlanner
    from app.services.tools_execution.registry import get_workflow_tool_registry

    response = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"mode": "reply", "reply": "可见的模型正文"}, ensure_ascii=False
                    )
                }
            }
        ]
    }
    service = Mock()
    service.get_context.return_value = None
    completion = Mock(return_value=response)
    plan = LLMWorkflowPlanner(ai_service=service, completion=completion).plan(
        "user", "你好", get_workflow_tool_registry(), {}
    )
    result = PlannedWorkflowDispatch._execute_reply_plan(plan, {})
    assert result["success"] is True and result["response"] == "可见的模型正文"
    completion.assert_called_once()


def test_whitespace_model_reply_is_not_a_success():
    import json

    from app.application.workflow.llm_plan_generation import _decode_completion

    response = {
        "choices": [{"message": {"content": json.dumps({"mode": "reply", "reply": "  \n"})}}]
    }
    assert _decode_completion(response) is None


def test_retry_and_second_confirm_do_not_write(monkeypatch):
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (1, 1, "customers-1", "products-1"),
    )
    ctx = {
        "tenant_id": "demo",
        "idempotency_key": "turn-1",
        "destructive_confirmed": True,
        "scope_counts": {"customers": 1, "products": 1},
    }
    prepare_turn("清理全部客户和产品", {**ctx, "destructive_confirmed": False})
    assert prepare_turn("清理全部客户和产品", ctx) is None
    assert mutation_policy() == "allow_once"
    blocked = mutation_block(
        "delete_customers",
        '{"all": true}',
        {"mutation_policy": "model_only", "idempotency_key": "turn-1", "tenant_id": "demo"},
    )
    assert blocked["committed"] is False
    note_tool_result(ctx, "delete_customers")
    again = prepare_turn(
        "清理全部客户和产品",
        {"idempotency_key": "turn-1", "destructive_confirmed": True, "tenant_id": "demo"},
    )
    assert again["execution"]["committed"] is False
    assert again["execution"]["effect"] == "unknown"
    assert again["success"] is False
    retry_ctx = {"idempotency_key": "turn-1", "retry_of": "turn-1", "tenant_id": "demo"}
    assert prepare_turn("清理全部客户和产品", retry_ctx) is None
    assert mutation_policy() == "model_only"
    assert mutation_block("delete_customers", "{}", retry_ctx)["error"] == "outcome_unknown"


def test_preview_confirmation_and_retry_keep_unknown_effect(monkeypatch):
    from app.application.chat_turn_guard import admit_chat_turn

    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (2, 3, "customers-2", "products-3"),
    )
    context = {"tenant_id": "demo-tenant", "idempotency_key": "turn-bulk", "turn_id": "turn-bulk"}
    preview = admit_chat_turn("清理全部客户和产品", dict(context))
    assert preview["execution"]["effect"] == "preview"
    confirmed = {**context, "destructive_confirmed": True}
    assert admit_chat_turn("清理全部客户和产品", confirmed) is None
    assert confirmed["mutation_policy"] == "allow_once"
    note_tool_result(confirmed, "delete_customers")
    retry = {**context, "retry_of": "turn-bulk", "mutation_policy": "allow"}
    assert admit_chat_turn("清理全部客户和产品", retry) is None
    assert retry["mutation_policy"] == "model_only"
    blocked = mutation_block("delete_customers", "{}", retry)
    assert blocked["error"] == "outcome_unknown" and blocked["committed"] is False


def test_uncommitted_confirm_is_not_repeated_by_another_confirm(monkeypatch):
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (0, 0, "customers-0", "products-0"),
    )
    first = {
        "idempotency_key": "turn-2",
        "destructive_confirmed": True,
        "tenant_id": "demo",
        "scope_counts": {"customers": 0, "products": 0},
    }
    prepare_turn("清空所有产品", {**first, "destructive_confirmed": False})
    assert prepare_turn("清空所有产品", first) is None
    second = {"idempotency_key": "turn-2", "destructive_confirmed": True, "tenant_id": "demo"}
    reply = prepare_turn("清空所有产品", second)
    assert mutation_policy() == "model_only"
    assert reply["execution"]["committed"] is False
    assert "不会执行删除" in reply["response"]


def test_retry_cannot_supply_its_own_mutation_policy():
    from app.application.chat_turn_guard import admit_chat_turn

    context = {"tenant_id": "demo", "retry_of": "old-turn", "mutation_policy": "allow"}
    assert admit_chat_turn("清空所有产品", context) is None
    assert context["mutation_policy"] == "model_only"
    assert mutation_block("delete_products", "{}", context)["success"] is False


def test_preview_uses_authorized_tenant_rows_not_caller_counts(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.application.chat_turn_guard import (
        _matches_previewed_batch,
        preview_message,
        scope_snapshot,
    )
    from app.db.db_base import Base
    from app.db.models import Product
    from app.db.models.purchase_unit import PurchaseUnit

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all(
            [
                PurchaseUnit(tenant_id=1, unit_name="A"),
                PurchaseUnit(tenant_id=2, unit_name="B"),
                Product(tenant_id=1, name="P"),
            ]
        )
        db.commit()

    @contextmanager
    def session():
        with Session(engine) as db:
            yield db

    monkeypatch.setattr("app.db.session.get_db", session)
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope._bound_actor", lambda ctx: object()
    )
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_permission.actor_tool_denial", lambda *args: None
    )
    ctx = {"tenant_id": 1, "scope_counts": {"customers": 999, "products": 999}}
    valid = '{"tool_id":"products","action":"batch_delete","params":{"ids":[1]}}'
    assert _matches_previewed_batch("execute_erp_capability", valid, ctx, "清空所有产品")
    assert not _matches_previewed_batch("execute_erp_capability", valid, ctx, "清空所有客户")
    assert not _matches_previewed_batch("delete_products", valid, ctx, "清空所有产品")
    assert not _matches_previewed_batch(
        "execute_erp_capability", valid.replace("[1]", "[1, 999]"), ctx, "清空所有产品"
    )
    assert not _matches_previewed_batch(
        "execute_erp_capability",
        valid.replace('"ids":[1]', '"ids":[1],"force":true'),
        ctx,
        "清空所有产品",
    )
    customers, products, customer_scope, product_scope = scope_snapshot(ctx)
    assert (customers, products) == (1, 1)
    text = preview_message(ctx, "清空所有产品", customers=customers, products=products)
    assert "产品 1 条" in text and "客户" not in text and "999" not in text
    action = {**ctx, "user_id": "10", "idempotency_key": "preview"}
    prepare_turn("清空所有产品", action)
    with Session(engine) as db:
        db.delete(db.query(Product).filter(Product.tenant_id == 1).one())
        db.add(Product(id=999, tenant_id=1, name="replacement"))
        db.commit()
    assert scope_snapshot(ctx)[1] == products
    assert scope_snapshot(ctx)[3] != product_scope
    assert (
        prepare_turn("清空所有产品", {**action, "destructive_confirmed": True})["success"] is False
    )
    product_scope = scope_snapshot(ctx)[3]
    changed_action = {**action, "idempotency_key": "same-id"}
    prepare_turn("清空所有产品", changed_action)
    with Session(engine) as db:
        db.query(Product).filter(Product.id == 999).one().name = "changed"
        db.commit()
    assert scope_snapshot(ctx)[1] == products
    assert scope_snapshot(ctx)[3] != product_scope
    assert (
        prepare_turn("清空所有产品", {**changed_action, "destructive_confirmed": True})["success"]
        is False
    )
    product_scope = scope_snapshot(ctx)[3]
    monkeypatch.setattr(
        "app.application.agent_orchestrator.tool_permission.actor_tool_denial",
        lambda tool, *_: {} if tool == "customers" else None,
    )
    assert scope_snapshot(ctx) == (None, 1, None, product_scope)
    monkeypatch.setattr(
        "app.infrastructure.auth.agent_mod_scope._bound_actor",
        lambda ctx: (_ for _ in ()).throw(ValueError("invalid session")),
    )
    assert scope_snapshot(ctx) == (None, None, None, None)
    assert "租户：未核验" in preview_message(ctx, "清空所有产品", customers=None, products=None)
    engine.dispose()


def test_identical_turn_keys_are_isolated_between_tenants_and_users(monkeypatch):
    from app.application.chat_turn_guard import execution_for_context

    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (1, 2, "customers-1", "products-2"),
    )
    first = {"tenant_id": "1", "user_id": "10", "idempotency_key": "same"}
    prepare_turn("清空所有产品", first)
    assert execution_for_context(first)["tenant_id"] == "1"
    assert execution_for_context({**first, "tenant_id": "2"}) is None
    assert execution_for_context({**first, "user_id": "11"}) is None


def test_concurrent_confirmation_and_dispatch_are_claimed_once(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    monkeypatch.setattr(
        "app.application.chat_turn_guard._matches_previewed_batch", lambda *args: True
    )

    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (1, 1, "customers-1", "products-1"),
    )
    ctx = {
        "tenant_id": "1",
        "user_id": "10",
        "idempotency_key": "same",
        "destructive_confirmed": True,
        "mutation_policy": "allow_once",
    }
    prepare_turn("清空所有产品", {**ctx, "destructive_confirmed": False})
    barrier = Barrier(2)

    def attempt(_):
        barrier.wait()
        if prepare_turn("清空所有产品", ctx) is not None:
            return "blocked"
        args = '{"tool_id":"products","action":"batch_delete","params":{"ids":[1]}}'
        return (
            "allowed" if mutation_block("execute_erp_capability", args, ctx) is None else "blocked"
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sorted(outcomes) == ["allowed", "blocked"]
    assert (
        prepare_turn("清空所有产品", {**ctx, "destructive_confirmed": False})["execution"]["effect"]
        == "executing"
    )
    assert mutation_block("delete_products", "{}", ctx)["error"] == "outcome_unknown"


def test_both_previewed_ranges_can_submit_one_approval_each(monkeypatch):
    from app.application.chat_turn_guard import execution_for_context

    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot", lambda ctx: (1, 1, "c", "p")
    )
    monkeypatch.setattr(
        "app.application.chat_turn_guard._matches_previewed_batch", lambda *args: True
    )
    ctx = {"tenant_id": "1", "user_id": "1", "turn_id": "both", "mutation_policy": "allow_once"}
    message = "清空所有客户和产品"
    prepare_turn(message, ctx)
    assert prepare_turn(message, {**ctx, "destructive_confirmed": True}) is None
    customer = '{"tool_id":"customers","action":"batch_delete","params":{"ids":[1]}}'
    product = '{"tool_id":"products","action":"batch_delete","params":{"ids":[2]}}'
    assert mutation_block("execute_erp_capability", customer, ctx) is None
    note_tool_result(ctx, "execute_erp_capability", customer, pending=True)
    assert mutation_block("execute_erp_capability", customer, ctx)["error"] == "already_submitted"
    assert mutation_block("execute_erp_capability", product, ctx) is None
    note_tool_result(ctx, "execute_erp_capability", product, pending=True)
    assert execution_for_context(ctx)["effect"] == "pending_approval"


def test_client_cannot_replace_preview_scope():
    from app.application.agent_orchestrator.run_models import AgentRun
    from app.application.agent_orchestrator.runtime_context import (
        RuntimeContextOwnershipError,
        merge_runtime_context,
    )
    from app.fastapi_routes.domains.agent.route_support import without_runtime_identity

    forged = {"mutation_policy": "allow_once", "_bulk_preview_scopes": {"products": "forged"}}
    assert without_runtime_identity(forged) == {}
    run = AgentRun(
        user_id="1",
        message="test",
        metadata={
            "runtime_context": {
                "mutation_policy": "allow_once",
                "_bulk_preview_scopes": {"products": "original"},
            }
        },
    )
    with pytest.raises(RuntimeContextOwnershipError):
        merge_runtime_context(run, forged)


def test_confirmation_rejects_missing_or_changed_preview(monkeypatch):
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (1, 1, "customers-1", "products-1"),
    )
    ctx = {
        "tenant_id": "1",
        "user_id": "10",
        "idempotency_key": "key",
        "destructive_confirmed": True,
    }
    assert prepare_turn("清空所有产品", ctx)["success"] is False
    prepare_turn("清空所有产品", {**ctx, "destructive_confirmed": False})
    assert prepare_turn("清理全部客户和产品", ctx)["success"] is False
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (1, 2, "customers-1", "products-2"),
    )
    assert prepare_turn("清空所有产品", ctx)["success"] is False
    prepare_turn("清空所有产品", {**ctx, "destructive_confirmed": False})
    assert prepare_turn("清空所有产品", ctx) is None
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (1, 2, "customers-1", "different"),
    )
    assert (
        mutation_block("delete_products", "{}", {**ctx, "mutation_policy": "allow_once"})["error"]
        == "scope_changed"
    )
