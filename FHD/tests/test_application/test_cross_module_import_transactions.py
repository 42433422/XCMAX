"""Real database checks for approved import atomicity and durable replay."""

from copy import deepcopy

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.application.agent_orchestrator.cross_module_chain import _approval_fingerprint
from app.application.agent_orchestrator.cross_module_execution import _import_approved_products
from app.application.elt.targets.products import ProductAdapter
from app.db.db_base import Base
from app.db.models.product import Product
from app.db.models.task_lifecycle import TaskLifecycleIdempotency, TaskLifecycleRecord
from app.domain.task_lifecycle.control import SessionBook, TaskLifecycleError
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def import_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'import.sqlite3'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    assert "cross_module_delivery" not in inspect(engine).get_table_names()
    engine.dispose()


@pytest.fixture
def approved_import():
    checkpoint = {
        "tenant_id": "1",
        "user_id": "7",
        "task_id": "task-import",
        "run_id": "run-import",
        "idempotency_key": "task-import-key",
        "source_path": "/uploaded/source.xlsx",
        "original_sha256": "f" * 64,
        "qualifying": [
            {"unit": "西南材料", "model_number": "SW-42", "name": "涂层", "price": "17.65"},
            {"unit": "东海配件", "model_number": "DH-5", "name": "密封件", "price": "63.20"},
        ],
    }
    checkpoint["approval_fingerprint"] = _approval_fingerprint(
        checkpoint,
        {"products": checkpoint["qualifying"], "file_path": checkpoint["source_path"]},
    )
    return checkpoint


@pytest.mark.parametrize("failure_stage", ["second_product", "receipt"])
def test_import_and_receipt_roll_back_together(
    import_database, approved_import, monkeypatch, failure_stage
):
    staged_counts = []
    execute = ProductAdapter.execute_row
    put = SessionBook.put

    def fail_on_second(adapter, db, *args, **kwargs):
        if db.query(Product).count() == 1:
            staged_counts.append(1)
            raise OSError("interrupted product write")
        return execute(adapter, db, *args, **kwargs)

    def fail_after_receipt(book, *args, **kwargs):
        put(book, *args, **kwargs)
        staged_counts.append(book._db.query(Product).count())
        raise OSError("interrupted receipt write")

    if failure_stage == "second_product":
        monkeypatch.setattr(ProductAdapter, "execute_row", fail_on_second)
    else:
        monkeypatch.setattr(SessionBook, "put", fail_after_receipt)
    with tenant_scope(1), pytest.raises(OSError), import_database.begin() as db:
        _import_approved_products(db, approved_import, approved_import["qualifying"])
    assert staged_counts == [1 if failure_stage == "second_product" else 2]
    with import_database() as db, tenant_scope(1):
        assert db.query(Product).count() == 0
        assert db.query(TaskLifecycleRecord).count() == 0
        assert db.query(TaskLifecycleIdempotency).count() == 0


@pytest.mark.parametrize("changed_field", ["price", "user_id"])
def test_committed_import_replays_across_sessions_and_rejects_changed_approval(
    import_database, approved_import, changed_field
):
    with import_database.begin() as db, tenant_scope(1):
        initial, count = _import_approved_products(
            db, approved_import, approved_import["qualifying"]
        )
        assert initial["replayed"] is False
        assert count == 2
    # The next executor has no in-memory receipt and reads the committed database.
    with import_database.begin() as db, tenant_scope(1):
        replay, count = _import_approved_products(
            db, approved_import, approved_import["qualifying"]
        )
        assert replay["replayed"] is True
        assert count == 2
    changed = deepcopy(approved_import)
    if changed_field == "price":
        changed["qualifying"][0]["price"] = "999.00"
    else:
        changed["user_id"] = "8"
    changed["approval_fingerprint"] = _approval_fingerprint(
        changed, {"products": changed["qualifying"], "file_path": changed["source_path"]}
    )
    with tenant_scope(1), pytest.raises(TaskLifecycleError), import_database.begin() as db:
        _import_approved_products(db, changed, changed["qualifying"])
    with import_database() as db, tenant_scope(1):
        assert sorted((row.model_number, str(row.price)) for row in db.query(Product)) == [
            ("DH-5", "63.20"),
            ("SW-42", "17.65"),
        ]
        # The import transaction stores the delivery receipt and the HTTP body together.
        assert sorted(row.module for row in db.query(TaskLifecycleRecord)) == [
            "cross_module_http_response",
            "cross_module_import",
        ]
        assert db.query(TaskLifecycleIdempotency).count() == 1
