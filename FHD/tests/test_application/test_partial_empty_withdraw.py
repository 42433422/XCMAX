"""Incomplete coverage must not turn zero-write withdrawal into destructive rollback."""

from unittest.mock import MagicMock

import pytest

from app.application.elt import auto_ingest_service as ais
from app.application.elt.errors import EltConflict
from app.application.elt.service import EltService
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_elt_auto_ingest_service import (
    _candidate_plan,
    _shipment_xlsx,
)
from tests.test_application.test_elt_auto_ingest_service import (
    allow_tmp_ingest_paths as allow_tmp_ingest_paths,
)
from tests.test_application.test_elt_auto_ingest_service import (
    ledger_root as ledger_root,
)
from tests.test_application.test_elt_auto_ingest_service import (
    rag_service as rag_service,
)


@pytest.mark.usefixtures("rag_service", "ledger_root", "allow_tmp_ingest_paths")
def test_duplicate_and_invalid_rows_partial_withdraws_without_empty_rollback(
    tmp_path, monkeypatch, rag_service
):
    assert EltService  # Import real service before candidate path fixtures replace providers.
    source = _shipment_xlsx(tmp_path / "data/elt/uploads/42/7/mixed.xlsx")
    fake = MagicMock()
    plan = _candidate_plan(fake, monkeypatch, "r", source)
    plan["valid_rows_only"] = True
    receipt = {
        "id": "r",
        "status": "completed",
        "rollback_status": None,
        "summary": {"executed": 0, "new": 0, "update": 0, "skip": 1, "error": 1},
        "receipt": {"rows_written": False},
    }
    fake.execute.return_value = receipt
    fake.rollback.side_effect = EltConflict("ELT_ROLLBACK_EMPTY", "本次运行没有已写入的数据")
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    with tenant_scope(42):
        result = service.run(
            MagicMock(), owner_user_id=7, tenant_id=42, source_path=source, prepared_plan=plan
        )
        assert result["status"] == "completed_empty"
        assert not result["coverage"]["complete"]
        assert result["coverage"]["business_rows"]["error"] == 1
        fake.get_run.return_value = receipt
        withdrawn = service.withdraw(
            MagicMock(), tenant_id=42, owner_user_id=7, batch_id=result["batch_id"]
        )
    assert withdrawn["status"] == "withdrawn"
    assert withdrawn["withdraw"]["business"]["reason"] == "no_business_writes"
    fake.rollback.assert_not_called()
    fake.execute.assert_called_once()
    assert fake.execute.call_args.kwargs["valid_rows_only"] is True
    docs = rag_service.status(dataset_id="office-docking", tenant_id="42")["documents"]
    assert not any(d.get("document_id") == result["knowledge"]["match_ref"] for d in docs)


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize("batch_status", ["applied", "partial", "completed_empty"])
@pytest.mark.parametrize(
    "outcome",
    [
        "zero",
        "written",
        "unknown",
        "failed_zero",
        "failed_written",
        "interrupted_written",
        "knowledge",
        "missing",
        "skipped",
    ],
)
def test_all_withdraw_states_verify_business_before_knowledge(monkeypatch, batch_status, outcome):
    from app.application.elt.errors import EltError

    batch = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": batch_status,
        "business": {"run_id": "r"},
    }
    current = {
        "id": "r",
        "status": "completed",
        "rollback_status": None,
        "summary": {"executed": 0, "new": 0, "update": 0},
        "receipt": {"rows_written": False},
    }
    if "written" in outcome:
        current["summary"]["executed"] = 1
        current["receipt"]["rows_written"] = True
    if outcome.startswith("failed"):
        current["status"] = "failed"
    if outcome.startswith("interrupted"):
        current["status"] = "interrupted"
    if outcome == "unknown":
        current["summary"] = {}
    if outcome == "knowledge":
        batch["business"] = {
            "skipped": True,
            "reason": "knowledge_only_target",
            "target_type": "knowledge",
        }
    if outcome == "missing":
        batch["business"] = {}
    if outcome == "skipped":
        batch["business"] = {"skipped": True}
    ais._save_ledger(42, {"batches": {"b": batch}})
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    fake = MagicMock()
    fake.get_run.return_value = current
    fake.rollback.return_value = {"rollback_status": "completed"}
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    knowledge = MagicMock(return_value={"rolled_back": True})
    monkeypatch.setattr(service, "_withdraw_knowledge", knowledge)
    if outcome in {"unknown", "failed_zero", "missing", "skipped"}:
        with pytest.raises(EltError):
            service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id="b")
        knowledge.assert_not_called()
        fake.rollback.assert_not_called()
        return
    result = service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id="b")
    assert result["status"] == "withdrawn"
    knowledge.assert_called_once()
    assert fake.rollback.call_count == (1 if "written" in outcome else 0)


