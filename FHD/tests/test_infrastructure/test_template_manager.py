"""Tests for app.infrastructure.skills.template_manager.template_manager — pure functions."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.skills.template_manager.template_manager import (
    get_base_dir,
    get_template_manager_skill,
    list_physical_template_files,
    get_template_file,
)


# ========================= get_base_dir ==================================


class TestGetBaseDir:
    def test_returns_string(self):
        result = get_base_dir()
        assert isinstance(result, str)
        assert len(result) > 0


# ========================= get_template_manager_skill ====================


class TestGetTemplateManagerSkill:
    def test_structure(self):
        skill = get_template_manager_skill()
        assert skill["name"] == "template-manager"
        assert "functions" in skill
        assert isinstance(skill["functions"], dict)

    def test_has_required_functions(self):
        skill = get_template_manager_skill()
        required = [
            "list_all_templates",
            "list_templates_by_type",
            "get_template_file_path",
            "get_default_template",
            "save_template_file",
            "get_template_info",
            "create_template",
            "update_template",
            "delete_template",
        ]
        for fn_name in required:
            assert fn_name in skill["functions"], f"Missing function: {fn_name}"

    def test_functions_are_callable(self):
        skill = get_template_manager_skill()
        for fn_name, fn in skill["functions"].items():
            assert callable(fn), f"Function {fn_name} is not callable"


# ========================= list_physical_template_files ==================


class TestListPhysicalTemplateFiles:
    def test_no_dirs(self):
        with patch("os.path.exists", return_value=False):
            result = list_physical_template_files()
            assert result == []

    def test_with_xlsx_files(self):
        with patch("os.path.exists", return_value=True), \
             patch("os.listdir", return_value=["test.xlsx", "readme.txt"]), \
             patch("os.path.getsize", return_value=1024), \
             patch("os.path.join", side_effect=lambda *args: "/".join(args)):
            result = list_physical_template_files()
            # Should only include .xlsx/.xls files
            assert len(result) == 2  # one from templates dir, one from temp_excel dir
            for item in result:
                assert item["filename"] == "test.xlsx"

    def test_no_excel_files(self):
        with patch("os.path.exists", return_value=True), \
             patch("os.listdir", return_value=["readme.txt", "image.png"]):
            result = list_physical_template_files()
            assert result == []


# ========================= get_template_file =============================


class TestGetTemplateFile:
    def test_not_found(self):
        with patch("os.path.exists", return_value=False):
            result = get_template_file("nonexistent.xlsx")
            assert result is None

    def test_found_in_templates(self):
        def exists_side_effect(p):
            # The directory check and file check both need to return True
            return "templates" in p

        with patch("os.path.exists", side_effect=exists_side_effect), \
             patch("os.path.getsize", return_value=2048), \
             patch("os.path.join", side_effect=lambda *args: "/".join(args)):
            result = get_template_file("test.xlsx")
            assert result is not None
            assert result["filename"] == "test.xlsx"
            assert result["size_bytes"] == 2048
