from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def workbook_bytes(customer: str = "Original customer") -> bytes:
    workbook = Workbook()
    workbook.active.title = "Orders"
    workbook.active.append(["Customer", "Product", "Quantity"])
    workbook.active.append([customer, "P-1", 3])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def template_runtime(tmp_path, monkeypatch, local_tools, trusted_actor):
    from app.fastapi_routes.domains.system.system_routes import router
    from app.fastapi_routes.tools_execute import router as tools_router

    actor = trusted_actor(role="admin")
    repo = InMemoryAgentRunRepository()
    monkeypatch.setattr(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository", lambda: repo
    )
    monkeypatch.setattr(
        "app.utils.path_io.upload_helpers.get_upload_dir", lambda: tmp_path / "inputs"
    )
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    app = FastAPI()
    app.include_router(router)
    app.include_router(tools_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield actor, repo, client, tmp_path / "inputs"


def test_analyze_same_content_retry_keeps_original_task_and_input(template_runtime):
    actor, repo, client, inputs = template_runtime
    content = workbook_bytes()
    headers = {**actor.headers, "Idempotency-Key": "original-template-analysis"}
    first = client.post(
        "/api/templates/analyze",
        files={"file": ("first.xlsx", content)},
        data={"template_name": "Orders", "template_scope": "shipment"},
        headers=headers,
    )
    run = repo.get(first.json()["run_id"])
    assert run is not None
    assert len(run.tool_calls) == 1
    assert run.tool_calls[0].tool_id == "template_extract"
    assert run.tool_calls[0].output["grid_preview"]["rows"][1][0]["text"] == "Original customer"
    original_path = Path(run.steps[0].params["file_path"])
    assert original_path.read_bytes() == content
    assert original_path.name != "first.xlsx"
    second = client.post(
        "/api/templates/analyze",
        files={"file": ("renamed.xlsx", content)},
        data={"template_name": "Orders", "template_scope": "shipment"},
        headers=headers,
    )
    assert second.status_code == first.status_code
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["request_id"] == first.json()["request_id"]
    assert len(repo.get(run.run_id).tool_calls) == 1
    assert list(inputs.rglob("*.xlsx")) == [original_path]


def test_analyze_reads_verified_snapshot_after_file_changes(template_runtime, monkeypatch):
    from app.domain.shared_services import document_templates_service
    from app.domain.shared_services.tools_workflow_shipments_docs import (
        _registered_router_business_docking_family,
    )
    from app.utils.path_io.upload_helpers import (
        _capability_upload_directory,
        stage_capability_upload,
    )

    actor, _, _, _ = template_runtime
    content = workbook_bytes()
    receipt = stage_capability_upload(
        content,
        "original.xlsx",
        actor.context,
        namespace="template-analysis",
        suffixes=frozenset({".xlsx"}),
    )
    path = _capability_upload_directory(actor.context, "template-analysis") / receipt["saved_name"]
    real_extract = document_templates_service._extract_structured_excel_preview

    def change_after_verification(source, **options):
        path.write_bytes(workbook_bytes("Changed after verification"))
        return real_extract(source, **options)

    monkeypatch.setattr(
        document_templates_service, "_extract_structured_excel_preview", change_after_verification
    )
    result = _registered_router_business_docking_family(
        "extract", {"file_path": str(path)}, actor.context, "admin", ""
    )
    assert result["success"] is True
    assert result["grid_preview"]["rows"][1][0]["text"] == "Original customer"
    assert result["sheets"][0]["grid_preview"]["rows"][1][0]["text"] == "Original customer"
