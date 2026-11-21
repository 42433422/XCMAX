"""COVERAGE_RAMP Phase 1 (p1-p0-core): workflow helpers and registered dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.application.tools.workflow import (
    _parse_excel_header_row_1based,
    execute_workflow_tool,
    get_workflow_tool_registry,
    invalidate_workflow_tool_registry,
)

# ---------------------------------------------------------------------------
# workflow.py pure helpers
# ---------------------------------------------------------------------------


def test_workflow_tool_registry_roundtrip() -> None:
    invalidate_workflow_tool_registry()
    reg = get_workflow_tool_registry()
    assert isinstance(reg, list)
    assert reg == []
    names = set()
    for t in reg:
        if isinstance(t, dict):
            fn = t.get("function") or {}
            if isinstance(fn, dict) and fn.get("name"):
                names.add(fn["name"])
    assert names == set()


def test_parse_excel_header_row_edge_cases() -> None:
    assert _parse_excel_header_row_1based({"header_row": -1}) is None
    assert _parse_excel_header_row_1based({"header_row": "2"}) == 2


# ---------------------------------------------------------------------------
# execute_workflow_tool entry (mocked)
# ---------------------------------------------------------------------------


@patch("app.mod_sdk.employee_tool_registry.is_employee_tool", return_value=False)
def test_execute_workflow_tool_unknown(_mock_emp: MagicMock) -> None:
    out = execute_workflow_tool("unknown_xyz_tool", {})
    assert isinstance(out, str)
    assert "error" in out.lower() or "unknown" in out.lower() or "失败" in out
