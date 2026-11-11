"""Receipt polling yields database connections; empty rollback verifies ownership."""

from unittest.mock import ANY, MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from app.application.elt import auto_ingest_service as ais
from app.application.elt.errors import EltConflict, EltError
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_auto_ingest_service import ledger_root as ledger_root


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize(
    "kind", ["empty", "worker_bool", "written", "receipt_written", "forbidden", "incomplete"]
)
def test_empty_withdraw_checks_real_receipt_before_knowledge(monkeypatch, kind):
    batch = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "completed_empty",
        "business": {"run_id": "r"},
    }
    ais._save_ledger(42, {"batches": {"b": batch}})
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    fake = MagicMock()
    fake.get_run.return_value = {
        "id": "r",
        "receipt": {},
        "rollback_status": None,
        "status": "completed",
        "summary": {"executed": 0, "new": 0, "update": 0},
    }
    if kind == "written":
        fake.get_run.return_value["summary"]["executed"] = 1
    if kind == "receipt_written":
        fake.get_run.return_value["receipt"]["rows_written"] = 2
    if kind == "incomplete":
        fake.get_run.return_value["summary"] = {}
    if kind == "forbidden":
        fake.get_run.side_effect = EltError("FORBIDDEN", "owner denied", status_code=403)
    if kind == "worker_bool":
        fake.get_run.return_value["receipt"]["rows_written"] = False
    if kind in {"empty", "worker_bool"}:
        fake.rollback.side_effect = EltConflict("ELT_ROLLBACK_EMPTY", "本次运行没有已写入的数据")
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    knowledge = MagicMock(return_value={"rolled_back": True})
    monkeypatch.setattr(service, "_withdraw_knowledge", knowledge)
    with tenant_scope(42):
        if kind in {"forbidden", "incomplete"}:
            with pytest.raises(EltError):
                service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id="b")
            knowledge.assert_not_called()
            fake.rollback.assert_not_called()
            return
        result = service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id="b")
    assert result["status"] == "withdrawn"
    fake.get_run.assert_called_once_with(ANY, run_id="r", owner_user_id=7)
    knowledge.assert_called_once()
    if kind in {"empty", "worker_bool"}:
        fake.rollback.assert_not_called()
        assert result["withdraw"]["business"]["reason"] == "no_business_writes"
    else:
        fake.rollback.assert_called_once()


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize(
    "finish",
    [
        "completed",
        "initial_completed",
        "timeout",
        "read_error",
        "cancel",
        "release_error",
        "read_release_error",
    ],
)
def test_poll_returns_pool_connection_before_sleep_and_after_read(tmp_path, monkeypatch, finish):
    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0)
    fake = MagicMock()
    ready = {"target_type": "customers", "preview_revision": "v"}
    fake.get_run.return_value = ready
    calls = 0
    sleeps = []
    ticks = iter([0, 0, 0, 31])
    monkeypatch.setattr(ais.time, "monotonic", lambda: next(ticks))

    def sleep(_):
        sleeps.append(1)
        assert engine.pool.checkedout() == 0
        with engine.connect() as other:
            other.execute(text("select 1"))

    monkeypatch.setattr(ais.time, "sleep", sleep)
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    with Session(engine) as db:

        def read(*args, **kwargs):
            nonlocal calls
            calls += 1
            db.execute(text("select 1"))
            if calls == 1:
                return ready
            if finish == "read_error":
                raise RuntimeError("read failed")
            if finish == "cancel":
                raise KeyboardInterrupt()
            return {"status": "executing" if finish == "timeout" else "completed"}

        def execute(*args, **kwargs):
            db.commit()  # Match service.execute's durable queue-claim contract.
            db.execute(text("select 1"))  # Its final receipt opens another read.
            return {"status": "completed" if finish == "initial_completed" else "executing"}

        fake.get_run.side_effect = read
        fake.execute.side_effect = execute
        if finish == "release_error":
            monkeypatch.setattr(
                db, "rollback", MagicMock(side_effect=RuntimeError("release failed"))
            )
        if finish == "read_release_error":
            rollback = db.rollback
            releases = 0

            def release():
                nonlocal releases
                releases += 1
                if releases == 2:
                    raise RuntimeError("read release failed")
                rollback()

            monkeypatch.setattr(db, "rollback", release)
        try:
            with tenant_scope(42):
                result = ais.AutoIngestService()._ingest_business(
                    db,
                    owner_user_id=7,
                    path=tmp_path / "unused",
                    file_name="unused",
                    target_type="customers",
                    batch_id="b",
                    prepared_plan={
                        "run_id": "r",
                        "upload_id": "u",
                        "preview_revision": "v",
                        "target_type": "customers",
                    },
                )
            assert finish in {"completed", "initial_completed", "timeout"}
            assert result["pending_execution"] == (finish == "timeout")
        except (RuntimeError, KeyboardInterrupt):
            assert finish in {"read_error", "cancel", "release_error", "read_release_error"}
        if finish == "release_error":
            assert sleeps == []
            assert calls == 1
        elif finish == "read_release_error":
            assert len(sleeps) == 1
            assert calls == 2
        else:
            assert engine.pool.checkedout() == 0
            assert len(sleeps) == (0 if finish == "initial_completed" else 1)
        fake.execute.assert_called_once()
    assert engine.pool.checkedout() == 0
    engine.dispose()


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize("scope", ["owner", "tenant", "mod"])
def test_empty_withdraw_keeps_scope_gate(monkeypatch, scope):
    batch = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "completed_empty",
        "business": {"run_id": "r"},
    }
    ais._save_ledger(42, {"batches": {"b": batch}})
    monkeypatch.setattr(
        ais, "get_request_active_mod_id", lambda: "other" if scope == "mod" else "m"
    )
    fake = MagicMock()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    knowledge = MagicMock()
    monkeypatch.setattr(service, "_withdraw_knowledge", knowledge)
    with pytest.raises(EltError):
        service.withdraw(
            MagicMock(),
            tenant_id=99 if scope == "tenant" else 42,
            owner_user_id=8 if scope == "owner" else 7,
            batch_id="b",
        )
    knowledge.assert_not_called()
    fake.get_run.assert_not_called()
    fake.rollback.assert_not_called()
    assert ais._load_ledger(42)["batches"]["b"] == batch


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize(
    "fault",
    [
        "bool",
        "string",
        "negative",
        "missing_count",
        "missing_summary",
        "bad_summary",
        "missing_receipt",
        "bad_receipt",
        "rows_true",
        "rows_string",
        "rows_negative",
        "running",
        "unknown",
        "missing_run",
        "skipped",
    ],
)
def test_empty_withdraw_rejects_unproven_receipts(monkeypatch, fault):
    batch = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "completed_empty",
        "business": {"run_id": "r"},
    }
    current = {
        "id": "r",
        "status": "completed",
        "rollback_status": None,
        "summary": {"executed": 0, "new": 0, "update": 0},
        "receipt": {},
    }
    if fault in {"bool", "string", "negative"}:
        current["summary"]["executed"] = {"bool": False, "string": "0", "negative": -1}[fault]
    elif fault == "missing_count":
        current["summary"].pop("executed")
    elif fault.startswith("missing_") and fault != "missing_run":
        current.pop(fault.removeprefix("missing_"))
    elif fault in {"bad_summary", "bad_receipt"}:
        current[fault.removeprefix("bad_")] = []
    elif fault.startswith("rows_"):
        current["receipt"]["rows_written"] = {
            "rows_true": True,
            "rows_string": "0",
            "rows_negative": -1,
        }[fault]
    elif fault in {"running", "unknown"}:
        current["rollback_status"] = fault
    elif fault == "missing_run":
        batch["business"] = {}
    elif fault == "skipped":
        batch["business"]["skipped"] = True
    ais._save_ledger(42, {"batches": {"b": batch}})
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    fake = MagicMock()
    fake.get_run.return_value = current
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    knowledge = MagicMock()
    monkeypatch.setattr(service, "_withdraw_knowledge", knowledge)
    with pytest.raises(EltError, match="未撤回"):
        service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id="b")
    knowledge.assert_not_called()
    fake.rollback.assert_not_called()
    assert ais._load_ledger(42)["batches"]["b"] == batch


