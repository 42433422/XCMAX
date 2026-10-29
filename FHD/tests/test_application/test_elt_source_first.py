"""ELT loading commits complete raw evidence before any mapping or transformation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.application.etl import service_draft, service_preview, service_preview_worker
from app.application.etl.errors import EtlError
from app.application.etl.parser_types import ParsedDataset, ParsedRow
from app.application.etl.service_support import dump_json, load_json
from app.db.models import PurchaseUnit
from app.db.models.etl import EtlRun, EtlRunRow, EtlUpload
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_preview_task_boundaries import (
    create_preview,
    snapshot,
)
from tests.test_application.test_etl_preview_task_boundaries import (
    preview_store as preview_store,
)


def wait_for_job(store):
    store.executor.futures[-1].result(timeout=10)


def raw_rows(db, run_id):
    return db.query(EtlRunRow).filter(EtlRunRow.run_id == run_id).order_by(EtlRunRow.id).all()


def test_complete_raw_rows_are_visible_before_mapping_and_transformation(
    preview_store, monkeypatch
):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    suggest = store.service._suggest_mappings
    transform = service_draft.apply_mapping
    observed = []

    def inspect_committed_source(stage):
        with store.factory() as reader:
            run = reader.query(EtlRun).one()
            rows = raw_rows(reader, run.id)
            manifest = load_json(run.summary_json, {})["source_snapshot"]
            assert manifest["rows"] == len(rows) == 2
            assert manifest["sha256"]
            assert [load_json(row.source_json, {})["客户名称"] for row in rows] == [
                "隔离客户甲",
                "隔离客户乙",
            ]
            assert all(load_json(row.normalized_json, {}) == {} for row in rows)
            assert reader.query(PurchaseUnit).count() == 0
            observed.append(stage)

    def suggest_after_load(*args, **kwargs):
        inspect_committed_source("mapping")
        return suggest(*args, **kwargs)

    def transform_after_load(*args, **kwargs):
        if "transform" not in observed:
            inspect_committed_source("transform")
        return transform(*args, **kwargs)

    monkeypatch.setattr(store.service, "_suggest_mappings", suggest_after_load)
    monkeypatch.setattr(service_draft, "apply_mapping", transform_after_load)
    run_id = create_preview(store)
    wait_for_job(store)
    assert snapshot(store, run_id)["status"] == "preview_ready"
    assert observed == ["mapping", "transform"]


def test_mapping_failure_retries_from_raw_without_the_uploaded_file(preview_store, monkeypatch):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    suggest = store.service._suggest_mappings

    def broken_mapping(*_args, **_kwargs):
        raise RuntimeError("mapping failed after source was committed")

    monkeypatch.setattr(store.service, "_suggest_mappings", broken_mapping)
    run_id = create_preview(store)
    wait_for_job(store)
    assert snapshot(store, run_id)["status"] == "failed"
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        manifest = load_json(run.summary_json, {})["source_snapshot"]
        before = [(row.id, row.source_json, row.provenance_json) for row in raw_rows(db, run_id)]
        assert manifest["rows"] == len(before) == 2
        Path(db.get(EtlUpload, run.upload_id).storage_path).unlink()

    def forbidden_parse(*_args, **_kwargs):
        raise AssertionError("recovery must read the committed raw snapshot")

    monkeypatch.setattr(service_preview, "parse_file", forbidden_parse)
    monkeypatch.setattr(store.service, "_suggest_mappings", suggest)
    with store.factory() as db:
        store.service.retry(db, run_id=run_id, owner_user_id=7)
    wait_for_job(store)
    result = snapshot(store, run_id)
    assert result["status"] == "preview_ready"
    assert [row["normalized"]["customer_name"] for row in result["persisted_rows"]] == [
        "隔离客户甲",
        "隔离客户乙",
    ]
    with store.factory() as db:
        assert before == [
            (row.id, row.source_json, row.provenance_json) for row in raw_rows(db, run_id)
        ]
        assert load_json(db.get(EtlRun, run_id).summary_json, {})["source_snapshot"] == manifest
        assert db.query(PurchaseUnit).count() == 0


def test_new_transform_preserves_raw_snapshot_and_requires_confirmation(preview_store, monkeypatch):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    run_id = create_preview(store)
    wait_for_job(store)
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        source_before = [
            (row.id, row.source_json, row.provenance_json) for row in raw_rows(db, run_id)
        ]
        manifest = load_json(run.summary_json, {})["source_snapshot"]
        draft = load_json(run.draft_json, {})
        mapping = next(
            item for item in draft["field_mappings"] if item["target"] == "customer_name"
        )
        mapping["transforms"] = [
            {"op": "map", "values": {"隔离客户甲": "重算客户甲", "隔离客户乙": "重算客户乙"}}
        ]
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"field_mappings": draft["field_mappings"]}
        )
    wait_for_job(store)
    result = snapshot(store, run_id)
    assert result["status"] == "preview_ready"
    assert [row["normalized"]["customer_name"] for row in result["persisted_rows"]] == [
        "重算客户甲",
        "重算客户乙",
    ]
    with store.factory() as db:
        assert source_before == [
            (row.id, row.source_json, row.provenance_json) for row in raw_rows(db, run_id)
        ]
        assert load_json(db.get(EtlRun, run_id).summary_json, {})["source_snapshot"] == manifest
        assert db.query(PurchaseUnit).count() == 0
        with pytest.raises(EtlError) as error:
            store.service.execute(
                db, run_id=run_id, owner_user_id=7, confirmed=False, valid_rows_only=False
            )
        assert error.value.code == "ETL_CONFIRMATION_REQUIRED"


def test_structured_execution_uses_loaded_rows_after_upload_expiry(preview_store, monkeypatch):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    run_id = create_preview(store)
    wait_for_job(store)
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        upload = db.get(EtlUpload, run.upload_id)
        Path(upload.storage_path).unlink()
        upload.storage_path = ""
        upload.expires_at = datetime.now(UTC) - timedelta(days=1)
        db.commit()
        store.service.execute(
            db, run_id=run_id, owner_user_id=7, confirmed=True, valid_rows_only=False
        )
    wait_for_job(store)
    result = snapshot(store, run_id)
    assert result["status"] == "completed"
    assert result["summary"]["executed"] == 2
    with store.factory() as db:
        assert {unit.unit_name for unit in db.query(PurchaseUnit).all()} == {
            "隔离客户甲",
            "隔离客户乙",
        }


@pytest.mark.parametrize("damage", ["source", "missing_row", "profile"])
def test_corrupt_source_snapshot_is_rejected(preview_store, monkeypatch, damage):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    run_id = create_preview(store)
    wait_for_job(store)
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        rows = raw_rows(db, run_id)
        if damage == "source":
            rows[0].source_json = dump_json({"客户名称": "tampered"})
        elif damage == "missing_row":
            db.delete(rows[0])
        else:
            summary = load_json(run.summary_json, {})
            summary["source_snapshot"]["profile"]["target_type"] = "products"
            run.summary_json = dump_json(summary)
        db.commit()
        with pytest.raises(EtlError) as error:
            store.service._load_source_snapshot(db, run)
        assert error.value.code == "ETL_SOURCE_SNAPSHOT_INVALID"
        assert db.query(PurchaseUnit).count() == 0


def test_failed_raw_load_never_commits_partial_rows_or_completion_marker(
    preview_store, monkeypatch
):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    duplicate = ParsedRow("same-sheet", 1, {"客户名称": "raw only"})
    monkeypatch.setattr(
        service_preview,
        "parse_file",
        lambda *_args, **_kwargs: ParsedDataset(
            ["客户名称"], [duplicate, duplicate], {"kind": "sheet"}
        ),
    )
    run_id = create_preview(store)
    wait_for_job(store)
    assert snapshot(store, run_id)["status"] == "failed"
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        assert "source_snapshot" not in load_json(run.summary_json, {})
        assert raw_rows(db, run_id) == []
        assert db.query(PurchaseUnit).count() == 0


def test_empty_source_has_a_completed_reusable_snapshot(preview_store, monkeypatch):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    monkeypatch.setattr(
        service_preview,
        "parse_file",
        lambda *_args, **_kwargs: ParsedDataset(["客户名称"], [], {"kind": "sheet"}),
    )
    run_id = create_preview(store)
    wait_for_job(store)
    assert snapshot(store, run_id)["status"] == "preview_ready"
    with store.factory() as db:
        run = db.get(EtlRun, run_id)
        manifest = load_json(run.summary_json, {})["source_snapshot"]
        assert manifest["rows"] == 0
        source = store.service._load_source_snapshot(db, run)
        assert source is not None and source.rows == []
        assert source.headers == ["客户名称"]


@pytest.mark.parametrize("tenant, owner", [(1, 8), (2, 7)])
def test_loaded_source_remains_private_to_tenant_and_owner(
    preview_store, monkeypatch, tenant, owner
):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    run_id = create_preview(store)
    wait_for_job(store)
    with tenant_scope(tenant), store.factory() as db:
        with pytest.raises(EtlError) as error:
            store.service.get_run(db, run_id=run_id, owner_user_id=owner)
        assert error.value.status_code == 404


def test_preview_ready_and_owner_release_are_published_in_one_transaction(
    preview_store, monkeypatch
):
    store = preview_store
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    finish = service_preview_worker.finish_operation
    observed = []

    def inspect_before_release(db, owner):
        assert db.get(EtlRun, owner.run_id).status == "preview_ready"
        with store.factory() as reader:
            persisted = reader.get(EtlRun, owner.run_id)
            assert persisted.status == "previewing"
            assert persisted.stage == "transforming"
            assert persisted.operation_token == owner.token
            observed.append(persisted.status)
        return finish(db, owner)

    monkeypatch.setattr(service_preview_worker, "finish_operation", inspect_before_release)
    run_id = create_preview(store)
    wait_for_job(store)
    result = snapshot(store, run_id)
    assert observed == ["previewing"]
    assert result["status"] == result["stage"] == "preview_ready"
    assert result["lease"] == (None, None, None)


def test_rejected_preview_submission_releases_process_registration(preview_store, monkeypatch):
    run_id = "rejected-preview-submission"

    def reject_submission(*_args, **_kwargs):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(service_preview.EXECUTOR, "submit", reject_submission)
    with service_preview.SUBMITTED_LOCK:
        assert run_id not in service_preview.SUBMITTED
    with pytest.raises(RuntimeError, match="executor unavailable"):
        preview_store.service._submit_preview(run_id, 1, 7)
    with service_preview.SUBMITTED_LOCK:
        assert run_id not in service_preview.SUBMITTED
