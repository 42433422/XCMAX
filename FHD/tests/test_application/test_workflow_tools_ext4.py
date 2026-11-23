"""Workflow composition and the retained spreadsheet analysis contract."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


class TestParseExcelHeaderRow1based:
    def test_with_header_row_key(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        args = {"header_row": 2}
        result = _parse_excel_header_row_1based(args)
        assert result == 2

    def test_with_header_row_index_key(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        # The implementation reads `header_row_index` as a fallback key.
        args = {"header_row_index": 3}
        result = _parse_excel_header_row_1based(args)
        assert result == 3

    def test_empty_args(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        result = _parse_excel_header_row_1based({})
        assert result is None or result == 1

    def test_none_args(self):
        from app.application.tools.workflow import _parse_excel_header_row_1based

        # The implementation does not guard against None; expect AttributeError.
        with pytest.raises(AttributeError):
            _parse_excel_header_row_1based(None)


class TestExecuteWorkflowToolErrors:
    def test_unknown_tool(self):
        from app.application.tools.workflow import execute_workflow_tool

        # execute_workflow_tool returns a JSON-encoded string.
        result = execute_workflow_tool("nonexistent_tool_xyz", {})
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed.get("success") is False or "error" in parsed or "不支持" in str(parsed)

    def test_empty_tool_name(self):
        from app.application.tools.workflow import execute_workflow_tool

        result = execute_workflow_tool("", {})
        assert isinstance(result, str)
        # Should be JSON-parseable.
        json.loads(result)

    def test_none_args(self):
        from app.application.tools.workflow import execute_workflow_tool

        # execute_workflow_tool tolerates None args by treating it as "{}".
        result = execute_workflow_tool("query_products", None)
        assert isinstance(result, str)
        json.loads(result)


class TestGetWorkflowToolRegistry:
    def test_returns_list(self):
        from app.application.tools.workflow import get_workflow_tool_registry

        result = get_workflow_tool_registry()
        assert isinstance(result, list)

    def test_invalidate_and_reget(self):
        from app.application.tools.workflow import (
            get_workflow_tool_registry,
            invalidate_workflow_tool_registry,
        )

        invalidate_workflow_tool_registry()
        result = get_workflow_tool_registry()
        assert isinstance(result, list)
