"""Tests for app.services.kitten_report.save_service — coverage ramp."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.services.kitten_report.save_service import AnalysisSaveService


@pytest.fixture
def save_service(tmp_path):
    return AnalysisSaveService(save_dir=str(tmp_path / "analyses"))


class TestSaveAnalysis:
    def test_save_success(self, save_service):
        result = save_service.save_analysis(
            "test_type",
            {"key": "value"},
            metadata={"source": "unit_test"},
        )
        assert result["success"] is True
        assert result["id"].startswith("analysis_")
        assert result["filename"].startswith("test_type_")
        assert os.path.exists(result["filepath"])

    def test_save_creates_file(self, save_service):
        result = save_service.save_analysis("my_analysis", {"data": [1, 2, 3]})
        with open(result["filepath"], encoding="utf-8") as f:
            content = json.load(f)
        assert content["type"] == "my_analysis"
        assert content["data"] == {"data": [1, 2, 3]}

    def test_save_without_metadata(self, save_service):
        result = save_service.save_analysis("simple", {"x": 1})
        assert result["success"] is True
        with open(result["filepath"], encoding="utf-8") as f:
            content = json.load(f)
        assert content["metadata"] == {}


class TestListSavedAnalyses:
    def test_empty(self, save_service):
        result = save_service.list_saved_analyses()
        assert result == []

    def test_list_after_save(self, save_service):
        save_service.save_analysis("type_a", {"data": 1})
        save_service.save_analysis("type_b", {"data": 2})
        result = save_service.list_saved_analyses()
        assert len(result) == 2

    def test_filter_by_type(self, save_service):
        save_service.save_analysis("type_a", {"data": 1})
        save_service.save_analysis("type_b", {"data": 2})
        result = save_service.list_saved_analyses(analysis_type="type_a")
        assert len(result) == 1
        assert result[0]["type"] == "type_a"

    def test_ignores_non_json(self, save_service):
        with open(os.path.join(save_service.save_dir, "readme.txt"), "w") as f:
            f.write("not json")
        result = save_service.list_saved_analyses()
        assert result == []


class TestGetAnalysis:
    def test_get_existing(self, save_service):
        saved = save_service.save_analysis("test", {"key": "val"})
        result = save_service.get_analysis(saved["id"])
        assert result is not None
        assert result["type"] == "test"

    def test_get_nonexistent(self, save_service):
        result = save_service.get_analysis("nonexistent_id")
        assert result is None


class TestDeleteAnalysis:
    def test_delete_existing(self, save_service):
        saved = save_service.save_analysis("test", {"key": "val"})
        result = save_service.delete_analysis(saved["id"])
        assert result is True
        assert save_service.get_analysis(saved["id"]) is None

    def test_delete_nonexistent(self, save_service):
        result = save_service.delete_analysis("nonexistent_id")
        assert result is False


class TestInit:
    def test_default_save_dir(self):
        svc = AnalysisSaveService()
        assert svc.save_dir.endswith("saved_analyses")

    def test_custom_save_dir(self, tmp_path):
        svc = AnalysisSaveService(save_dir=str(tmp_path / "custom"))
        assert svc.save_dir == str(tmp_path / "custom")
        assert os.path.isdir(svc.save_dir)
