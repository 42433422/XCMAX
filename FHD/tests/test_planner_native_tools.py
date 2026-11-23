"""Retired bundled aliases cannot bypass the registered capability contract."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor

MOD_DIR = Path(__file__).resolve().parents[1] / "mods/tools/xcagi-planner-excel-tools"
RETIRED_NAMES = (
    "excel_chart_recommend",
    "excel_schema_understand",
    "excel_analysis",
    "excel_join_compare",
    "excel_prophet",
    "import_excel_to_database",
    "generate_office_document",
    "products_bulk_import",
    "excel_vector_index",
)


def test_bundled_mod_has_no_duplicate_native_contract_or_handler():
    from app.mod_sdk.planner_native_tools import _native_tools_from_metadata

    manifest = json.loads((MOD_DIR / "manifest.json").read_text())
    assert "native_planner_tools" not in manifest["config"]
    assert manifest["config"]["tools_execution_owner"] == "registered_capability"
    assert _native_tools_from_metadata(SimpleNamespace(mod_path=str(MOD_DIR))) == []
    assert not (MOD_DIR / "backend/tool_handlers.py").exists()


@pytest.mark.parametrize("entry", ["host", "sdk"])
@pytest.mark.parametrize("name", RETIRED_NAMES)
def test_retired_builtin_cannot_execute_even_with_matching_legacy_token(
    entry, name, monkeypatch, tmp_path, trusted_actor
):
    from app.application.tools import workflow
    from app.application.tools.workflow_tools import adapters
    from app.mod_sdk import planner_native_tools, planner_tools

    monkeypatch.setenv("WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("FHD_DB_WRITE_TOKEN", "retired-token")
    actor = trusted_actor(user_id=17, role="admin")
    effects = []
    for owner, attribute in (
        (workflow, "handle_excel_analysis"),
        (adapters, "generate_document"),
        (adapters, "store_document"),
    ):
        port = Mock(side_effect=AssertionError("retired alias must not execute business code"))
        monkeypatch.setattr(owner, attribute, port)
        effects.append(port)
    monkeypatch.setattr(planner_native_tools, "is_planner_native_tools_enabled", lambda: True)
    monkeypatch.setattr(
        planner_native_tools,
        "_discover_native_tool_mods",
        lambda: [],
    )
    monkeypatch.setattr(adapters, "employee", lambda call: None)
    monkeypatch.setattr(adapters, "legacy_employee", lambda call: None)
    execute = (
        workflow.execute_workflow_tool
        if entry == "host"
        else planner_tools.execute_planner_workflow_tool
    )
    result = json.loads(
        execute(
            name,
            {
                "file_path": "not-opened.xlsx",
                "confirm": True,
                "user_request": "retired mutation",
                "items": [{"name": "must-not-create"}],
            },
            workspace_root=str(tmp_path),
            db_write_token="retired-token",
            runtime_context={**actor.context, "idempotency_key": "retired-original-request"},
        )
    )
    assert result["success"] is False
    assert result["error_code"] == "unknown_tool"
    assert result["execution_status"] == result["execution_state"] == "not_started"
    assert result["retryable"] is False
    assert "run_id" not in result and "task_id" not in result
    for effect in effects:
        effect.assert_not_called()


def test_retired_mod_http_route_is_removed_without_native_dispatch(monkeypatch):
    from app.infrastructure.mods.mod_manager import import_mod_backend_py
    from app.mod_sdk import planner_native_tools

    native = Mock(side_effect=AssertionError("removed route must not dispatch"))
    monkeypatch.setattr(planner_native_tools, "try_execute_native_planner_tool", native)
    blueprint = import_mod_backend_py(str(MOD_DIR), "retired-native-boundary", "blueprints")
    app = FastAPI()
    blueprint.register_fastapi_routes(app, "xcagi-planner-excel-tools")
    response = TestClient(app).post(
        "/api/mod/xcagi-planner-excel-tools/tools/run",
        json={"tool_name": "products_bulk_import", "arguments": {"confirm": True}},
    )
    assert response.status_code == 404
    native.assert_not_called()


def test_retired_import_is_not_registered_or_exported():
    from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
    from app.domain.shared_services.tools_workflow_dispatch import _REGISTERED_WORKFLOW_ROUTERS
    from app.mod_sdk import host_services

    assert get_tool_action_spec("import_excel_to_database", "import") is None
    assert "import_excel_to_database" not in _REGISTERED_WORKFLOW_ROUTERS
    assert not hasattr(host_services, "_handle_import_excel_to_database")
    assert not hasattr(host_services, "run_bulk_import")
    assert get_tool_action_spec("excel_analysis", "read") is not None
    assert get_tool_action_spec("generate_office_document", "execute") is not None
