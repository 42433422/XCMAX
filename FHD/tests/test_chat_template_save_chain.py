"""聊天保存 Excel 模板到模板库 — 工具链单测。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.application.tools.workflow import execute_workflow_tool, get_workflow_tool_registry
from app.domain.context.session_context import (
    enrich_template_preview_arguments,
    merge_system_prompt,
)
from app.services.tools_workflow_registered import execute_registered_workflow_tool


def test_planner_registry_includes_template_preview() -> None:
    names = [t["function"]["name"] for t in get_workflow_tool_registry() if t.get("function")]
    assert "template_preview" in names


def test_enrich_template_preview_arguments_fills_defaults() -> None:
    ctx = {
        "excel_analysis": {
            "file_path": "uploads/demo.xlsx",
            "sheets": [
                {
                    "sheet_name": "考勤表",
                    "sheet_index": 1,
                    "fields": [{"label": "姓名", "name": "姓名", "type": "dynamic"}],
                }
            ],
        }
    }
    out = enrich_template_preview_arguments({"action": "create"}, ctx)
    assert out["action"] == "create"
    assert out["file_path"] == "uploads/demo.xlsx"
    assert out["sheet_name"] == "考勤表"
    assert out["template_name"] == "考勤表-模板"


def test_execute_workflow_tool_template_preview_create() -> None:
    grid = {
        "file_path": "uploads/demo.xlsx",
        "sheets": [
            {
                "sheet_name": "考勤表",
                "sheet_index": 1,
                "fields": [{"label": "姓名", "name": "姓名", "type": "dynamic"}],
                "sample_rows": [],
                "grid_preview": {},
            }
        ],
    }
    mock_result = MagicMock()
    mock_result.lastrowid = 42
    mock_db = MagicMock()
    mock_db.execute.return_value = mock_result
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("app.db.session.get_db", return_value=mock_db):
        raw = execute_workflow_tool(
            "template_preview",
            {
                "action": "create",
                "template_name": "单测模板",
                "_runtime_context": {"excel_analysis": grid},
            },
            workspace_root="/tmp",
        )
    out = json.loads(raw)
    assert out.get("success") is True, out
    assert out.get("template", {}).get("name") == "单测模板"


def test_merge_system_prompt_mentions_template_save() -> None:
    ctx = {
        "excel_file_path": "uploads/demo.xlsx",
        "excel_analysis": {
            "file_path": "uploads/demo.xlsx",
            "sheets": [{"sheet_name": "S1", "fields": [{"label": "A"}]}],
        },
    }
    prompt = merge_system_prompt(None, ctx) or ""
    assert "template_preview" in prompt
    assert "保存到模板库" in prompt or "加入模板" in prompt


def test_registered_router_create_still_works() -> None:
    grid = {
        "file_path": "uploads/demo2.xlsx",
        "sheets": [
            {
                "sheet_name": "Sheet1",
                "fields": [{"label": "列1", "name": "列1", "type": "dynamic"}],
                "sample_rows": [],
            }
        ],
    }
    mock_result = MagicMock()
    mock_result.lastrowid = 99
    mock_db = MagicMock()
    mock_db.execute.return_value = mock_result
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)

    with patch("app.db.session.get_db", return_value=mock_db):
        out = execute_registered_workflow_tool(
            "template_preview",
            "create",
            {"name": "路由单测模板", "_runtime_context": {"excel_analysis": grid}},
        )
    assert out.get("success") is True
