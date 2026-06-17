"""Tests for app.infrastructure.attendance.workspace_paths."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.infrastructure.attendance.workspace_paths import resolve_workspace_excel


class TestResolveWorkspaceExcel:
    """Tests for resolve_workspace_excel."""

    def test_resolves_relative_path(self) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": "/tmp/test_workspace"}):
            result = resolve_workspace_excel("data/excel/file.xlsx")
            result_str = str(result)
            # macOS may resolve /tmp to /private/tmp
            assert "test_workspace" in result_str
            assert "data/excel/file.xlsx" in result_str

    def test_uses_cwd_when_no_env(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = resolve_workspace_excel("test.xlsx")
            assert "test.xlsx" in str(result)

    def test_strips_leading_slash(self) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": "/tmp/ws"}):
            result = resolve_workspace_excel("/absolute/path.xlsx")
            assert "absolute/path.xlsx" in str(result)

    def test_handles_backslashes(self) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": "/tmp/ws"}):
            result = resolve_workspace_excel("folder\\file.xlsx")
            assert "folder/file.xlsx" in str(result)

    def test_empty_path(self) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": "/tmp/ws"}):
            result = resolve_workspace_excel("")
            # macOS resolves /tmp to /private/tmp
            assert "ws" in str(result)

    def test_raises_for_path_traversal(self) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": "/tmp/ws"}):
            with pytest.raises(ValueError):
                resolve_workspace_excel("../../etc/passwd")

    def test_returns_path_object(self) -> None:
        with patch.dict("os.environ", {"WORKSPACE_ROOT": "/tmp/ws"}):
            result = resolve_workspace_excel("file.xlsx")
            assert isinstance(result, Path)
