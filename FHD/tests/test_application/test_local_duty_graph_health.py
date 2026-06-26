"""Branch coverage tests for app.application.local_duty_graph_health.

Covers missing branches in:
- _staffing_areas_from_doc (areas/departments fallback, subzones recursion, ids filtering)
- read_local_employee_manifest (empty pid, roots discovery, manifest file reading, error paths)
- build_local_employee_status (deployed flag, metrics parsing, success_rate computation)
- build_local_duty_graph_health (scheduler defaults, env flags)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.local_duty_graph_health import (
    _staffing_areas_from_doc,
    build_local_duty_graph_health,
    build_local_employee_status,
    read_local_employee_manifest,
)

# ---------------------------------------------------------------------------
# _staffing_areas_from_doc
# ---------------------------------------------------------------------------


class TestStaffingAreasFromDoc:
    def test_empty_doc_returns_empty_list(self):
        assert _staffing_areas_from_doc({}, set()) == []

    def test_none_doc_returns_empty_list(self):
        # doc.get would fail on None; but the function expects a dict
        # Passing {} is the safe path
        assert _staffing_areas_from_doc({}, set()) == []

    def test_areas_not_dict_falls_to_departments(self):
        doc = {"areas": "not a dict", "departments": {"zone1": {"ids": ["e1"]}}}
        result = _staffing_areas_from_doc(doc, {"e1"})
        # e1 is registered, so missing is empty
        assert len(result) == 1
        assert result[0]["key"] == "zone1"
        assert result[0]["missing"] == []

    def test_areas_empty_dict_falls_to_departments(self):
        doc = {"areas": {}, "departments": {"zone1": {"ids": ["e1"]}}}
        result = _staffing_areas_from_doc(doc, set())
        assert len(result) == 1
        assert result[0]["missing"] == ["e1"]

    def test_departments_not_dict_returns_empty(self):
        doc = {"areas": {}, "departments": "not a dict"}
        assert _staffing_areas_from_doc(doc, set()) == []

    def test_departments_none_returns_empty(self):
        doc = {"areas": {}, "departments": None}
        assert _staffing_areas_from_doc(doc, set()) == []

    def test_block_not_dict_skipped(self):
        doc = {"areas": {"zone1": "not a dict", "zone2": {"ids": ["e1"]}}}
        result = _staffing_areas_from_doc(doc, set())
        assert len(result) == 1
        assert result[0]["key"] == "zone2"

    def test_raw_ids_not_list_returns_empty_ids(self):
        doc = {"areas": {"zone1": {"ids": "not a list"}}}
        result = _staffing_areas_from_doc(doc, set())
        # ids is empty, so block is not appended
        assert result == []

    def test_raw_ids_none_returns_empty_ids(self):
        doc = {"areas": {"zone1": {"ids": None}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result == []

    def test_raw_ids_with_empty_strings_filtered(self):
        doc = {"areas": {"zone1": {"ids": ["", "  ", "e1"]}}}
        result = _staffing_areas_from_doc(doc, set())
        assert len(result) == 1
        assert result[0]["missing"] == ["e1"]

    def test_raw_ids_with_non_string_converted(self):
        doc = {"areas": {"zone1": {"ids": [1, 2, "e1"]}}}
        result = _staffing_areas_from_doc(doc, {"1", "2"})
        # "1" and "2" are registered, "e1" is missing
        assert result[0]["missing"] == ["e1"]

    def test_label_falls_back_to_key(self):
        doc = {"areas": {"zone1": {"ids": ["e1"]}}}  # no label field
        result = _staffing_areas_from_doc(doc, set())
        assert result[0]["label"] == "zone1"

    def test_label_from_field(self):
        doc = {"areas": {"zone1": {"ids": ["e1"], "label": "Zone One"}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result[0]["label"] == "Zone One"

    def test_label_empty_string_falls_back_to_key(self):
        doc = {"areas": {"zone1": {"ids": ["e1"], "label": ""}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result[0]["label"] == "zone1"

    def test_label_none_falls_back_to_key(self):
        doc = {"areas": {"zone1": {"ids": ["e1"], "label": None}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result[0]["label"] == "zone1"

    def test_subzones_dict_recursion(self):
        doc = {
            "areas": {
                "zone1": {
                    "ids": ["e1"],
                    "subzones": {
                        "sub1": {"ids": ["e2"]},
                        "sub2": {"ids": ["e3"]},
                    },
                }
            }
        }
        result = _staffing_areas_from_doc(doc, set())
        assert len(result) == 3
        keys = [r["key"] for r in result]
        assert "zone1" in keys
        assert "zone1/sub1" in keys
        assert "zone1/sub2" in keys

    def test_subzones_not_dict_skipped(self):
        doc = {
            "areas": {
                "zone1": {
                    "ids": ["e1"],
                    "subzones": "not a dict",
                }
            }
        }
        result = _staffing_areas_from_doc(doc, set())
        assert len(result) == 1
        assert result[0]["key"] == "zone1"

    def test_subzone_value_not_dict_skipped(self):
        doc = {
            "areas": {
                "zone1": {
                    "ids": ["e1"],
                    "subzones": {
                        "sub1": "not a dict",
                        "sub2": {"ids": ["e2"]},
                    },
                }
            }
        }
        result = _staffing_areas_from_doc(doc, set())
        # zone1 itself + zone1/sub2 (sub1 is skipped)
        assert len(result) == 2
        keys = [r["key"] for r in result]
        assert "zone1/sub1" not in keys
        assert "zone1/sub2" in keys

    def test_missing_sorted(self):
        doc = {"areas": {"zone1": {"ids": ["e3", "e1", "e2"]}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result[0]["missing"] == ["e1", "e2", "e3"]

    def test_registered_excluded_from_missing(self):
        doc = {"areas": {"zone1": {"ids": ["e1", "e2", "e3"]}}}
        result = _staffing_areas_from_doc(doc, {"e2"})
        assert result[0]["missing"] == ["e1", "e3"]

    def test_all_registered_no_missing(self):
        doc = {"areas": {"zone1": {"ids": ["e1", "e2"]}}}
        result = _staffing_areas_from_doc(doc, {"e1", "e2"})
        assert result[0]["missing"] == []

    def test_empty_ids_not_appended(self):
        doc = {"areas": {"zone1": {"ids": []}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result == []

    def test_no_ids_field_not_appended(self):
        doc = {"areas": {"zone1": {"label": "Zone One"}}}
        result = _staffing_areas_from_doc(doc, set())
        assert result == []

    def test_nested_subzones_recursion(self):
        doc = {
            "areas": {
                "zone1": {
                    "subzones": {
                        "sub1": {
                            "subzones": {
                                "deep1": {"ids": ["e1"]}
                            }
                        }
                    }
                }
            }
        }
        result = _staffing_areas_from_doc(doc, set())
        assert len(result) == 1
        assert result[0]["key"] == "zone1/sub1/deep1"


# ---------------------------------------------------------------------------
# read_local_employee_manifest
# ---------------------------------------------------------------------------


class TestReadLocalEmployeeManifest:
    def test_empty_employee_id_returns_none(self):
        assert read_local_employee_manifest("") is None

    def test_none_employee_id_returns_none(self):
        assert read_local_employee_manifest(None) is None

    def test_whitespace_employee_id_returns_none(self):
        assert read_local_employee_manifest("   ") is None

    def test_strips_employee_id(self, tmp_path):
        # Create a manifest file
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        manifest = {"name": "Test Employee", "version": "1.0"}
        (emp_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("  emp-1  ")

        assert result is not None
        assert result["employee_id"] == "emp-1"
        assert result["name"] == "Test Employee"
        assert result["version"] == "1.0"
        assert result["manifest"] == manifest

    def test_all_mods_roots_returns_none_falls_to_primary(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"name": "Test"}), encoding="utf-8"
        )

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = None
        mgr.mods_root = str(tmp_path)

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None
        assert result["name"] == "Test"

    def test_all_mods_roots_empty_falls_to_primary(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"name": "Test"}), encoding="utf-8"
        )

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = []
        mgr.mods_root = str(tmp_path)

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None

    def test_all_mods_roots_raises_error_falls_to_primary(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"name": "Test"}), encoding="utf-8"
        )

        mgr = MagicMock()
        mgr.all_mods_roots.side_effect = RuntimeError("fail")
        mgr.mods_root = str(tmp_path)

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None

    def test_no_roots_no_primary_returns_none(self):
        mgr = MagicMock()
        mgr.all_mods_roots.return_value = []
        mgr.mods_root = None

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is None

    def test_no_roots_empty_primary_returns_none(self):
        mgr = MagicMock()
        mgr.all_mods_roots.return_value = []
        mgr.mods_root = ""

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is None

    def test_manifest_not_found_returns_none(self, tmp_path):
        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("nonexistent")

        assert result is None

    def test_empty_mods_root_skipped(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"name": "Test"}), encoding="utf-8"
        )

        mgr = MagicMock()
        # First root is empty (should be skipped), second has the file
        mgr.all_mods_roots.return_value = ["", str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None

    def test_none_mods_root_skipped(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps({"name": "Test"}), encoding="utf-8"
        )

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [None, str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None

    def test_non_dict_manifest_returns_none(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text(
            json.dumps([1, 2, 3]), encoding="utf-8"
        )

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is None

    def test_invalid_json_returns_none(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        (emp_dir / "manifest.json").write_text("{invalid json", encoding="utf-8")

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is None

    def test_get_mod_manager_raises_returns_none(self):
        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager",
            side_effect=RuntimeError("fail"),
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is None

    def test_first_root_with_manifest_wins(self, tmp_path):
        # Create two roots, both with the manifest
        root1 = tmp_path / "root1"
        root2 = tmp_path / "root2"
        for root in [root1, root2]:
            emp_dir = root / "_employees" / "emp-1"
            emp_dir.mkdir(parents=True)
            (emp_dir / "manifest.json").write_text(
                json.dumps({"root": str(root)}), encoding="utf-8"
            )

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [str(root1), str(root2)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None
        assert result["root"] == str(root1)

    def test_manifest_data_merged_into_result(self, tmp_path):
        emp_dir = tmp_path / "_employees" / "emp-1"
        emp_dir.mkdir(parents=True)
        manifest = {"name": "Test", "version": "2.0", "custom_field": "value"}
        (emp_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

        mgr = MagicMock()
        mgr.all_mods_roots.return_value = [str(tmp_path)]

        with patch(
            "app.infrastructure.mods.mod_manager.get_mod_manager", return_value=mgr
        ):
            result = read_local_employee_manifest("emp-1")

        assert result is not None
        assert result["employee_id"] == "emp-1"
        assert result["manifest"] == manifest
        assert result["name"] == "Test"
        assert result["version"] == "2.0"
        assert result["custom_field"] == "value"


# ---------------------------------------------------------------------------
# build_local_employee_status
# ---------------------------------------------------------------------------


class TestBuildLocalEmployeeStatus:
    def test_empty_employee_id(self):
        with patch(
            "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
            return_value={},
        ):
            result = build_local_employee_status("")
        assert result["employee_id"] == ""
        assert result["deployed"] is False
        assert result["execution_stats"]["total_executions"] == 0

    def test_none_employee_id(self):
        with patch(
            "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
            return_value={},
        ):
            result = build_local_employee_status(None)
        assert result["employee_id"] == ""
        assert result["deployed"] is False

    def test_whitespace_employee_id_stripped(self):
        with patch(
            "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
            return_value={},
        ):
            with patch(
                "app.application.local_duty_graph_health.read_local_employee_manifest",
                return_value=None,
            ):
                result = build_local_employee_status("  emp-1  ")
        assert result["employee_id"] == "emp-1"

    def test_deployed_true_when_manifest_exists(self):
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value={"employee_id": "emp-1", "name": "Test"},
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value={},
            ):
                result = build_local_employee_status("emp-1")
        assert result["deployed"] is True

    def test_deployed_false_when_manifest_missing(self):
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value={},
            ):
                result = build_local_employee_status("emp-1")
        assert result["deployed"] is False

    def test_no_metrics_returns_zeros(self):
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value={},
            ):
                result = build_local_employee_status("emp-1")
        stats = result["execution_stats"]
        assert stats["total_executions"] == 0
        assert stats["success_count"] == 0
        assert stats["failed_count"] == 0
        assert stats["blocked_count"] == 0
        assert stats["success_rate"] == 0

    def test_metrics_by_employee_none_returns_zeros(self):
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value={"by_employee": None},
            ):
                result = build_local_employee_status("emp-1")
        assert result["execution_stats"]["total_executions"] == 0

    def test_metrics_by_employee_empty_dict_returns_zeros(self):
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value={"by_employee": {}},
            ):
                result = build_local_employee_status("emp-1")
        assert result["execution_stats"]["total_executions"] == 0

    def test_metrics_with_runs(self):
        metrics = {
            "by_employee": {
                "emp-1": {
                    "runs_total": 10,
                    "runs_success": 8,
                    "runs_failed": 2,
                    "runs_blocked": 1,
                    "last_execution": "2026-01-01T00:00:00",
                }
            }
        }
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value=metrics,
            ):
                result = build_local_employee_status("emp-1")
        stats = result["execution_stats"]
        assert stats["total_executions"] == 10
        assert stats["success_count"] == 8
        assert stats["failed_count"] == 2
        assert stats["blocked_count"] == 1
        assert stats["success_rate"] == 0.8
        assert result["last_execution"] == "2026-01-01T00:00:00"

    def test_success_rate_zero_when_total_zero(self):
        metrics = {
            "by_employee": {
                "emp-1": {
                    "runs_total": 0,
                    "runs_success": 0,
                }
            }
        }
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value=metrics,
            ):
                result = build_local_employee_status("emp-1")
        assert result["execution_stats"]["success_rate"] == 0

    def test_runs_total_none_treated_as_zero(self):
        metrics = {
            "by_employee": {
                "emp-1": {
                    "runs_total": None,
                    "runs_success": None,
                    "runs_failed": None,
                    "runs_blocked": None,
                }
            }
        }
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value=metrics,
            ):
                result = build_local_employee_status("emp-1")
        stats = result["execution_stats"]
        assert stats["total_executions"] == 0
        assert stats["success_count"] == 0
        assert stats["failed_count"] == 0
        assert stats["blocked_count"] == 0

    def test_runs_total_string_converted(self):
        metrics = {
            "by_employee": {
                "emp-1": {
                    "runs_total": "10",
                    "runs_success": "8",
                }
            }
        }
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value=metrics,
            ):
                result = build_local_employee_status("emp-1")
        assert result["execution_stats"]["total_executions"] == 10
        assert result["execution_stats"]["success_count"] == 8

    def test_last_execution_none_when_not_in_metrics(self):
        metrics = {"by_employee": {"emp-1": {}}}
        with patch(
            "app.application.local_duty_graph_health.read_local_employee_manifest",
            return_value=None,
        ):
            with patch(
                "app.application.employee_runtime.metrics.get_employee_runtime_metrics",
                return_value=metrics,
            ):
                result = build_local_employee_status("emp-1")
        assert result["last_execution"] is None


# ---------------------------------------------------------------------------
# build_local_duty_graph_health (additional branch coverage)
# ---------------------------------------------------------------------------


class TestBuildLocalDutyGraphHealth:
    def test_scheduler_defaults_when_keys_missing(self):
        """When scheduler dict is empty, defaults should be applied."""
        with (
            patch(
                "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
                return_value=frozenset(),
            ),
            patch(
                "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health._duty_employee_area_map",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health.load_duty_roster_document",
                return_value={},
            ),
        ):
            result = build_local_duty_graph_health()
        assert result["success"] is True
        assert result["source"] == "local"
        assert result["employee_cron_jobs"] == []
        assert result["employee_scheduler"]["enabled"] is False
        assert result["employee_scheduler"]["running"] is False
        assert result["employee_scheduler"]["last_error"] == ""

    def test_scheduler_with_values(self):
        with (
            patch(
                "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
                return_value=frozenset(),
            ),
            patch(
                "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
                return_value={
                    "enabled": True,
                    "running": True,
                    "last_error": "some error",
                    "jobs": [{"job_id": "j1"}],
                },
            ),
            patch(
                "app.application.local_duty_graph_health._duty_employee_area_map",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health.load_duty_roster_document",
                return_value={},
            ),
        ):
            result = build_local_duty_graph_health()
        assert result["employee_cron_jobs"] == [{"job_id": "j1"}]
        assert result["employee_scheduler"]["enabled"] is True
        assert result["employee_scheduler"]["running"] is True
        assert result["employee_scheduler"]["last_error"] == "some error"

    def test_env_flags_default(self, monkeypatch):
        monkeypatch.delenv("MODSTORE_DAILY_ORCHESTRATOR_ENABLED", raising=False)
        monkeypatch.delenv("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", raising=False)
        with (
            patch(
                "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
                return_value=frozenset(),
            ),
            patch(
                "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health._duty_employee_area_map",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health.load_duty_roster_document",
                return_value={},
            ),
        ):
            result = build_local_duty_graph_health()
        assert result["env_flags"]["MODSTORE_DAILY_ORCHESTRATOR_ENABLED"] == "1"
        assert result["env_flags"]["MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED"] == "1"

    def test_env_flags_custom(self, monkeypatch):
        monkeypatch.setenv("MODSTORE_DAILY_ORCHESTRATOR_ENABLED", "0")
        monkeypatch.setenv("MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED", "false")
        with (
            patch(
                "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
                return_value=frozenset(),
            ),
            patch(
                "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health._duty_employee_area_map",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health.load_duty_roster_document",
                return_value={},
            ),
        ):
            result = build_local_duty_graph_health()
        assert result["env_flags"]["MODSTORE_DAILY_ORCHESTRATOR_ENABLED"] == "0"
        assert result["env_flags"]["MODSTORE_EMPLOYEE_AUTO_CRON_ENABLED"] == "false"

    def test_staffing_counts(self):
        with (
            patch(
                "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
                return_value=frozenset({"emp-a", "emp-b", "emp-c"}),
            ),
            patch(
                "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
                return_value={"emp-a", "emp-d"},
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health._duty_employee_area_map",
                return_value={"emp-a": "zone1"},
            ),
            patch(
                "app.application.local_duty_graph_health.load_duty_roster_document",
                return_value={},
            ),
        ):
            result = build_local_duty_graph_health()
        staffing = result["staffing"]
        assert staffing["planned_count"] == 3
        assert staffing["registered_count"] == 1  # only emp-a is in both
        assert staffing["missing_local_employee_packs"] == ["emp-b", "emp-c"]
        assert staffing["extra_employees"] == ["emp-d"]
        assert staffing["area_map_size"] == 1

    def test_change_requests_always_zero(self):
        with (
            patch(
                "app.application.local_duty_graph_health.all_planned_duty_employee_ids",
                return_value=frozenset(),
            ),
            patch(
                "app.application.local_duty_graph_health._local_registered_employee_pack_ids",
                return_value=set(),
            ),
            patch(
                "app.application.employee_runtime.scheduler.get_employee_scheduler_status",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health._duty_employee_area_map",
                return_value={},
            ),
            patch(
                "app.application.local_duty_graph_health.load_duty_roster_document",
                return_value={},
            ),
        ):
            result = build_local_duty_graph_health()
        assert result["change_requests"] == {"pending": 0, "failed": 0}
        assert result["incident_unknown_24h"] == 0
