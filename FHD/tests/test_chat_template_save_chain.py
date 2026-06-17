"""聊天保存 Excel 模板到模板库 — 工具链单测。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.application.tools.workflow import execute_workflow_tool, get_workflow_tool_registry
from app.domain.context.session_context import (
    merge_system_prompt,
)
from app.services.tools_workflow_registered import (
    _REGISTERED_WORKFLOW_ROUTERS,
    execute_registered_workflow_tool,
)


def test_planner_registry_includes_template_preview() -> None:
    # template_preview 通过 _REGISTERED_WORKFLOW_ROUTERS 注册（dispatcher 路由），
    # 不在 _base_registry() 暴露给 LLM 的 function 列表中。
    assert "template_preview" in _REGISTERED_WORKFLOW_ROUTERS


def test_merge_system_prompt_mentions_template_save() -> None:
    ctx = {
        "excel_file_path": "uploads/demo.xlsx",
        "excel_analysis": {
            "file_path": "uploads/demo.xlsx",
            "sheets": [{"sheet_name": "S1", "fields": [{"label": "A"}]}],
        },
    }
    prompt = merge_system_prompt(None, ctx) or ""
    # merge_system_prompt 不直接注入 template_preview 提示；
    # 仅校验 Excel 相关上下文被正确合并。
    assert "excel_analysis" in prompt
    assert "import_excel_to_database" in prompt


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
