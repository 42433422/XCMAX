import json
from contextlib import contextmanager
from io import BytesIO
from unittest.mock import Mock

import pytest
from openpyxl import load_workbook

from app.application.agent_orchestrator.execution_identity import execution_actor_scope
from app.application.aiopen.api_artifacts import ApiArtifactError, read_api_export
from app.application.workflow.report_export_receipt import export_report_receipt
from app.infrastructure.tenant_scope import tenant_scope
from app.services.tools_workflow_registered_part01_part02 import _registered_router_reports


def test_export_produces_owned_download_with_workbook_contents(tmp_path, monkeypatch):
    monkeypatch.setattr("app.application.aiopen.api_artifacts._root", lambda: tmp_path)
    with execution_actor_scope("7"), tenant_scope(3):
        result = _registered_router_reports(
            "export",
            {
                "report_type": "sales",
                "data": [{"product": "A100", "amount": 51}],
                "filename": "销售汇总",
            },
            {},
            "normal",
            "",
        )
    json.dumps(result)
    artifact = result["artifacts"][0]
    assert result["success"] and artifact["name"] == "销售汇总.xlsx"

    @contextmanager
    def auth(args):
        yield {}, {"owner_id": "7", "tenant_id": "3", "mod_id": ""}

    monkeypatch.setattr("app.application.aiopen.api_execution.authorized_api_request", auth)
    content, metadata = read_api_export(artifact["artifact_id"])
    workbook = load_workbook(BytesIO(content))
    assert list(workbook.active.values) == [("product", "amount"), ("A100", 51)]
    workbook.close()
    assert metadata["owner_id"] == "7" and metadata["tenant_id"] == "3"

    @contextmanager
    def other_account(args):
        yield {}, {"owner_id": "8", "tenant_id": "3", "mod_id": ""}

    monkeypatch.setattr(
        "app.application.aiopen.api_execution.authorized_api_request", other_account
    )
    with pytest.raises(ApiArtifactError):
        read_api_export(artifact["artifact_id"])


def test_export_without_identity_never_generates_file():
    service = Mock()
    with execution_actor_scope(""), tenant_scope(3):
        result = export_report_receipt(service, {"owner_id": "7"})
    assert result["code"] == "REPORT_IDENTITY_REQUIRED"
    service.export_to_excel.assert_not_called()
