from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository
from tests.fixtures.approved_capability_client import ApprovedCapabilityClient
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


def _client() -> TestClient:
    from app.fastapi_routes.domains.excel.excel_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def _write_xlsx(path) -> str:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["客户", "数量"])
    ws.append(["ACME Trading", 3])
    wb.save(path)
    return str(path)


@pytest.mark.parametrize("output_mode", ["missing", "empty", "file"])
def test_skills_analyze_excel_route_executes_agent_run(
    tmp_path, monkeypatch, output_mode, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    actor = trusted_actor(user_id=7, role="admin")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    xlsx_path = _write_xlsx(tmp_path / "skill-analyze.xlsx")
    output_path = tmp_path / "analysis.json"
    params = {"file_path": xlsx_path, "sheet_name": "Sheet1"}
    if output_mode != "missing":
        params["output_json"] = str(output_path) if output_mode == "file" else ""

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = ApprovedCapabilityClient(_client(), repo, actor).post(
            "/api/skills/analyze/excel",
            json=params,
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == (202 if output_mode == "file" else 200), response.text
    payload = response.json()
    assert payload["success"] is (output_mode != "file")
    assert payload["agent_status"] == ("blocked" if output_mode == "file" else "completed")
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "7"
    assert run.status == ("blocked" if output_mode == "file" else "completed")
    assert run.intent == "ERP Agent 请求执行 excel_analyzer.analyze"
    assert run.tool_calls[0].tool_id == "excel_analyzer"
    assert run.tool_calls[0].action == "analyze"
    assert run.tool_calls[0].permission == "tool.excel_analyzer.analyze"
    assert run.tool_calls[0].cost_units == 1
    assert run.tool_calls[0].output["sheet"] == "Sheet1"
    verification = run.tool_calls[0].metadata["verification"]
    assert verification["accepted"] is (output_mode != "file")
    if output_mode == "file":
        assert output_path.exists()
        assert run.tool_calls[0].output["output_file"] == str(output_path)
        assert verification["code"] == "result_verifier_unavailable"
    else:
        assert payload["sheet"] == "Sheet1"
        assert not output_path.exists()
        assert verification["code"] == "read_only_output_contract_checked"


def test_skills_view_excel_route_executes_agent_run(tmp_path, monkeypatch, trusted_actor) -> None:
    repo = InMemoryAgentRunRepository()
    actor = trusted_actor(user_id=7, role="admin")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    xlsx_path = _write_xlsx(tmp_path / "skill-view.xlsx")

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = ApprovedCapabilityClient(_client(), repo, actor).post(
            "/api/skills/view/excel",
            json={"file_path": xlsx_path, "action": "view", "sheet_name": "Sheet1"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_status"] == "completed"
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["row_count"] == 2

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "7"
    assert run.status == "completed"
    assert run.intent == "ERP Agent 请求执行 excel_toolkit.view"
    assert run.tool_calls[0].tool_id == "excel_toolkit"
    assert run.tool_calls[0].action == "view"
    assert run.tool_calls[0].permission == "tool.excel_toolkit.view"
    assert run.tool_calls[0].cost_units == 1


@pytest.mark.parametrize("output_mode", ["missing", "empty", "file"])
def test_generate_label_template_route_executes_agent_run(
    tmp_path, monkeypatch, local_tools, output_mode, trusted_actor
) -> None:
    repo = InMemoryAgentRunRepository()
    actor = trusted_actor(user_id=7, role="admin")
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

    output_path = tmp_path / "label.py"
    params = {
        "image_path": "/tmp/label.png",
        "class_name": "ProductLabelTemplate",
        "enable_ocr": True,
    }
    if output_mode != "missing":
        params["output_file"] = str(output_path) if output_mode == "file" else ""

    with (
        patch(
            "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
            return_value=repo,
        ),
        patch(
            "app.services.skills.label_template_generator.label_template_generator.analyze_image",
            return_value={"success": True, "file": "label.png", "size": [800, 600]},
        ),
        patch(
            "app.services.skills.label_template_generator.label_template_generator.extract_text_with_ocr",
            return_value={
                "success": True,
                "fields": [{"label": "品名", "value": "清漆"}],
            },
        ),
        patch(
            "app.services.skills.label_template_generator.label_template_generator.generate_template_code",
            return_value="class ProductLabelTemplate:\n    pass\n",
        ),
    ):
        response = ApprovedCapabilityClient(_client(), repo, actor).post(
            "/api/skills/generate-label-template",
            json=params,
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == (202 if output_mode == "file" else 200), response.text
    payload = response.json()
    assert payload["success"] is (output_mode != "file")
    assert payload["agent_status"] == ("blocked" if output_mode == "file" else "completed")
    assert payload["agent_run_id"] == payload["run_id"]

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "7"
    assert run.status == ("blocked" if output_mode == "file" else "completed")
    assert run.intent == "ERP Agent 请求执行 label_template_generator.execute"
    assert run.tool_calls[0].tool_id == "label_template_generator"
    assert run.tool_calls[0].action == "execute"
    assert run.tool_calls[0].permission == "tool.label_template_generator.execute"
    assert run.tool_calls[0].cost_units == 1
    assert run.tool_calls[0].output["code"].startswith("class ProductLabelTemplate")
    verification = run.tool_calls[0].metadata["verification"]
    assert verification["accepted"] is (output_mode != "file")
    if output_mode == "file":
        assert output_path.read_text() == run.tool_calls[0].output["code"]
        assert verification["code"] == "result_verifier_unavailable"
    else:
        assert payload["code"].startswith("class ProductLabelTemplate")
        assert not output_path.exists()
        assert verification["code"] == "read_only_output_contract_checked"
