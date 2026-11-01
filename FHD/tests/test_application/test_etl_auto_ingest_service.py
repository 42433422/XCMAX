"""Auto-ingest: product KB write + business domain wiring + withdraw."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook

from app.application import dataset_rag_app_service as rag
from app.application.elt import auto_ingest_service as ais
from app.application.elt.auto_ingest_service import AutoIngestService
from app.infrastructure.tenant_scope import tenant_scope


@pytest.fixture
def rag_service(tmp_path, monkeypatch):
    svc = rag.DatasetRagApplicationService(
        embedder=lambda text: [1.0, 0.0],
        storage_path=tmp_path / "knowledge.json",
        allowed_roots=[tmp_path],
        rebuild_workers_enabled=False,
    )
    monkeypatch.setattr(rag, "get_dataset_rag_app_service", lambda: svc)
    return svc


@pytest.fixture
def ledger_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ais, "get_app_data_dir", lambda: str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def allow_tmp_ingest_paths(tmp_path, monkeypatch):
    """Trust only this test's workspace through the real ETL path resolver."""
    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))


def _shipment_xlsx(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "出货"
    ws.append(["送货单", "客户鑫顺"])
    ws.append(["购货单位", "鑫顺家私", "订单编号", "26-0100012A"])
    ws.append(["产品名称", "数量", "规格"])
    ws.append(["PE特清底漆", "5", "25"])
    wb.save(path)
    return path


def test_auto_ingest_writes_knowledge_and_records_business(
    rag_service, ledger_root, allow_tmp_ingest_paths, tmp_path, monkeypatch
):
    xlsx = _shipment_xlsx(tmp_path / "26鑫顺.xlsx")
    fake_etl = MagicMock()
    fake_etl.save_upload.return_value = {"upload_id": "up-1"}
    fake_etl.create_preview.return_value = {
        "id": "run-1",
        "status": "preview_ready",
        "preview_revision": "rev-1",
    }
    fake_etl.execute.return_value = {
        "id": "run-1",
        "status": "completed",
        "summary": {"new": 1, "update": 0, "skip": 0, "error": 0, "executed": 1},
    }
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake_etl)

    service = AutoIngestService()
    with tenant_scope(42):
        batch = service.run(
            MagicMock(),
            owner_user_id=7,
            tenant_id=42,
            source_path=xlsx,
            file_name="26鑫顺.xlsx",
            template_id="tpl-1",
            review_id="rev-excel-1",
            labels=["出货", "送货单"],
            composer_note="整理要求：保留客户与单号",
        )

    assert batch["status"] == "applied"
    assert batch["detection"]["target_type"] == "shipment_records"
    assert batch["knowledge"]["match_ref"]
    assert batch["knowledge"]["action"] in {"new", "update"}
    assert batch["business"]["target_type"] == "shipment_records"
    assert batch["business"]["run_id"] == "run-1"
    fake_etl.create_preview.assert_called_once()
    fake_etl.execute.assert_called_once()

    docs = rag_service.status(dataset_id="office-docking", tenant_id="42")["documents"]
    assert any(d.get("document_id") == batch["knowledge"]["match_ref"] for d in docs)

    listed = service.list_batches(tenant_id=42, owner_user_id=7)
    assert listed[0]["batch_id"] == batch["batch_id"]


def test_auto_ingest_withdraw_rolls_back_kb_and_business(
    rag_service, ledger_root, allow_tmp_ingest_paths, tmp_path, monkeypatch
):
    xlsx = _shipment_xlsx(tmp_path / "ship.xlsx")
    fake_etl = MagicMock()
    fake_etl.save_upload.return_value = {"upload_id": "up-2"}
    fake_etl.create_preview.return_value = {
        "id": "run-2",
        "status": "preview_ready",
        "preview_revision": "rev-2",
    }
    fake_etl.execute.return_value = {"id": "run-2", "status": "completed", "summary": {}}
    fake_etl.rollback.return_value = {"id": "run-2", "rollback_status": "completed"}
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake_etl)

    service = AutoIngestService()
    with tenant_scope(9):
        batch = service.run(
            MagicMock(),
            owner_user_id=3,
            tenant_id=9,
            source_path=xlsx,
            file_name="ship.xlsx",
            labels=["出货"],
        )
        doc_id = batch["knowledge"]["match_ref"]
        assert rag_service.status(dataset_id="office-docking", tenant_id="9")["documents"]

        withdrawn = service.withdraw(
            MagicMock(), tenant_id=9, owner_user_id=3, batch_id=batch["batch_id"]
        )

    assert withdrawn["status"] == "withdrawn"
    fake_etl.rollback.assert_called_once()
    docs_after = rag_service.status(dataset_id="office-docking", tenant_id="9")["documents"]
    assert all(d.get("document_id") != doc_id for d in docs_after)


