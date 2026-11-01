"""Auto-ingest: product KB write + business domain wiring + withdraw."""

from __future__ import annotations

import os
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


@pytest.mark.parametrize(
    "reader",
    [
        ais._extract_text,
        ais.detect_etl_target,
        ais._resolve_auto_ingest_source,
        AutoIngestService.detect_target,
    ],
)
@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
@pytest.mark.parametrize("attack", ["outside", "leaf_swap", "parent_swap"])
def test_auto_ingest_readers_reject_untrusted_or_swapped_files(
    tmp_path, monkeypatch, reader, suffix, attack
):
    from app.application import shipment_excel_etl_security as security
    from app.application.elt.errors import EltError

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    parent = allowed / "incoming"
    parent.mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    source = parent / f"客户😀{suffix}"
    secret = outside / source.name
    for path in (source, secret):
        if suffix == ".xlsx":
            _shipment_xlsx(path)
        else:
            path.write_text("送货单,产品名称,数量\n", encoding="utf-8-sig")
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    if attack == "outside":
        source = secret
    else:
        probe = allowed / "link-probe"
        try:
            probe.symlink_to(secret)
            probe.unlink()
        except OSError as exc:
            if os.name == "nt":
                pytest.skip(f"Windows symlink privilege unavailable: {exc}")
            raise
        original = security._open_directory_under_root

        def replace_after_pin(*args, **kwargs):
            fd = original(*args, **kwargs)
            try:
                source.unlink()
                source.symlink_to(secret)
            except OSError:
                os.close(fd)
                raise
            return fd

        if attack == "parent_swap":
            original_resolve = security.resolve_etl_path

            def replace_after_resolve(*args, **kwargs):
                resolved = original_resolve(*args, **kwargs)
                parent.rename(allowed / "original")
                parent.symlink_to(outside, target_is_directory=True)
                return resolved

            monkeypatch.setattr(security, "resolve_etl_path", replace_after_resolve)
        else:
            monkeypatch.setattr(security, "_open_directory_under_root", replace_after_pin)
    with pytest.raises((security.ShipmentEtlPathError, EltError, OSError)):
        reader(source)


def test_auto_ingest_csv_keeps_bom_and_newline_semantics(tmp_path, monkeypatch):
    from app.application import shipment_excel_etl_security as security

    source = tmp_path / "客户😀.csv"
    source.write_bytes("送货单,产品名称,数量\r\n商品,油漆,2\r\n".encode("utf-8-sig"))
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [tmp_path])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    assert ais.detect_etl_target(source)["target_type"] == "shipment_records"
    assert ais._extract_text(source) == "\ufeff送货单,产品名称,数量\n商品,油漆,2\n"


@pytest.mark.parametrize("suffix", [".csv", ".xlsx"])
def test_saved_upload_detection_preserves_owner_and_tenant_boundary(tmp_path, monkeypatch, suffix):
    import io

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.application import shipment_excel_etl_security as security
    from app.application.elt.errors import EltError, EltNotFound
    from app.application.elt.service_uploads import UploadServiceMixin
    from app.db.models.elt import EltUpload
    from app.db.tenant_filter import install_tenant_filter

    install_tenant_filter()
    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    service = UploadServiceMixin()
    content = io.BytesIO("送货单,产品名称,数量\n油漆,产品,2\n".encode())
    if suffix == ".xlsx":
        workbook = Workbook()
        workbook.active.append(["送货单", "产品名称", "数量"])
        content = io.BytesIO()
        workbook.save(content)
        workbook.close()
        content.seek(0)
    engine = create_engine("sqlite://")
    EltUpload.__table__.create(engine)
    try:
        with Session(engine) as db, tenant_scope(42):
            receipt = service.save_upload(
                db,
                owner_user_id=7,
                file_name=f"客户😀{suffix}",
                content_type=None,
                stream=content,
            )
            source = service._owned_upload(db, receipt["upload_id"], 7)
            assert (
                ais.detect_etl_target(source.storage_path, owner_user_id=7)["target_type"]
                == "shipment_records"
            )
            with pytest.raises(EltError):
                ais._resolve_auto_ingest_source(source.storage_path)
            with pytest.raises(security.ShipmentEtlPathError):
                ais.detect_etl_target(source.storage_path, owner_user_id=8)
            with tenant_scope(43), pytest.raises(security.ShipmentEtlPathError):
                ais.detect_etl_target(source.storage_path, owner_user_id=7)
            with pytest.raises(EltNotFound):
                service._owned_upload(db, receipt["upload_id"], 8)
            with tenant_scope(43), pytest.raises(EltNotFound):
                service._owned_upload(db, receipt["upload_id"], 7)
            private = tmp_path / "etl" / "auto_ingest" / "batches.csv"
            private.parent.mkdir()
            private.write_text("private")
            with pytest.raises(security.ShipmentEtlPathError):
                ais.detect_etl_target(private)
    finally:
        engine.dispose()


