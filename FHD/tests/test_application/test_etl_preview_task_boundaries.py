"""Real CSV/SQLite ETL jobs exercise owner routing and terminal task outcomes."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application.etl import (
    llm_assist,
    llm_session_provider,
    service_draft,
    service_execution,
    service_preview,
    service_uploads,
)
from app.application.etl.errors import EtlError
from app.application.etl.service import EtlService
from app.application.etl.service_support import load_json
from app.application.etl.targets import get_adapter
from app.db import session as db_session
from app.db.base import Base
from app.db.models import Product, PurchaseUnit
from app.db.models.etl import EtlRun, EtlRunRow
from app.db.models.user import Session as UserSession
from app.db.models.user import User
from app.infrastructure.llm.providers import registry
from app.infrastructure.tenant_scope import tenant_scope

CSV = "客户名称,电话\n隔离客户甲,13000000001\n隔离客户乙,13000000002\n".encode()


class ObservedExecutor(ThreadPoolExecutor):
    """Keep actual background execution, but make every worker exception observable."""

    def __init__(self):
        super().__init__(max_workers=1, thread_name_prefix="etl-boundary-test")
        self.futures = []

    def submit(self, fn, /, *args, **kwargs):
        future = super().submit(fn, *args, **kwargs)
        self.futures.append(future)
        return future


class FallbackProvider:
    provider_id = "fallback"
    is_configured = True

    def __init__(self):
        self.calls = 0

    async def chat_completion(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("owner request reached a different account's fallback")


@pytest.fixture
def preview_store(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'etl.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(db_session, "SessionLocal", factory)
    monkeypatch.setattr(service_uploads, "get_app_data_dir", lambda: str(tmp_path))
    monkeypatch.setenv("FHD_ETL_LLM", "on")
    monkeypatch.setenv("FHD_ETL_LLM_TIMEOUT", "2")
    monkeypatch.setenv("LLM_ROUTING_ORDER", "fallback")
    fallback = FallbackProvider()
    local_registry = registry.LLMProviderRegistry.__new__(registry.LLMProviderRegistry)
    local_registry._providers = {"fallback": fallback}
    monkeypatch.setattr(registry, "_registry", local_registry)
    with factory() as db:
        for owner in (7, 8):
            db.add(User(id=owner, username=f"isolated-{owner}", password="unused", tenant_id=1))
            db.add(
                UserSession(
                    session_id=f"isolated-session-{owner}",
                    user_id=owner,
                    tenant_id=1,
                    market_access_token=f"isolated-token-{owner}",
                    created_at=datetime.now(UTC) + timedelta(seconds=owner),
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        db.commit()
    llm_assist.clear_etl_llm_circuit()
    with ObservedExecutor() as executor, tenant_scope(1):
        for module in (service_preview, service_draft, service_execution):
            monkeypatch.setattr(module, "new_session", factory)
            monkeypatch.setattr(module, "EXECUTOR", executor)
        store = SimpleNamespace(
            factory=factory,
            executor=executor,
            service=EtlService(),
            fallback=fallback,
            calls=[],
        )
        try:
            yield store
        finally:
            executor.shutdown(wait=True)
            llm_assist.clear_etl_llm_circuit()
            engine.dispose()


def install_provider(store, monkeypatch, outcome="success"):
    async def chat_completion(provider, messages, **kwargs):
        task = json.loads(messages[1]["content"])["task"]
        store.calls.append((provider.owner_user_id, provider._token, task))
        assert "provider" not in kwargs and "conversation_service" not in kwargs
        if outcome == "type_error":
            raise TypeError("provider contract changed")
        if outcome == "missing_route":
            request = httpx.Request("GET", "https://isolated.invalid/resolve-chat-default")
            response = httpx.Response(400, request=request)
            raise httpx.HTTPStatusError("no configured model", request=request, response=response)
        if outcome == "invalid_json":
            content = "not a JSON response"
        elif task == "suggest_etl_field_mappings":
            content = json.dumps(
                {
                    "mappings": [
                        {
                            "source": "客户名称",
                            "target": "customer_name",
                            "confidence": 0.99,
                            "reason": "customer heading",
                        }
                    ]
                }
            )
        else:
            # A model recommending skip cannot override the deterministic new action.
            content = json.dumps(
                {"items": [{"index": i, "action": "skip", "reason": "advisory"} for i in range(2)]}
            )
        return {
            "choices": [{"message": {"content": content}}],
            "model": "isolated-owner-model",
        }

    monkeypatch.setattr(
        llm_session_provider.SessionMarketProvider, "chat_completion", chat_completion
    )


def create_preview(store, *, owner=7, target="customers", csv=CSV):
    with store.factory() as db:
        upload = store.service.save_upload(
            db,
            owner_user_id=owner,
            file_name="customers.csv",
            content_type="text/csv",
            stream=BytesIO(csv),
        )
        db.commit()
        result = store.service.create_preview(
            db, owner_user_id=owner, upload_id=upload["upload_id"], target_type=target
        )
    return result["id"]


def snapshot(store, run_id, owner=7):
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        result = store.service.get_run(db, run_id=run_id, owner_user_id=owner)
        rows = db.query(EtlRunRow).filter(EtlRunRow.run_id == run_id).order_by(EtlRunRow.id).all()
        result["persisted_rows"] = [
            {
                "normalized": load_json(row.normalized_json, {}),
                "advisory": load_json(row.llm_suggestion_json, {}),
                "action": row.final_action,
                "execution_status": row.execution_status,
            }
            for row in rows
        ]
        result["lease"] = (run.operation_kind, run.operation_token, run.operation_lease_until)
        result["error_code"] = run.error_code
        result["error_message"] = run.error_message
        return result


@pytest.mark.parametrize("outcome", ["success", "missing_route", "invalid_json", "type_error"])
def test_real_csv_preview_preserves_owner_and_deterministic_rows(
    preview_store, monkeypatch, outcome
):
    store = preview_store
    install_provider(store, monkeypatch, outcome)
    run_id = create_preview(store)
    store.executor.futures[-1].result(timeout=10)
    result = snapshot(store, run_id)
    assert result["status"] == "preview_ready"
    assert result["progress"] == 100 and result["total_rows"] == 2
    assert result["lease"] == (None, None, None)
    assert [row["normalized"]["customer_name"] for row in result["persisted_rows"]] == [
        "隔离客户甲",
        "隔离客户乙",
    ]
    assert [row["action"] for row in result["persisted_rows"]] == ["new", "new"]
    assert store.fallback.calls == 0
    assert store.calls and all(
        owner == 7 and token == "isolated-token-7" for owner, token, _ in store.calls
    )
    degraded = outcome != "success"
    mapping = result["source_features"]["llm_mapping"]
    assert mapping["degraded"] is degraded
    assert result["details"]["llm_degraded"] is degraded
    assert all(row["advisory"]["degraded"] is degraded for row in result["persisted_rows"])
    assert len(store.calls) == (1 if degraded else 2), "ETL must not automatically retry failures"
    if degraded:
        assert mapping["degradation_code"] == "ETL_LLM_UNAVAILABLE"
    else:
        assert mapping["model"] == "isolated-owner-model"
        assert all(row["advisory"]["action"] == "skip" for row in result["persisted_rows"])
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0, "preview must not write business rows"


def test_no_account_or_app_configuration_still_finishes_preview(preview_store, monkeypatch):
    from app.services import ai_conversation_service

    store = preview_store
    with store.factory() as db:
        db.query(UserSession).filter(UserSession.user_id == 7).update({"market_access_token": None})
        db.commit()
    store.fallback.is_configured = False
    monkeypatch.setattr(ai_conversation_service, "get_ai_conversation_service", lambda: None)
    run_id = create_preview(store)
    store.executor.futures[-1].result(timeout=10)
    result = snapshot(store, run_id)
    assert result["status"] == "preview_ready" and result["total_rows"] == 2
    assert result["source_features"]["llm_mapping"]["degradation_code"] == "ETL_LLM_UNAVAILABLE"
    assert result["details"]["llm_degraded"] is True
    assert result["lease"] == (None, None, None)
    assert store.fallback.calls == 0


def test_unexpected_parser_error_is_persisted_and_releases_preview_lease(
    preview_store, monkeypatch
):
    def broken_parse(*_args, **_kwargs):
        raise TypeError("unexpected parser failure with private detail")

    monkeypatch.setattr(service_preview, "parse_file", broken_parse)
    run_id = create_preview(preview_store)
    preview_store.executor.futures[-1].result(timeout=10)
    result = snapshot(preview_store, run_id)
    assert result["status"] == result["stage"] == "failed"
    assert result["error_code"] == "ETL_INTERNAL_ERROR"
    assert "private detail" not in result["error_message"]
    assert result["lease"] == (None, None, None)
    assert result["persisted_rows"] == []
    assert run_id not in service_preview.SUBMITTED


def ready_preview(store, monkeypatch, *, target="customers"):
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    run_id = create_preview(store, target=target)
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, run_id)["status"] == "preview_ready"
    return run_id


def test_customer_products_csv_preview_and_confirmed_execution_persist_aggregate(
    preview_store, monkeypatch
):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    csv = (
        "客户名称,产品型号,产品名称,价格\n"
        "隔离联合客户,LOCAL-1,隔离产品甲,12.50\n"
        "隔离联合客户,LOCAL-2,隔离产品乙,25.00\n"
    ).encode()
    run_id = create_preview(store, target="customer_products", csv=csv)
    store.executor.futures[-1].result(timeout=10)
    preview = snapshot(store, run_id)
    assert preview["status"] == "preview_ready" and preview["summary"]["new"] == 2
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == db.query(Product).count() == 0
        store.service.execute(
            db, run_id=run_id, owner_user_id=7, confirmed=True, valid_rows_only=False
        )
    store.executor.futures[-1].result(timeout=10)
    result = snapshot(store, run_id)
    assert result["status"] == "completed" and result["summary"]["executed"] == 2
    assert result["lease"] == (None, None, None)
    with store.factory() as db:
        customer = db.query(PurchaseUnit).one()
        assert customer.unit_name == "隔离联合客户"
        products = db.query(Product).order_by(Product.model_number).all()
        assert [(row.unit, row.model_number, row.name, row.price) for row in products] == [
            (customer.unit_name, "LOCAL-1", "隔离产品甲", Decimal("12.50")),
            (customer.unit_name, "LOCAL-2", "隔离产品乙", Decimal("25.00")),
        ]
        rolled_back = store.service.rollback(db, run_id=run_id, owner_user_id=7)
        assert rolled_back["rollback_status"] == "completed"
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == db.query(Product).count() == 0
    assert snapshot(store, run_id)["lease"] == (None, None, None)


def test_unexpected_revalidation_error_fails_and_releases_lease(preview_store, monkeypatch):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)

    def broken_revalidate(*_args, **_kwargs):
        raise TypeError("unexpected revalidation failure")

    monkeypatch.setattr(store.service, "_revalidate_existing_rows", broken_revalidate)
    with store.factory() as db:
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"validation_rules": []}
        )
    store.executor.futures[-1].result(timeout=10)
    result = snapshot(store, run_id)
    assert result["status"] == result["stage"] == "failed"
    assert result["error_code"] == "ETL_INTERNAL_ERROR"
    assert result["lease"] == (None, None, None)
    assert run_id not in service_draft.SUBMITTED


def test_unexpected_database_execution_error_rolls_back_chunk_without_replay(
    preview_store, monkeypatch
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    adapter = get_adapter("customers")
    execute_row = adapter.execute_row
    calls = []

    def write_then_fail(db, data, **kwargs):
        calls.append(data["customer_name"])
        result = execute_row(db, data, **kwargs)
        if len(calls) == 2:
            raise TypeError("adapter failed after SQL flush")
        return result

    monkeypatch.setattr(adapter, "execute_row", write_then_fail)
    with store.factory() as db:
        store.service.execute(
            db, run_id=run_id, owner_user_id=7, confirmed=True, valid_rows_only=False
        )
    store.executor.futures[-1].result(timeout=10)
    result = snapshot(store, run_id)
    assert result["status"] == "failed" and result["error_code"] == "ETL_INTERNAL_ERROR"
    assert result["lease"] == (None, None, None)
    assert calls == ["隔离客户甲", "隔离客户乙"], "unexpected errors must not replay writes"
    assert all(row["execution_status"] != "success" for row in result["persisted_rows"])
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0


def test_unexpected_external_batch_error_retains_unknown_outcome_and_rejects_retry(
    preview_store, monkeypatch
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch, target="export_csv")
    calls = []

    def external_then_fail(rows, context):
        calls.append(list(rows))
        raise TypeError("external result contract changed after dispatch")

    monkeypatch.setattr(get_adapter("export_csv"), "execute_batch", external_then_fail)
    with store.factory() as db:
        store.service.execute(
            db, run_id=run_id, owner_user_id=7, confirmed=True, valid_rows_only=False
        )
    store.executor.futures[-1].result(timeout=10)
    result = snapshot(store, run_id)
    assert result["status"] == result["stage"] == "outcome_unknown"
    assert result["error_code"] == "ETL_OUTCOME_UNKNOWN"
    assert result["lease"][0] == "batch_execute" and all(result["lease"])
    assert len(calls) == 1 and len(calls[0]) == 2
    with store.factory() as db, pytest.raises(EtlError) as error:
        store.service.retry(db, run_id=run_id, owner_user_id=7)
    assert error.value.code == "ETL_RETRY_NOT_ALLOWED"
    assert len(calls) == 1 and run_id not in service_execution.SUBMITTED


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_process_control_exceptions_are_not_translated_to_application_failure(
    preview_store, monkeypatch, exception
):
    def interrupted_parse(*_args, **_kwargs):
        raise exception("test process control")

    monkeypatch.setattr(service_preview, "parse_file", interrupted_parse)
    run_id = create_preview(preview_store)
    with pytest.raises(exception):
        preview_store.executor.futures[-1].result(timeout=10)
    result = snapshot(preview_store, run_id)
    assert result["status"] == "previewing" and result["error_code"] is None
    assert run_id not in service_preview.SUBMITTED