@pytest.mark.usefixtures("ledger_root", "allow_tmp_ingest_paths")
@pytest.mark.parametrize("failure", ["knowledge", "ledger", "persist_before", "persist_after"])
def test_withdraw_recovers_after_business_commit_without_repeating_business(
    tmp_path, monkeypatch, rag_service, failure
):
    source = _shipment_xlsx(tmp_path / "data/elt/uploads/42/7/recover.xlsx")
    fake = MagicMock()
    plan = _candidate_plan(fake, monkeypatch, "r", source)
    receipt = {
        "id": "r",
        "status": "completed",
        "rollback_status": None,
        "summary": {"executed": 1, "new": 1, "update": 0, "error": 0},
        "receipt": {"rows_written": True},
    }
    fake.execute.return_value = receipt
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    with tenant_scope(42):
        batch = service.run(
            MagicMock(), owner_user_id=7, tenant_id=42, source_path=source, prepared_plan=plan
        )
        fake.get_run.return_value = receipt

        def rollback(*args, **kwargs):
            receipt["rollback_status"] = "completed"
            receipt["receipt"]["rollback"] = {
                "status": "completed",
                "rows": 1,
                "at": "2026-11-11T01:00:00+00:00",
            }
            return receipt

        fake.rollback.side_effect = rollback
        if failure == "knowledge":
            original = service._withdraw_knowledge
            calls = []

            def withdraw_knowledge(batch):
                calls.append(1)
                if len(calls) == 1:
                    raise OSError("temporary KB failure")
                return original(batch)

            monkeypatch.setattr(service, "_withdraw_knowledge", withdraw_knowledge)
        elif failure.startswith("persist_"):
            original_persist = rag_service._repository._persist_locked
            calls = []

            def persist():
                calls.append(1)
                if len(calls) == 1:
                    if failure == "persist_after":
                        original_persist()
                    raise OSError("knowledge persistence interrupted")
                return original_persist()

            monkeypatch.setattr(rag_service._repository, "_persist_locked", persist)
        else:
            original_save = ais._save_ledger
            calls = []

            def save(tenant, ledger):
                if ledger["batches"][batch["batch_id"]]["status"] == "withdrawn":
                    calls.append(1)
                    if len(calls) == 1:
                        raise OSError("disk failure after knowledge delete")
                return original_save(tenant, ledger)

            monkeypatch.setattr(ais, "_save_ledger", save)
        with pytest.raises(OSError):
            service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id=batch["batch_id"])
        result = service.withdraw(
            MagicMock(), tenant_id=42, owner_user_id=7, batch_id=batch["batch_id"]
        )
    assert result["status"] == "withdrawn"
    fake.rollback.assert_called_once()
    assert len(calls) == (1 if failure == "persist_after" else 2)
    docs = rag_service.status(dataset_id="office-docking", tenant_id="42")["documents"]
    assert not any(d.get("document_id") == batch["knowledge"]["match_ref"] for d in docs)
    from app.application.dataset_rag_app_service import DatasetRagApplicationService

    rebuilt = DatasetRagApplicationService(
        embedder=lambda text: [1.0, 0.0],
        storage_path=rag_service._repository.storage_path,
        allowed_roots=[tmp_path],
        rebuild_workers_enabled=False,
    )
    durable_docs = rebuilt.status(dataset_id="office-docking", tenant_id="42")["documents"]
    assert not any(d.get("document_id") == batch["knowledge"]["match_ref"] for d in durable_docs)


