"""The same ELT row transaction contract on SQLite and isolated PostgreSQL schemas."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import event

from app.application.elt import service_execution
from app.application.elt.errors import EltError
from app.application.elt.operation_owner import bind_owner, claim_operation, unbind_owner
from app.application.elt.service import EltService
from app.application.elt.service_support import dump_json
from app.application.elt.targets import get_adapter
from app.db.models import PurchaseUnit
from app.db.models.elt import EltRun, EltRunRow, EltUpload
from tests.test_application.test_etl_rollback_compare_swap import store as store


@pytest.mark.parametrize("store", ["sqlite", "postgres"], indirect=True)
@pytest.mark.parametrize("fault", ["row_flush", "commit_before", "commit_after"])
def test_row_savepoints_and_commit_ack_preserve_exactly_once_effects(store, monkeypatch, fault):
    _engine, factory, _ids = store
    monkeypatch.setattr(service_execution, "new_session", factory)
    with factory() as db:
        upload = EltUpload(
            id="transaction-upload",
            tenant_id=1,
            owner_user_id=7,
            file_name="synthetic.csv",
            suffix=".csv",
            size_bytes=0,
            sha256="a" * 64,
            storage_path="synthetic-not-parsed",
        )
        run = EltRun(
            id="transaction-run",
            tenant_id=1,
            owner_user_id=7,
            upload_id=upload.id,
            target_type="customers",
            status="executing",
            file_sha256=upload.sha256,
            executed_rows=0,
        )
        db.add(upload)
        db.flush()
        db.add(run)
        db.flush()
        rows = [
            EltRunRow(
                run_id=run.id,
                tenant_id=1,
                owner_user_id=7,
                source_row=index + 1,
                source_sheet="synthetic",
                normalized_json=dump_json({"customer_name": name}),
                final_action="new",
            )
            for index, name in enumerate(("事务客户甲", "事务客户乙"))
        ]
        db.add_all(rows)
        db.commit()
        owner = claim_operation(db, run, "execute", allowed_statuses={"executing"})
        bind_owner(db, owner)
        db.commit()
        adapter = get_adapter("customers")
        original = adapter.execute_row
        calls = []
        interrupted = False

        def write(session, data, **kwargs):
            calls.append(data["customer_name"])
            result = original(session, data, **kwargs)
            if fault == "row_flush" and data["customer_name"] == "事务客户乙":
                raise EltError("ELT_TEST_ROW_FAILURE", "synthetic failure after actual row flush")
            return result

        def commit_fault(session):
            nonlocal interrupted
            if session.in_nested_transaction() or interrupted:
                return
            interrupted = True
            raise OSError("synthetic transaction acknowledgement failure")

        monkeypatch.setattr(adapter, "execute_row", write)
        if fault != "row_flush":
            event.listen(
                db, "after_commit" if fault == "commit_after" else "before_commit", commit_fault
            )
        service = EltService(adviser=MagicMock())
        try:
            if fault == "commit_after":
                service._execute_rows(db, run, upload, adapter, rows, set(), {}, owner)
            else:
                with pytest.raises((EltError, OSError)):
                    service._execute_rows(db, run, upload, adapter, rows, set(), {}, owner)
        finally:
            unbind_owner(db)
        assert calls == ["事务客户甲", "事务客户乙"]
    with factory() as check:
        names = {
            item.unit_name
            for item in check.query(PurchaseUnit).filter(
                PurchaseUnit.unit_name.in_(["事务客户甲", "事务客户乙"])
            )
        }
        assert names == (
            {"事务客户甲", "事务客户乙"}
            if fault == "commit_after"
            else ({"事务客户甲"} if fault == "row_flush" else set())
        )
        saved = check.get(EltRun, "transaction-run")
        assert saved.executed_rows == len(names)
        receipts = check.query(EltRunRow).filter_by(run_id=saved.id).order_by(EltRunRow.id).all()
        assert [row.execution_status for row in receipts] == (
            ["success", "success"]
            if fault == "commit_after"
            else (["success", "failed"] if fault == "row_flush" else [None, None])
        )
