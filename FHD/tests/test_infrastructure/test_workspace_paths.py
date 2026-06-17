"""Tests for app.infrastructure.attendance.workspace_paths."""
from __future__ import annotations

import os
import pytest

from app.infrastructure.attendance.workspace_paths import resolve_workspace_excel


class TestResolveWorkspaceExcel:
    def test_basic_relative_path(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspace")
        result = resolve_workspace_excel("data/file.xlsx")
        assert "data/file.xlsx" in str(result)

    def test_backslash_converted_to_forward(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspace")
        result = resolve_workspace_excel("data\\file.xlsx")
        assert "data/file.xlsx" in str(result)

    def test_leading_slash_stripped(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspace")
        result = resolve_workspace_excel("/data/file.xlsx")
        assert "data/file.xlsx" in str(result)

    def test_empty_path(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspace")
        result = resolve_workspace_excel("")
        assert "workspace" in str(result)

    def test_path_traversal_raises(self, monkeypatch):
        monkeypatch.setenv("WORKSPACE_ROOT", "/tmp/workspace")
        with pytest.raises(ValueError):
            resolve_workspace_excel("../../etc/passwd")

    def test_default_workspace_root(self, monkeypatch):
        monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
        result = resolve_workspace_excel("data/file.xlsx")
        assert "data/file.xlsx" in str(result)