@pytest.mark.usefixtures("ledger_root")
@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "bad_status",
        "zero",
        "bool",
        "bad_at",
        "naive_at",
        "running",
        "outcome_unknown",
        "expired",
        "unexpected",
        "failed",
        "contradictory",
    ],
)
def test_completed_rollback_requires_strict_recovery_receipt(monkeypatch, fault):
    from app.application.elt.errors import EltError

    batch = {
        "batch_id": "b",
        "tenant_id": 42,
        "owner_user_id": 7,
        "mod_id": "m",
        "status": "applied",
        "business": {"run_id": "r"},
    }
    rollback = {"status": "completed", "rows": 1, "at": "2026-11-11T01:00:00+00:00"}
    current = {
        "id": "r",
        "status": "completed",
        "rollback_status": "completed",
        "summary": {"executed": 1, "new": 1, "update": 0},
        "receipt": {"rows_written": True, "rollback": rollback},
    }
    if fault == "missing":
        current["receipt"].pop("rollback")
    elif fault == "bad_status":
        rollback["status"] = "running"
    elif fault in {"zero", "bool"}:
        rollback["rows"] = 0 if fault == "zero" else True
    elif fault in {"bad_at", "naive_at"}:
        rollback["at"] = "bad" if fault == "bad_at" else "2026-11-11T01:00:00"
    elif fault == "contradictory":
        current["summary"] = {"executed": 0, "new": 0, "update": 0}
        current["receipt"]["rows_written"] = False
    else:
        current["rollback_status"] = fault
    ais._save_ledger(42, {"batches": {"b": batch}})
    monkeypatch.setattr(ais, "get_request_active_mod_id", lambda: "m")
    fake = MagicMock()
    fake.get_run.return_value = current
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    knowledge = MagicMock()
    monkeypatch.setattr(service, "_withdraw_knowledge", knowledge)
    with pytest.raises(EltError):
        service.withdraw(MagicMock(), tenant_id=42, owner_user_id=7, batch_id="b")
    fake.rollback.assert_not_called()
    knowledge.assert_not_called()


@pytest.mark.usefixtures("ledger_root", "allow_tmp_ingest_paths")
@pytest.mark.parametrize("disk", ["present", "corrupt", "null_dataset", "bad_version"])
def test_missing_memory_is_not_proof_of_durable_knowledge_delete(
    tmp_path, monkeypatch, rag_service, disk
):
    source = _shipment_xlsx(tmp_path / "data/elt/uploads/42/7/durable.xlsx")
    fake = MagicMock()
    plan = _candidate_plan(fake, monkeypatch, "r", source)
    fake.execute.return_value = {
        "id": "r",
        "status": "completed",
        "summary": {"executed": 0, "new": 0, "update": 0},
    }
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    service = ais.AutoIngestService()
    with tenant_scope(42):
        batch = service.run(
            MagicMock(), owner_user_id=7, tenant_id=42, source_path=source, prepared_plan=plan
        )
        repository = rag_service._repository
        if disk == "corrupt":
            repository.storage_path.write_text("{broken", encoding="utf-8")
        if disk in {"null_dataset", "bad_version"}:
            import json

            snapshot = json.loads(repository.storage_path.read_text(encoding="utf-8"))
            if disk == "null_dataset":
                snapshot["datasets"]["office-docking"] = None
            else:
                snapshot["version"] = True
            repository.storage_path.write_text(json.dumps(snapshot), encoding="utf-8")
        repository.datasets = {}
        repository.lock.revision = repository.lock.revision_now()
        with pytest.raises((RuntimeError, ValueError)):
            service._withdraw_knowledge(batch)
