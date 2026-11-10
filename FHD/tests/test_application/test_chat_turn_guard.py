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
from app.legacy.chat import legacy_chat_adapter as adapter
from app.legacy.chat.legacy_chat_runtime import chat, chat_stream_sse_events, chat_stream_text


@pytest.fixture(autouse=True)
def _isolated_turn_ledger():
    reset_turn_ledger()
    yield
    reset_turn_ledger()


def chunk(content="", calls=None, finish="stop"):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=calls or []), finish_reason=finish
            )
        ]
    )


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


def test_bulk_preview_names_scope_and_does_not_call_the_model(monkeypatch):
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (4, 9, "customers-4", "products-9"),
    )
    client = MagicMock()
    result = chat(
        "清理全部客户和产品",
        client=client,
        runtime_context={
            "tenant_id": "XCAGI-ENTERPRISE-DEMO",
            "turn_id": "turn-1",
            "scope_counts": {"customers": 4, "products": 9},
        },
    )
    client.chat.completions.create.assert_not_called()
    assert result["execution"]["committed"] is False
    assert result["execution"]["effect"] == "preview"
    assert "XCAGI-ENTERPRISE-DEMO" in result["response"]
    assert "客户 4 条" in result["response"]
    assert "产品 9 条" in result["response"]
    assert "尚未写入" in result["response"]
    assert is_bulk_destructive("删除所有订单")
    assert not is_bulk_destructive("删除这个客户")


def test_stream_shows_message_body_when_delta_content_is_empty():
    chunk = MagicMock()
    chunk.choices = [MagicMock(finish_reason="stop")]
    chunk.choices[0].delta = SimpleNamespace(content=None, tool_calls=None)
    chunk.choices[0].message = SimpleNamespace(content="可见的模型正文")
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.return_value = iter([chunk])
    parts = list(chat_stream_text("你好", client=client, model="test-model"))
    assert "可见的模型正文" in parts
    assert not any(
        isinstance(part, dict) and part.get("error") == "planner_empty_response" for part in parts
    )


def test_whitespace_stream_stays_an_explicit_empty_result():
    chunk = MagicMock()
    chunk.choices = [MagicMock(finish_reason="stop")]
    chunk.choices[0].delta = SimpleNamespace(content="  \n", tool_calls=None)
    chunk.choices[0].message = None
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.return_value = iter([chunk])
    parts = list(chat_stream_text("你好", client=client, model="test-model"))
    assert any(
        isinstance(part, dict) and part.get("error") == "planner_empty_response" for part in parts
    )


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


def test_stream_keeps_the_execution_record_through_preview_commit_and_retry(monkeypatch):
    executed: list[str] = []

    def execute(name, _arguments, *_args, **_kwargs):
        executed.append(name)
        return '{"success": true}'

    monkeypatch.setattr(adapter, "_get_workflow_tool_registry", lambda: [])
    monkeypatch.setattr(adapter, "_resolve_chat_execute_tool", lambda: execute)
    ctx = {
        "tenant_id": "demo-tenant",
        "idempotency_key": "turn-bulk",
        "turn_id": "turn-bulk",
        "scope_counts": {"customers": 2, "products": 3},
    }
    monkeypatch.setattr(
        "app.application.chat_turn_guard.scope_snapshot",
        lambda ctx: (2, 3, "customers-2", "products-3"),
    )
    preview = list(
        chat_stream_sse_events("清理全部客户和产品", runtime_context=ctx, client=MagicMock())
    )
    assert preview[-1]["result"]["execution"]["effect"] == "preview"
    assert preview[-1]["result"]["execution"]["committed"] is False
    assert executed == []

    call = SimpleNamespace(
        index=0, id="call-1", function=SimpleNamespace(name="delete_all_customers", arguments="{}")
    )
    rounds = iter(
        [
            iter([chunk(calls=[call], finish="tool_calls")]),
            iter([chunk("  \n")]),
        ]
    )
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.side_effect = lambda **_: next(rounds)
    confirmed = {**ctx, "destructive_confirmed": True}
    failed = list(
        chat_stream_sse_events(
            "清理全部客户和产品", runtime_context=confirmed, client=client, model="test"
        )
    )
    assert executed == ["delete_all_customers"]
    assert failed[-1]["type"] == "error"
    assert failed[-1]["execution"]["committed"] is False
    assert failed[-1]["result"]["execution"]["effect"] == "unknown"

    retry = list(
        chat_stream_sse_events(
            "清理全部客户和产品",
            runtime_context={**ctx, "retry_of": "turn-bulk"},
            client=MagicMock(
                is_modstore_openai_compatible=False,
                chat=MagicMock(
                    completions=MagicMock(
                        create=MagicMock(return_value=iter([chunk("只回答，不删除。")]))
                    )
                ),
            ),
            model="test",
        )
    )
    assert executed == ["delete_all_customers"]
    assert retry[-1]["result"]["execution"]["effect"] == "unknown"


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


def test_retry_cannot_supply_its_own_mutation_policy(monkeypatch):
    executed = []
    monkeypatch.setattr(adapter, "_get_workflow_tool_registry", lambda: [])
    monkeypatch.setattr(
        adapter, "_resolve_chat_execute_tool", lambda: lambda *a, **k: executed.append(a)
    )
    call = SimpleNamespace(
        index=0, id="call-1", function=SimpleNamespace(name="delete_products", arguments="{}")
    )

    responses = iter(
        [iter([chunk(calls=[call], finish="tool_calls")]), iter([chunk("未执行删除。")])]
    )
    client = MagicMock(is_modstore_openai_compatible=False)
    client.chat.completions.create.side_effect = lambda **_: next(responses)
    list(
        chat_stream_sse_events(
            "清空所有产品",
            runtime_context={
                "tenant_id": "demo",
                "retry_of": "old-turn",
                "mutation_policy": "allow",
            },
            client=client,
            model="test",
        )
    )
    assert executed == []


def test_preview_uses_authorized_tenant_rows_not_caller_counts(monkeypatch):
    from contextlib import contextmanager

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.application.chat_turn_guard import preview_message, scope_snapshot
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
        return "allowed" if mutation_block("delete_products", "{}", ctx) is None else "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sorted(outcomes) == ["allowed", "blocked"]
    assert (
        prepare_turn("清空所有产品", {**ctx, "destructive_confirmed": False})["execution"]["effect"]
        == "executing"
    )
    assert mutation_block("delete_products", "{}", ctx)["error"] == "outcome_unknown"


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
