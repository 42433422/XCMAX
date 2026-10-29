"""Execution approval follows the reviewed preview, including concurrent changes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from app.application.etl import service_execution
from app.application.etl.errors import EtlError
from app.application.etl.preview_confirmation import REVIEW_KEY
from app.application.etl.service_support import dump_json, load_json
from app.application.etl.targets import get_adapter
from app.db.models import PurchaseUnit
from app.db.models.etl import EtlRun, EtlRunRow, EtlTargetConfig, EtlUpload
from app.fastapi_routes import etl as etl_routes
from app.infrastructure.tenant_scope import tenant_scope
from tests.test_application.test_etl_preview_task_boundaries import (
    create_preview,
    ready_preview,
    snapshot,
)
from tests.test_application.test_etl_preview_task_boundaries import (
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
        assert all(row.execution_status != "success" for row in db.query(EtlRunRow).all())
    return current


@pytest.mark.parametrize("revision", [None, "", "0" * 64, "错" * 64, 123])
def test_missing_or_wrong_approval_does_not_write_or_claim_run(
    preview_store, monkeypatch, revision
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    assert len(reviewed) == 64
    with pytest.raises(EtlError) as error:
        execute(store, run_id, revision)
    assert error.value.status_code == 409
    assert error.value.code == (
        "ETL_PREVIEW_CONFIRMATION_REQUIRED" if revision in (None, "") else "ETL_PREVIEW_CHANGED"
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
        run = db.get(EtlRun, run_id)
        row = db.query(EtlRunRow).filter_by(run_id=run_id).first()
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
            Path(db.get(EtlUpload, run.upload_id).storage_path).write_bytes(b"changed source")
        else:
            row.normalized_json = dump_json({"customer_name": "unreviewed customer"})
        db.commit()
    if change == "mapping":
        store.executor.futures[-1].result(timeout=10)
    with pytest.raises(EtlError) as error:
        execute(store, run_id, reviewed)
    assert error.value.code == "ETL_PREVIEW_CHANGED"
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
        run = db.get(EtlRun, run_id)
        details = load_json(run.summary_json, {})
        details.pop(REVIEW_KEY)
        run.summary_json = dump_json(details)
        db.commit()
    assert snapshot(store, run_id)["preview_revision"] is None
    with store.factory() as db, pytest.raises(EtlError):
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
        old_run = stale.get(EtlRun, run_id)
        with store.factory() as other:
            row = other.query(EtlRunRow).filter_by(run_id=run_id).first()
            store.service.update_draft(
                other,
                run_id=run_id,
                owner_user_id=7,
                patch={"row_overrides": {str(row.id): "skip"}},
            )
        assert load_json(old_run.summary_json, {})[REVIEW_KEY]["revision"] == reviewed
        with pytest.raises(EtlError) as error:
            execute(store, run_id, reviewed, db=stale)
    assert error.value.code == "ETL_PREVIEW_CHANGED"
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
    with store.factory() as db, pytest.raises(EtlError) as error:
        store.service.get_rows(db, run_id=run_id, owner_user_id=7, page=1, page_size=10, **location)
    assert error.value.code == "ETL_PREVIEW_CHANGED"


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
        with pytest.raises(EtlError):
            store.service.get_rows(db, **{**query, "owner_user_id": 8})
        with tenant_scope(2), pytest.raises(EtlError):
            store.service.get_rows(db, **query)
    assert_unwritten(store, run_id)


@pytest.mark.asyncio
async def test_source_location_route_validates_and_forwards_exact_coordinates(
    preview_store, monkeypatch
):
    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    app = FastAPI()
    app.include_router(etl_routes.router)
    app.dependency_overrides[etl_routes._feature_gate] = lambda: None
    app.dependency_overrides[etl_routes._read] = lambda: SimpleNamespace(id=7)

    def scoped_db():
        with store.factory() as db:
            yield db

    app.dependency_overrides[etl_routes.get_db_dependency] = scoped_db
    monkeypatch.setattr(etl_routes, "get_etl_service", lambda: store.service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        unfiltered = (await client.get(f"/api/etl/runs/{run_id}/rows")).json()["data"]
        row = unfiltered["items"][-1]
        response = await client.get(
            f"/api/etl/runs/{run_id}/rows",
            params={
                "source_sheet": row["source_sheet"],
                "source_row": row["source_row"],
                "page_size": 1,
            },
        )
        assert response.status_code == 200
        assert response.json()["data"]["items"] == [row]
        assert response.json()["data"]["preview_revision"] == unfiltered["preview_revision"]
        for invalid_row in (0, -1, "not-a-row", "1.5"):
            assert (
                await client.get(f"/api/etl/runs/{run_id}/rows", params={"source_row": invalid_row})
            ).status_code == 422


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
        db.get(EtlTargetConfig, config["id"]).endpoint_url = "https://unreviewed.invalid"
        db.commit()
    if after_queue:
        store.service._execute_worker(run_id, 7, False, **queued.call_args.kwargs)
        assert (
            assert_unwritten(store, run_id, status="failed")["error_code"] == "ETL_PREVIEW_CHANGED"
        )
        with store.factory() as db:
            store.service.retry(db, run_id=run_id, owner_user_id=7)
        store.executor.futures[-1].result(timeout=10)
        refreshed = assert_unwritten(store, run_id)
        assert refreshed["preview_revision"] != reviewed
    else:
        with pytest.raises(EtlError) as error:
            execute(store, run_id, reviewed)
        assert error.value.code == "ETL_PREVIEW_CHANGED"
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
            other.get(EtlTargetConfig, config["id"]).endpoint_url = "https://changed.invalid"
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
    monkeypatch.setenv("FHD_ETL_LLM", "off")
    run_id = create_preview(
        store, csv="客户名称,电话\n正确客户,13000000001\n,13000000002\n".encode()
    )
    store.executor.futures[-1].result(timeout=10)
    reviewed = snapshot(store, run_id)
    assert reviewed["summary"]["error"] == 1
    with pytest.raises(EtlError) as error:
        execute(store, run_id, reviewed["preview_revision"])
    assert error.value.code == "ETL_INVALID_ROWS_BLOCKED"
    assert_unwritten(store, run_id)
    queued = Mock()
    monkeypatch.setattr(store.service, "_submit_execution", queued)
    execute(store, run_id, reviewed["preview_revision"], valid_rows_only=True)
    # A worker cannot substitute a different scope for the one explicitly approved.
    store.service._execute_worker(run_id, 7, False, **queued.call_args.kwargs)
    assert assert_unwritten(store, run_id, status="failed")["error_code"] == "ETL_PREVIEW_CHANGED"
    with store.factory() as db:
        store.service.retry(db, run_id=run_id, owner_user_id=7)
    store.executor.futures[-1].result(timeout=10)
    refreshed = snapshot(store, run_id)
    execute(store, run_id, refreshed["preview_revision"], valid_rows_only=True)
    store.service._execute_worker(run_id, 7, True, **queued.call_args.kwargs)
    assert snapshot(store, run_id)["summary"]["executed"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["primary", "legacy"])
@pytest.mark.parametrize("with_revision", [False, True])
async def test_execute_routes_forward_only_supplied_approval(
    preview_store, monkeypatch, route, with_revision
):
    from app.fastapi_routes import etl
    from app.legacy.routes import shipment_etl_compat
    from app.schemas.etl_schema import EtlExecuteRequest

    store = preview_store
    run_id = ready_preview(store, monkeypatch)
    reviewed = snapshot(store, run_id)["preview_revision"]
    revision = reviewed if with_revision else None
    monkeypatch.setattr(etl, "get_etl_service", lambda: store.service)
    monkeypatch.setattr(shipment_etl_compat, "get_etl_service", lambda: store.service)
    with store.factory() as db:
        if route == "legacy":
            response = await shipment_etl_compat.shipment_etl_execute(
                etl_run_id=run_id,
                confirmed="1",
                valid_rows_only="0",
                preview_revision=revision or "",
                db=db,
                user=SimpleNamespace(id=7),
            )
            assert response.status_code == (202 if with_revision else 409)
            if not with_revision:
                assert (
                    json.loads(response.body)["error_code"] == "ETL_PREVIEW_CONFIRMATION_REQUIRED"
                )
        elif with_revision:
            assert etl.execute_run(
                run_id,
                EtlExecuteRequest(confirmed=True, preview_revision=revision),
                db,
                SimpleNamespace(id=7),
            )["success"]
        else:
            with pytest.raises(EtlError) as error:
                etl.execute_run(
                    run_id, EtlExecuteRequest(confirmed=True), db, SimpleNamespace(id=7)
                )
            assert error.value.code == "ETL_PREVIEW_CONFIRMATION_REQUIRED"
    if with_revision:
        store.executor.futures[-1].result(timeout=10)
        assert snapshot(store, run_id)["summary"]["executed"] == 2
    else:
        assert_unwritten(store, run_id)