def test_auto_ingest_progress_tracks_real_stages(
    rag_service, ledger_root, allow_tmp_ingest_paths, tmp_path, monkeypatch
):
    xlsx = _shipment_xlsx(tmp_path / "progress.xlsx")
    fake_etl = MagicMock()
    fake_etl.save_upload.return_value = {"upload_id": "up-p"}
    fake_etl.create_preview.return_value = {
        "id": "run-p",
        "status": "preview_ready",
        "preview_revision": "rev-p",
    }
    fake_etl.execute.return_value = {
        "id": "run-p",
        "status": "completed",
        "summary": {"new": 1, "update": 0, "skip": 0, "error": 0, "executed": 1},
    }
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake_etl)

    service = AutoIngestService()
    with tenant_scope(7):
        batch = service.run(
            MagicMock(),
            owner_user_id=3,
            tenant_id=7,
            source_path=xlsx,
            file_name="progress.xlsx",
            labels=["出货"],
        )
        progress = service.get_progress(tenant_id=7, owner_user_id=3, batch_id=batch["batch_id"])

    assert progress["status"] == "applied"
    assert progress["kb_progress"]["pct"] == 100
    assert progress["business_progress"]["pct"] == 100
    assert progress["kb_progress"]["stage"] in {"done", "skipped"}
    assert progress["business_progress"]["stage"] == "done"


@pytest.mark.parametrize("terminal", ["completed", "failed", "interrupted", "outcome_unknown"])
def test_async_business_receipts_follow_actual_run_without_reexecution(
    rag_service, ledger_root, allow_tmp_ingest_paths, tmp_path, monkeypatch, terminal
):
    from contextlib import nullcontext

    fake = MagicMock()
    fake.save_upload.return_value = {"upload_id": "up-async"}
    fake.create_preview.return_value = {
        "id": "run-async",
        "status": "preview_ready",
        "preview_revision": "rev",
    }
    fake.execute.return_value = {
        "id": "run-async",
        "status": "executing",
        "summary": {"executed": 0},
    }
    fake.get_run.return_value = {
        "id": "run-async",
        "status": "executing",
        "progress": 30,
        "summary": {"executed": 0},
    }
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    monkeypatch.setattr("app.db.session.get_db", lambda: nullcontext(MagicMock()))
    service = AutoIngestService()
    with tenant_scope(42):
        batch = service.run(
            MagicMock(),
            owner_user_id=7,
            tenant_id=42,
            source_path=_shipment_xlsx(tmp_path / "async.xlsx"),
            file_name="async.xlsx",
        )
        assert batch["status"] == "running"
        assert batch["business_progress"]["pct"] < 100
        assert (
            service.get_progress(tenant_id=42, owner_user_id=7, batch_id=batch["batch_id"])[
                "status"
            ]
            == "running"
        )
        fake.get_run.return_value = {
            "id": "run-async",
            "status": terminal,
            "progress": 100,
            "summary": {"executed": 1},
        }
        final = service.get_progress(tenant_id=42, owner_user_id=7, batch_id=batch["batch_id"])
        assert final["status"] == ("applied" if terminal == "completed" else "failed")
        assert final["kb_progress"]["pct"] == 100
        assert (
            service.list_batches(tenant_id=42, owner_user_id=7)[0]["business"]["summary"][
                "executed"
            ]
            == 1
        )
        fake.execute.assert_called_once()
        ais._patch_batch(42, batch["batch_id"], status="withdrawn")
        assert service._refresh_business(batch)["status"] == "withdrawn"


def test_business_failure_preserves_completed_knowledge_receipt(
    rag_service, ledger_root, allow_tmp_ingest_paths, tmp_path, monkeypatch
):
    from app.application.elt.errors import EltError

    fake = MagicMock()
    fake.save_upload.return_value = {"upload_id": "up-error"}
    fake.create_preview.return_value = {
        "id": "run-error",
        "status": "preview_ready",
        "preview_revision": "rev",
    }
    fake.execute.side_effect = EltError("ELT_PREVIEW_STALE", "业务预演已变化")
    monkeypatch.setattr("app.application.elt.service.get_elt_service", lambda: fake)
    with tenant_scope(42), pytest.raises(EltError):
        AutoIngestService().run(
            MagicMock(),
            owner_user_id=7,
            tenant_id=42,
            source_path=_shipment_xlsx(tmp_path / "error.xlsx"),
            file_name="error.xlsx",
        )
    saved = next(iter(ais._load_ledger(42)["batches"].values()))
    assert saved["status"] == "failed"
    assert saved["knowledge"]["match_ref"]
    assert saved["kb_progress"]["pct"] == 100
    assert saved["business"]["run_id"] == "run-error"
    assert "勿重复提交" in saved["business_progress"]["message"]