@pytest.mark.usefixtures("ledger_root")
def test_empty_withdraw_real_elt_run_zero_success_rows(tmp_path, monkeypatch):
    from app.application.elt.service import EltService
    from app.db.db_base import Base
    from app.db.models.elt import EltRun, EltRunRow, EltUpload

    engine = create_engine(f"sqlite:///{tmp_path / 'real-empty.db'}")
    Base.metadata.create_all(engine)
    actual = EltService()
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: actual)
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    batch = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "completed_empty",
        "business": {"run_id": "r"},
    }
    ais._save_ledger(42, {"batches": {"b": batch}})
    with tenant_scope(42), Session(engine) as db:
        db.add(
            EltUpload(
                id="u",
                tenant_id=42,
                owner_user_id=7,
                file_name="x.csv",
                suffix=".csv",
                size_bytes=1,
                sha256="a" * 64,
                storage_path="unused",
            )
        )
        db.flush()
        db.add(
            EltRun(
                id="r",
                tenant_id=42,
                owner_user_id=7,
                upload_id="u",
                target_type="products",
                status="completed",
                file_sha256="a" * 64,
                reversible=True,
            )
        )
        db.commit()
        assert (
            db.query(EltRunRow)
            .filter(EltRunRow.run_id == "r", EltRunRow.execution_status == "success")
            .count()
            == 0
        )
        receipt = actual.get_run(db, run_id="r", owner_user_id=7)
        assert receipt["summary"]["executed"] == 0
        service = ais.AutoIngestService()
        knowledge = MagicMock(return_value={"rolled_back": True})
        monkeypatch.setattr(service, "_withdraw_knowledge", knowledge)
        result = service.withdraw(db, tenant_id=42, owner_user_id=7, batch_id="b")
        assert result["status"] == "withdrawn"
        assert result["withdraw"]["business"]["reason"] == "no_business_writes"
        knowledge.assert_called_once()
        assert db.get(EltRun, "r").rollback_status is None
    engine.dispose()


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize("held", ["awaiting_confirmation", "withdrawn", "rejected"])
def test_mapping_failure_survives_only_reader_confirmation(tmp_path, monkeypatch, held):
    source = tmp_path / "order.csv"
    source.write_text("code,name\nM-1,demo\n", encoding="utf-8")
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    monkeypatch.setattr(
        ais,
        "enrich_knowledge_progress",
        lambda receipt, _tenant, progress: (receipt, progress("done", 100), {}),
    )
    service = ais.AutoIngestService()
    monkeypatch.setattr(service, "detect_target", lambda *_args, **_kwargs: {"target_type": "products"})
    monkeypatch.setattr(
        service, "_ingest_knowledge", lambda **_kwargs: {"action": "skip", "reason": "test"}
    )

    def refuse(*_args, **kwargs):
        ais._patch_batch(42, kwargs["batch_id"], status=held)
        raise EltConflict("ELT_MAPPING_CONFIRMATION_REQUIRED", "有歧义的字段尚未确认")

    monkeypatch.setattr(service, "_ingest_business", refuse)
    with pytest.raises(EltConflict):
        service.run(
            MagicMock(),
            owner_user_id=7,
            tenant_id=42,
            source_path=source,
            file_name="order.csv",
        )
    saved = next(iter(ais._load_ledger(42)["batches"].values()))
    if held == "awaiting_confirmation":
        assert saved["status"] == "failed"
        assert saved["error"] == "EltConflict"
    else:
        assert saved["status"] == held
        assert "error" not in saved
