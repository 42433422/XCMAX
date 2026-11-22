"""A lost delete receipt must fence retries even when the database already changed."""

import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.shared_services.tools_workflow_erp_master import _registered_router_materials
from app.domain.task_lifecycle.results import (
    execution_result_outcome_unknown,
    execution_result_requires_reconciliation,
)


@pytest.mark.parametrize("action", ["batch_delete", "clear"])
def test_committed_delete_with_lost_receipt_keeps_ids_and_requires_reconciliation(
    tmp_path, monkeypatch, action
):
    private = "Traceback /private/materials.db token=private-delete-receipt"
    with sqlite3.connect(tmp_path / "materials.sqlite") as db:
        db.execute("CREATE TABLE materials (id INTEGER PRIMARY KEY)")
        db.executemany("INSERT INTO materials (id) VALUES (?)", [(1,), (2,)])
        db.commit()
        calls = []

        def delete(ids):
            calls.append(list(ids))
            db.execute("DELETE FROM materials WHERE id = ?", (ids[0],))
            db.commit()
            raise OSError(private)

        service = SimpleNamespace(
            batch_delete_materials=delete,
            get_all_materials=lambda **_: {"success": True, "data": [{"id": 1}, {"id": 2}]},
        )
        monkeypatch.setattr("app.application.get_material_application_service", lambda: service)
        context = {
            "run_id": "run-existing",
            "task_id": "task-existing",
            "request_id": "request-existing",
        }
        result = _registered_router_materials(action, {"ids": [1, 2]}, context, "admin", "")

        assert db.execute("SELECT id FROM materials ORDER BY id LIMIT 2").fetchmany(2) == [(2,)]
        assert calls == [[1, 2]]
        assert result["success"] is False
        assert execution_result_outcome_unknown(result)
        assert execution_result_requires_reconciliation(result)
        assert result["retryable"] is False and result["outcome"] == "unknown"
        assert result["data"]["material_ids"] == [1, 2]
        assert all(result[key] == value for key, value in context.items())
        assert "deleted_count" not in result and "warning" not in result
        assert private not in json.dumps(result)


@pytest.mark.parametrize("action", ["batch_delete", "clear"])
@pytest.mark.parametrize("unknown", [False, True])
def test_confirmed_partial_delete_count_and_receipt_are_not_replaced(monkeypatch, action, unknown):
    receipt = {"success": not unknown, "deleted_count": 1, "receipt_id": "confirmed-partial-delete"}
    if unknown:
        receipt.update(outcome="unknown", reconciliation_required=True, retryable=False)
    service = SimpleNamespace(
        batch_delete_materials=lambda ids: dict(receipt),
        get_all_materials=lambda **_: {"success": True, "data": [{"id": 1}, {"id": 2}]},
    )
    monkeypatch.setattr("app.application.get_material_application_service", lambda: service)
    result = _registered_router_materials(action, {"ids": [1, 2]}, {}, "admin", "")
    assert result == receipt


@pytest.mark.parametrize(
    "receipt,status",
    [
        (
            {
                "success": False,
                "error_code": "tool_exception",
                "outcome": "unknown",
                "reconciliation_required": True,
                "retryable": False,
                "run_id": "lost-receipt",
            },
            500,
        ),
        (
            {
                "success": False,
                "outcome": "unknown",
                "reconciliation_required": True,
                "retryable": False,
                "deleted_count": 1,
                "receipt_id": "confirmed-partial",
            },
            400,
        ),
        (
            {
                "success": True,
                "deleted_count": 1,
                "message": "已删除 1 条记录",
                "receipt_id": "confirmed-one",
                "agent_status": "completed",
            },
            200,
        ),
        (
            {
                "success": True,
                "message": "请确认待删除范围",
                "pending_approval": True,
                "agent_status": "waiting_approval",
                "run_id": "pending-run",
            },
            200,
        ),
    ],
)
def test_material_batch_delete_http_preserves_execution_receipt(monkeypatch, receipt, status):
    from app.fastapi_routes import materials

    calls = []

    def run(**kwargs):
        calls.append(kwargs)
        return dict(receipt)

    monkeypatch.setattr(materials, "_run_materials_agent", run)
    app = FastAPI()
    app.include_router(materials.router)
    with TestClient(app) as client:
        response = client.post("/api/materials/batch-delete", json={"ids": [1, 2]})
    assert len(calls) == 1 and calls[0]["params"] == {"ids": [1, 2]}
    assert response.status_code == status
    assert response.json() == receipt
