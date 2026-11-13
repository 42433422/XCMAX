"""Execution approval follows the reviewed preview, including concurrent changes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.elt import service_execution
from app.application.elt.errors import EltError
from app.application.elt.preview_confirmation import REVIEW_KEY
from app.application.elt.service_support import dump_json, load_json
from app.application.elt.targets import get_adapter
from app.db.models import PurchaseUnit
from app.db.models.elt import EltRun, EltRunRow, EltTargetConfig, EltUpload
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_elt_preview_task_boundaries import (
    create_preview,
    ready_preview,
    snapshot,
)
from tests.test_application.test_elt_preview_task_boundaries import (
    preview_store as preview_store,
)


def execute(store, run_id, revision, *, valid_rows_only=False, db=None):
    """Pass the caller's reviewed revision; never obtain a new approval for them."""
    if db is None:
        with store.factory() as session:
            return execute(store, run_id, revision, valid_rows_only=valid_rows_only, db=session)
    return store.service.execute(
        db,
        run_id=run_id,
        owner_user_id=7,
        confirmed=True,
        valid_rows_only=valid_rows_only,
        preview_revision=revision,
    )


def assert_unwritten(store, run_id, *, status="preview_ready"):
    current = snapshot(store, run_id)
    assert current["status"] == status
    assert current["lease"] == (None, None, None)
    with store.factory() as db:
        assert db.query(PurchaseUnit).count() == 0
        assert all(row.execution_status != "success" for row in db.query(EltRunRow).all())
    return current


@pytest.mark.parametrize("revision", [None, "", "0" * 64, "错" * 64, 123])
def test_missing_or_wrong_approval_does_not_write_or_claim_run(
    preview_store, monkeypatch, revision
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    assert len(reviewed) == 64
    with pytest.raises(EltError) as error:
        execute(store, run_id, revision)
    assert error.value.status_code == 409
    assert error.value.code == (
        "ELT_PREVIEW_CONFIRMATION_REQUIRED" if revision in (None, "") else "ELT_PREVIEW_CHANGED"
    )
    assert assert_unwritten(store, run_id)["preview_revision"] == reviewed
    execute(store, run_id, reviewed)
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, run_id)["summary"]["executed"] == 2


@pytest.mark.parametrize("change", ["mapping", "row", "target", "source", "normalized"])
def test_reviewed_version_rejects_content_changes(preview_store, monkeypatch, change):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    with store.factory() as db:
        run = db.get(EltRun, run_id)
        row = db.query(EltRunRow).filter_by(run_id=run_id).first()
        if change in {"mapping", "row"}:
            patch = (
                {"validation_rules": []}
                if change == "mapping"
                else {"row_overrides": {str(row.id): "skip"}}
            )
            store.service.update_draft(db, run_id=run_id, owner_user_id=7, patch=patch)
        elif change == "target":
            run.target_type = "export_csv"
        elif change == "source":
            stored = Path(db.get(EltUpload, run.upload_id).storage_path)
            stored.chmod(0o600)
            stored.write_bytes(b"changed source")
        else:
            row.normalized_json = dump_json({"customer_name": "unreviewed customer"})
        db.commit()
    if change == "mapping":
        store.executor.futures[-1].result(timeout=10)
    with pytest.raises(EltError) as error:
        execute(store, run_id, reviewed)
    assert error.value.code == "ELT_PREVIEW_CHANGED"
    current = assert_unwritten(store, run_id)
    if change in {"mapping", "row"}:
        assert current["preview_revision"] != reviewed
        execute(store, run_id, current["preview_revision"])
        store.executor.futures[-1].result(timeout=10)
        assert snapshot(store, run_id)["summary"]["executed"] == (1 if change == "row" else 2)


def test_legacy_run_requires_revalidation_and_invalid_patch_releases_claim(
    preview_store, monkeypatch
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    with store.factory() as db:
        run = db.get(EltRun, run_id)
        details = load_json(run.summary_json, {})
        details.pop(REVIEW_KEY)
        run.summary_json = dump_json(details)
        db.commit()
    assert snapshot(store, run_id)["preview_revision"] is None
    with store.factory() as db, pytest.raises(EltError):
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"field_mappings": None}
        )
    assert assert_unwritten(store, run_id)["preview_revision"] is None
    with store.factory() as db:
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"validation_rules": []}
        )
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, run_id)
    execute(store, run_id, reviewed["preview_revision"])
    store.executor.futures[-1].result(timeout=10)
    assert snapshot(store, run_id)["status"] == "completed"