@pytest.mark.parametrize("operation", ["validate", "upload"])
def test_prepared_hash_and_business_upload_reject_outside_input(tmp_path, monkeypatch, operation):
    from app.application import shipment_excel_etl_security as security

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "private.csv"
    outside.write_text("private")
    monkeypatch.setattr(security, "_trusted_base_roots", lambda: [allowed])
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    service = AutoIngestService()
    with pytest.raises(security.ShipmentEtlPathError):
        if operation == "validate":
            db = MagicMock()
            run = db.query.return_value.filter.return_value.first.return_value
            run.target_type, run.upload_id, run.file_sha256 = "customers", "up-1", "sha"
            plan = {
                "target_type": "customers",
                "upload_id": "up-1",
                "candidate_sha256": "sha",
                "mod_id": ais.get_request_active_mod_id(),
            }
            service.validate_prepared(
                db,
                plan=plan,
                path=outside,
                owner_user_id=7,
                tenant_id=42,
                preview_revision="rev-1",
            )
        else:
            service._ingest_business(
                MagicMock(),
                owner_user_id=7,
                path=outside,
                file_name=outside.name,
                target_type="customers",
                batch_id="batch-1",
            )


@pytest.mark.parametrize("component", ["tenant", "owner"])
def test_owned_upload_root_swap_cannot_change_identity(tmp_path, monkeypatch, component):
    from app.application import shipment_excel_etl_security as security

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    tenant_root = tmp_path / "etl" / "uploads" / "42"
    owner_root = tenant_root / "7"
    owner_root.mkdir(parents=True)
    source = owner_root / "input.csv"
    source.write_text("own")
    victim = tmp_path / "etl" / "uploads" / "43" / "7"
    victim.mkdir(parents=True)
    secret = victim / "input.csv"
    secret.write_text("other tenant")
    swap = tenant_root if component == "tenant" else owner_root
    target = victim.parent if component == "tenant" else victim
    original = security._open_directory_under_root

    def swap_before_pin(*args, **kwargs):
        swap.rename(swap.with_name(swap.name + "-original"))
        try:
            swap.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if os.name == "nt":
                pytest.skip(f"Windows symlink privilege unavailable: {exc}")
            raise
        return original(*args, **kwargs)

    monkeypatch.setattr(security, "_open_directory_under_root", swap_before_pin)
    with tenant_scope(42), pytest.raises(security.ShipmentEtlPathError):
        with security.open_etl_input_file(source, owner_user_id=7):
            pytest.fail("a swapped tenant/owner directory must not be followed")
    with tenant_scope(42), pytest.raises(security.ShipmentEtlPathError):
        with security.open_etl_input_file(secret, owner_user_id=7):
            pytest.fail("canonicalizing a swapped root must not authorize another tenant")


@pytest.mark.parametrize("background", [False, True])
def test_raw_auto_ingest_cannot_supply_upload_owner_or_prepared_plan(
    tmp_path, monkeypatch, background
):
    from types import SimpleNamespace

    from app.application.elt.errors import EltError
    from app.fastapi_routes.elt_auto_ingest import auto_ingest

    monkeypatch.setenv("XCAGI_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    source = tmp_path / "etl" / "uploads" / "43" / "8" / "private.csv"
    source.parent.mkdir(parents=True)
    source.write_text("private")
    monkeypatch.setattr(ais, "get_auto_ingest_service", AutoIngestService)
    with tenant_scope(42), pytest.raises(EltError) as error:
        auto_ingest(
            {
                "source_path": str(source),
                "async": background,
                "owned_upload_user_id": 8,
                "prepared_plan": {"run_id": "forged"},
            },
            db=MagicMock(),
            user=SimpleNamespace(id=7),
        )
    assert error.value.code == "ETL_AUTO_INGEST_PATH_INVALID"
