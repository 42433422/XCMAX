"""SQL/savepoint failures and incomplete batch acknowledgements never replay writes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from sqlalchemy import event, text

from app.application.elt import service_execution
from app.application.elt.errors import EltError
from app.application.elt.operation_owner import claim_operation, recover_stale_owner
from app.application.elt.service_support import dump_json, load_json
from app.application.elt.targets import get_adapter
from app.db.models import PurchaseUnit
from app.db.models.elt import EltRun, EltRunRow
from tests.test_application.test_etl_preview_confirmation import execute
from tests.test_application.test_etl_preview_task_boundaries import (
    create_preview,
    ready_preview,
    snapshot,
)
from tests.test_application.test_etl_preview_task_boundaries import (
    preview_store as preview_store,
)


def test_row_failure_keeps_prior_write_without_executing_it_twice(preview_store, monkeypatch):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    adapter = get_adapter("customers")
    original = adapter.execute_row
    calls = []

    def write(db, data, **kwargs):
        calls.append(data["customer_name"])
        result = original(db, data, **kwargs)
        if data["customer_name"] == "隔离客户乙":
            raise EltError("ELT_TEST_ROW_REJECTED", "synthetic row failure after flush")
        return result

    monkeypatch.setattr(adapter, "execute_row", write)
    execute(store, run_id, snapshot(store, run_id)["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, run_id)
    assert calls == ["隔离客户甲", "隔离客户乙"]
    assert current["status"] == "failed"
    assert current["summary"]["executed"] == 1
    assert [r["execution_status"] for r in current["persisted_rows"]] == ["success", "failed"]
    with store.factory() as db:
        assert [u.unit_name for u in db.query(PurchaseUnit).all()] == ["隔离客户甲"]


@pytest.mark.parametrize("close_failures", [0, 2])
def test_sqlalchemy_after_commit_error_recovers_without_detaching_or_replaying(
    preview_store, monkeypatch, close_failures
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    adapter = get_adapter("customers")
    writes = Mock(wraps=adapter.execute_row)
    monkeypatch.setattr(adapter, "execute_row", writes)
    fired = False
    opened = []

    def factory():
        db = store.factory()
        opened.append(db)

        def after_commit(session):
            nonlocal fired
            if fired or session.in_nested_transaction():
                return
            for item in session.identity_map.values():
                if isinstance(item, EltRun) and item.id == run_id and item.executed_rows == 2:
                    fired = True
                    if close_failures:
                        transaction = session.get_transaction()
                        close = transaction.close
                        attempts = 0

                        def delayed_close(*args, **kwargs):
                            nonlocal attempts
                            attempts += 1
                            if attempts <= close_failures:
                                raise OSError("synthetic transaction cleanup failure")
                            return close(*args, **kwargs)

                        monkeypatch.setattr(transaction, "close", delayed_close)
                    raise OSError("synthetic after_commit observer failure")

        event.listen(db, "after_commit", after_commit)
        return db

    monkeypatch.setattr(service_execution, "new_session", factory)
    execute(store, run_id, snapshot(store, run_id)["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, run_id)
    assert fired and writes.call_count == 2
    assert current["status"] == ("outcome_unknown" if close_failures else "completed")
    assert current["summary"]["executed"] == 2
    if close_failures:
        assert len(opened) >= 3  # worker, independent readback, fresh failure transaction
        assert current["error_code"] == "ELT_OUTCOME_UNKNOWN" and current["lease"][1]
    else:
        assert current["lease"] == (None, None, None)
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 2
        assert all(row.execution_status == "success" for row in db.query(EltRunRow).all())


@pytest.mark.parametrize("lose_ack", [False, True])
def test_knowledge_external_store_is_called_without_holding_host_write_lock(
    preview_store, monkeypatch, tmp_path, lose_ack
):
    from app.application import dataset_rag_app_service as rag

    store = preview_store
    effects = []

    def embed(content):
        # A real independent writer models a knowledge consumer sharing the
        # host database; holding the ELT fence here would cause SQLITE_BUSY.
        with store.factory() as other:
            other.execute(text("PRAGMA busy_timeout=100"))
            other.add(PurchaseUnit(unit_name=f"knowledge-effect-{len(effects)}", tenant_id=1))
            other.commit()
        effects.append(content)
        return [1.0, 0.0]

    knowledge = rag.DatasetRagApplicationService(
        embedder=embed,
        storage_path=tmp_path / "knowledge-receipts.json",
        allowed_roots=[tmp_path],
        rebuild_workers_enabled=False,
    )
    monkeypatch.setattr(rag, "get_dataset_rag_app_service", lambda: knowledge)
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    run_id = create_preview(
        store,
        target="knowledge",
        csv="内容,来源\nsynthetic knowledge one,source-one\nsynthetic knowledge two,source-two\n".encode(),
    )
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, run_id)["summary"]["new"] == 2
    adapter = get_adapter("knowledge")
    original = adapter.execute_row
    calls = []

    def write(db, data, **kwargs):
        calls.append(data["content"])
        result = original(db, data, **kwargs)
        if lose_ack and len(calls) == 2:
            raise OSError("synthetic knowledge ACK loss after external commit")
        return result

    monkeypatch.setattr(adapter, "execute_row", write)
    execute(store, run_id, snapshot(store, run_id)["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, run_id)
    assert len(calls) == 2 and len(effects) == 2
    assert current["status"] == ("outcome_unknown" if lose_ack else "completed")
    assert current["summary"]["executed"] == (1 if lose_ack else 2)
    assert len(knowledge.status(dataset_id="office-docking", tenant_id="1")["documents"]) == 2
    if lose_ack:
        assert current["lease"][0] == "batch_execute"
        with store.factory() as db, pytest.raises(EltError):
            store.service.retry(db, run_id=run_id, owner_user_id=7)
    assert len(calls) == 2


@pytest.mark.parametrize("committed", [False, True])
@pytest.mark.parametrize("readback_available", [False, True])
def test_commit_acknowledgement_is_read_back_without_replaying(
    preview_store, monkeypatch, committed, readback_available
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    adapter = get_adapter("customers")
    writes = Mock(wraps=adapter.execute_row)
    monkeypatch.setattr(adapter, "execute_row", writes)
    opened = 0
    interrupted = False

    def factory():
        nonlocal opened
        opened += 1
        if opened > 1 and not readback_available:
            raise OSError("synthetic unavailable independent readback")
        db = store.factory()
        commit = db.commit

        def lose_ack():
            nonlocal interrupted
            run = db.get(EltRun, run_id)
            if not interrupted and run.executed_rows == 2:
                interrupted = True
                if committed:
                    commit()
                raise OSError("synthetic lost commit acknowledgement")
            return commit()

        monkeypatch.setattr(db, "commit", lose_ack)
        return db

    monkeypatch.setattr(service_execution, "new_session", factory)
    execute(store, run_id, snapshot(store, run_id)["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, run_id)
    assert interrupted
    assert writes.call_count == 2
    assert current["status"] == (
        ("completed" if committed else "failed") if readback_available else "outcome_unknown"
    )
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == (2 if committed else 0)
        rows = db.query(EltRunRow).filter_by(run_id=run_id).order_by(EltRunRow.id).all()
        assert [r.execution_status for r in rows] == (["success"] * 2 if committed else [None] * 2)
        assert db.get(EltRun, run_id).executed_rows == (2 if committed else 0)
        if not readback_available:
            run = db.get(EltRun, run_id)
            token = run.operation_token
            run.operation_lease_until = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
            assert recover_stale_owner(db, run) is False
            assert run.status == "outcome_unknown" and run.operation_token == token
            with pytest.raises(EltError, match="已有活动任务或结果尚待核对"):
                claim_operation(db, run, "execute", allowed_statuses={"outcome_unknown"})
            db.rollback()
            with pytest.raises(EltError, match="当前运行无需重试"):
                store.service.retry(db, run_id=run_id, owner_user_id=7)


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"receipt": {}, "executed": True},
        {"receipt": {}, "executed": -1},
        {"receipt": {}, "executed": "2"},
        {"receipt": {}, "executed": 2.0},
        {"receipt": {}, "executed": 1},
        {"receipt": {}, "executed": 3},
        {"receipt": [], "executed": 2},
        {"receipt": {}, "executed": 2, "success": False},
    ],
)
def test_incomplete_batch_receipt_cannot_mark_all_rows_success(preview_store, monkeypatch, result):
    store = preview_store
    run_id = ready_preview(store, monkeypatch, target="export_csv")
    adapter = get_adapter("export_csv")
    send = Mock(return_value=result)
    monkeypatch.setattr(adapter, "execute_batch", send)
    execute(store, run_id, snapshot(store, run_id)["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    current = snapshot(store, run_id)
    assert send.call_count == 1
    assert current["status"] == "outcome_unknown"
    assert current["error_code"] == "ELT_OUTCOME_UNKNOWN"
    assert all(row["execution_status"] != "success" for row in current["persisted_rows"])
    with store.factory() as db:
        assert db.get(EltRun, run_id).executed_rows == 0
        assert load_json(db.get(EltRun, run_id).receipt_json, {}).get("batch_result") == result


@pytest.mark.parametrize("retain_owner", [True, False])
def test_batch_ack_survives_receipt_commit_failure_only_for_original_owner(
    preview_store, monkeypatch, retain_owner
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch, target="export_csv")
    result = {"executed": 2, "receipt": {"upstream_id": "synthetic-batch-ack"}}
    adapter = get_adapter("export_csv")
    send = Mock(return_value=result)
    monkeypatch.setattr(adapter, "execute_batch", send)
    fired = False

    def factory():
        db = store.factory()

        def before_commit(session):
            nonlocal fired
            if fired:
                return
            pending = next(
                (
                    item
                    for item in session.identity_map.values()
                    if isinstance(item, EltRun)
                    and item.id == run_id
                    and "batch_result" in load_json(item.receipt_json, {})
                ),
                None,
            )
            if pending is None:
                return
            fired = True
            if not retain_owner:
                with store.factory() as replacement:
                    run = replacement.get(EltRun, run_id)
                    run.operation_token = "replacement-owner"
                    run.receipt_json = dump_json({"replacement": "receipt"})
                    replacement.commit()
            raise OSError("synthetic receipt commit failure before database flush")

        event.listen(db, "before_commit", before_commit)
        return db

    monkeypatch.setattr(service_execution, "new_session", factory)
    execute(store, run_id, snapshot(store, run_id)["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    assert fired and send.call_count == 1
    with store.factory() as db:
        run = db.get(EltRun, run_id)
        if retain_owner:
            assert run.status == "outcome_unknown"
            assert load_json(run.receipt_json, {}) == {"batch_result": result}
        else:
            assert run.operation_token == "replacement-owner" and run.status == "executing"
            assert load_json(run.receipt_json, {}) == {"replacement": "receipt"}
        assert run.executed_rows == 0
        assert not any(
            row.execution_status == "success"
            for row in db.query(EltRunRow).filter_by(run_id=run_id)
        )


@pytest.mark.parametrize(
    "target,result,eligible,expected",
    [
        ("dynamic_table", {"executed": 1, "receipt": {"inserted": 1, "duplicates": 2}}, 3, 1),
        ("attendance", {"executed": 1, "receipt": {"executed": 1, "skipped": 2}}, 3, 1),
        ("attendance", {"executed": 0, "receipt": {"idempotent_replay": True}}, 0, 0),
        ("abnormal", {"executed": 0, "receipt": {"executed": 0}}, 0, 0),
    ],
)
def test_batch_count_preserves_explicit_deduplication(target, result, eligible, expected):
    assert service_execution._batch_executed(target, result, eligible) == expected


@pytest.mark.parametrize(
    "target,result",
    [
        ("dynamic_table", {"executed": 1, "receipt": {"inserted": 1, "duplicates": True}}),
        ("dynamic_table", {"executed": 1, "receipt": {"inserted": True, "duplicates": 1}}),
        ("dynamic_table", {"executed": 1, "receipt": {"inserted": 0, "duplicates": 1}}),
        ("attendance", {"executed": 1, "receipt": {"skipped": 1, "error_rows": 1}}),
    ],
)
def test_malformed_dedupe_receipts_cannot_cover_missing_rows(target, result):
    with pytest.raises(EltError, match="回执行数与确认范围不符"):
        service_execution._batch_executed(target, result, 2)