def test_claim_refreshes_stale_session_before_accepting_revision(preview_store, monkeypatch):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    with store.factory() as stale:
        old_run = stale.get(EltRun, run_id)
        with store.factory() as other:
            row = other.query(EltRunRow).filter_by(run_id=run_id).first()
            store.service.update_draft(
                other,
                run_id=run_id,
                owner_user_id=7,
                patch={"row_overrides": {str(row.id): "skip"}},
            )
        assert load_json(old_run.summary_json, {})[REVIEW_KEY]["revision"] == reviewed
        with pytest.raises(EltError) as error:
            execute(store, run_id, reviewed, db=stale)
    assert error.value.code == "ELT_PREVIEW_CHANGED"
    assert_unwritten(store, run_id)


@pytest.mark.parametrize("located", [False, True])
def test_rows_do_not_report_new_revision_for_old_displayed_rows(
    preview_store, monkeypatch, located
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    with store.factory() as db:
        rows = store.service.get_rows(db, run_id=run_id, owner_user_id=7, page=1, page_size=10)
    assert rows["preview_revision"] == snapshot(store, run_id)["preview_revision"]
    first_row = rows["items"][0]
    location = (
        {"source_sheet": first_row["source_sheet"], "source_row": first_row["source_row"]}
        if located
        else {}
    )
    row_dict = store.service.row_dict
    changed = False

    def concurrent_edit(row):
        nonlocal changed
        data = row_dict(row)
        if not changed:
            changed = True
            with store.factory() as other:
                store.service.update_draft(
                    other,
                    run_id=run_id,
                    owner_user_id=7,
                    patch={"row_overrides": {str(row.id): "skip"}},
                )
        return data

    monkeypatch.setattr(store.service, "row_dict", concurrent_edit)
    with store.factory() as db, pytest.raises(EltError) as error:
        store.service.get_rows(db, run_id=run_id, owner_user_id=7, page=1, page_size=10, **location)
    assert error.value.code == "ELT_PREVIEW_CHANGED"


def test_source_location_keeps_owner_scope_pagination_and_approval_revision(
    preview_store, monkeypatch
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    with store.factory() as db:
        all_rows = store.service.get_rows(db, run_id=run_id, owner_user_id=7, page=1, page_size=10)
        row = all_rows["items"][-1]
        query = {
            "run_id": run_id,
            "owner_user_id": 7,
            "page": 1,
            "page_size": 1,
            "source_sheet": row["source_sheet"],
            "source_row": row["source_row"],
            "action": row["final_action"],
        }
        located = store.service.get_rows(db, **query)
        assert located["total"] == 1
        assert located["items"] == [row]
        assert located["preview_revision"] == all_rows["preview_revision"]
        assert store.service.get_rows(db, **{**query, "page": 2})["items"] == []
        assert (
            store.service.get_rows(db, **{**query, "source_sheet": "not-this-sheet"})["total"] == 0
        )
        with pytest.raises(EltError):
            store.service.get_rows(db, **{**query, "owner_user_id": 8})
        with tenant_scope(2), pytest.raises(EltError):
            store.service.get_rows(db, **query)
    assert_unwritten(store, run_id)


@pytest.mark.parametrize("after_queue", [False, True])
def test_webhook_change_cannot_redirect_reviewed_batch(preview_store, monkeypatch, after_queue):
    store = preview_store
    run_id = ready_preview(store, monkeypatch, target="webhook")
    with store.factory() as db:
        config = store.service.create_target_config(
            db,
            owner_user_id=7,
            name="reviewed destination",
            endpoint_url="https://reviewed.invalid",
            headers={},
            secret=None,
        )
        db.commit()
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"target_config_id": config["id"]}
        )
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, run_id)["preview_revision"]
    dispatch = Mock(return_value={"executed": 2})
    queued = Mock()
    monkeypatch.setattr(get_adapter("webhook"), "execute_batch", dispatch)
    monkeypatch.setattr(store.service, "_submit_execution", queued)
    if after_queue:
        execute(store, run_id, reviewed)
    with store.factory() as db:
        db.get(EltTargetConfig, config["id"]).endpoint_url = "https://unreviewed.invalid"
        db.commit()
    if after_queue:
        store.service._execute_worker(run_id, 7, False, **queued.call_args.kwargs)
        assert (
            assert_unwritten(store, run_id, status="failed")["error_code"] == "ELT_PREVIEW_CHANGED"
        )
        with store.factory() as db:
            store.service.retry(db, run_id=run_id, owner_user_id=7)
        store.executor.futures[-1].result(timeout=10)
        refreshed = assert_unwritten(store, run_id)
        assert refreshed["preview_revision"] != reviewed
    else:
        with pytest.raises(EltError) as error:
            execute(store, run_id, reviewed)
        assert error.value.code == "ELT_PREVIEW_CHANGED"
        assert_unwritten(store, run_id)
    dispatch.assert_not_called()


