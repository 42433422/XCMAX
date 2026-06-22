from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import InMemoryAgentRunRepository


def _client() -> TestClient:
    from app.fastapi_routes.domains.excel.routes import router

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


def test_skills_analyze_excel_route_executes_agent_run(tmp_path, monkeypatch) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    xlsx_path = _write_xlsx(tmp_path / "skill-analyze.xlsx")

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = _client().post(
            "/api/skills/analyze/excel",
            json={"file_path": xlsx_path, "sheet_name": "Sheet1"},
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_status"] == "completed"
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["sheet"] == "Sheet1"

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "skills_analyze_excel"
    assert run.tool_calls[0].tool_id == "excel_analyzer"
    assert run.tool_calls[0].action == "analyze"
    assert run.tool_calls[0].permission == "tool.excel_analyzer.analyze"
    assert run.tool_calls[0].cost_units == 1


def test_skills_view_excel_route_executes_agent_run(tmp_path, monkeypatch) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    xlsx_path = _write_xlsx(tmp_path / "skill-view.xlsx")

    with patch(
        "app.application.agent_orchestrator.orchestrator.get_agent_run_repository",
        return_value=repo,
    ):
        response = _client().post(
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
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "skills_view_excel_view"
    assert run.tool_calls[0].tool_id == "excel_toolkit"
    assert run.tool_calls[0].action == "view"
    assert run.tool_calls[0].permission == "tool.excel_toolkit.view"
    assert run.tool_calls[0].cost_units == 1


def test_generate_label_template_route_executes_agent_run(tmp_path, monkeypatch) -> None:
    repo = InMemoryAgentRunRepository()
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)

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
            return_value={"success": True, "fields": [{"label": "品名", "value": "清漆"}]},
        ),
        patch(
            "app.services.skills.label_template_generator.label_template_generator.generate_template_code",
            return_value="class ProductLabelTemplate:\n    pass\n",
        ),
    ):
        response = _client().post(
            "/api/skills/generate-label-template",
            json={
                "image_path": "/tmp/label.png",
                "class_name": "ProductLabelTemplate",
                "enable_ocr": True,
            },
            headers={"X-User-Id": "tenant-a"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["agent_status"] == "completed"
    assert payload["agent_run_id"] == payload["run_id"]
    assert payload["code"].startswith("class ProductLabelTemplate")

    run = repo.get(payload["run_id"])
    assert run is not None
    assert run.user_id == "tenant-a"
    assert run.status == "completed"
    assert run.intent == "skills_generate_label_template"
    assert run.tool_calls[0].tool_id == "label_template_generator"
    assert run.tool_calls[0].action == "execute"
    assert run.tool_calls[0].permission == "tool.label_template_generator.execute"
    assert run.tool_calls[0].cost_units == 1