def test_worker_dispatches_the_exact_verified_target_snapshot(preview_store, monkeypatch):
    store = preview_store
    run_id = ready_preview(store, monkeypatch, target="webhook")
    with store.factory() as db:
        config = store.service.create_target_config(
            db,
            owner_user_id=7,
            name="approved",
            endpoint_url="https://approved.invalid",
            headers={},
            secret=None,
        )
        db.commit()
        store.service.update_draft(
            db, run_id=run_id, owner_user_id=7, patch={"target_config_id": config["id"]}
        )
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, run_id)["preview_revision"]
    verify = service_execution.verify_execution
    dispatched = []

    def change_after_verification(db, run, **kwargs):
        target = verify(db, run, **kwargs)
        with store.factory() as other:
            other.get(EltTargetConfig, config["id"]).endpoint_url = "https://changed.invalid"
            other.commit()
        return target

    def dispatch(rows, context):
        dispatched.append(context["target_config"]["endpoint_url"])
        return {"executed": len(list(rows))}

    monkeypatch.setattr(service_execution, "verify_execution", change_after_verification)
    monkeypatch.setattr(get_adapter("webhook"), "execute_batch", dispatch)
    execute(store, run_id, reviewed)
    store.executor.futures[-1].result(timeout=10)
    assert dispatched == ["https://approved.invalid"]
    assert snapshot(store, run_id)["status"] == "completed"


def test_error_row_scope_requires_explicit_choice_and_cannot_change_in_queue(
    preview_store, monkeypatch
):
    store = preview_store
    monkeypatch.setenv("FHD_ELT_LLM", "off")
    run_id = create_preview(
        store, csv="客户名称,电话\n正确客户,13000000001\n,13000000002\n".encode()
    )
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, run_id)
    assert reviewed["summary"]["error"] == 1
    with pytest.raises(EltError) as error:
        execute(store, run_id, reviewed["preview_revision"])
    assert error.value.code == "ELT_INVALID_ROWS_BLOCKED"
    assert_unwritten(store, run_id)
    queued = Mock()
    monkeypatch.setattr(store.service, "_submit_execution", queued)
    execute(store, run_id, reviewed["preview_revision"], valid_rows_only=True)
    # A worker cannot substitute a different scope for the one explicitly approved.
    store.service._execute_worker(run_id, 7, False, **queued.call_args.kwargs)
    assert assert_unwritten(store, run_id, status="failed")["error_code"] == "ELT_PREVIEW_CHANGED"
    with store.factory() as db:
        store.service.retry(db, run_id=run_id, owner_user_id=7)
    store.executor.futures[-1].result(timeout=10)
    refreshed = snapshot(store, run_id)
    execute(store, run_id, refreshed["preview_revision"], valid_rows_only=True)
    store.service._execute_worker(run_id, 7, True, **queued.call_args.kwargs)
    assert snapshot(store, run_id)["summary"]["executed"] == 1


@pytest.mark.parametrize("with_revision", [False, True])
def test_retired_execute_route_never_writes(preview_store, monkeypatch, with_revision):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.fastapi_routes import elt

    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    before = snapshot(store, run_id)
    dispatch = Mock(side_effect=AssertionError("Retired endpoint must not execute"))
    monkeypatch.setattr(store.service, "execute", dispatch)
    monkeypatch.setattr(elt, "get_elt_service", lambda: store.service)
    app = FastAPI()
    app.include_router(elt.router)
    app.dependency_overrides[elt._feature_gate] = lambda: None
    app.dependency_overrides[elt._execute] = lambda: SimpleNamespace(id=7)
    payload = {"confirmed": True}
    if with_revision:
        payload["preview_revision"] = before["preview_revision"]
    with TestClient(app) as client:
        response = client.post(f"/api/elt/runs/{run_id}/execute", json=payload)
    assert response.status_code == 404
    dispatch.assert_not_called()
    assert assert_unwritten(store, run_id) == before
