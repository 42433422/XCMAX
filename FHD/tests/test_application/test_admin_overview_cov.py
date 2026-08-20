# mypy: disable-error-code="var-annotated"
"""Coverage tests for app.application.autonomy.admin_overview helpers.

Focuses on uncovered branches: env var resolution, JSONL edge cases,
cursor/limit clamping, gh CLI error paths, cross-tier gate state fallbacks,
and default remote-state file probing.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.application.autonomy import admin_overview as ao

# ---------------------------------------------------------------------------
# Path / env-var resolution helpers
# ---------------------------------------------------------------------------


class TestRuntimeMetricsDir:
    def test_autonomy_data_dir_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", "/tmp/autonomy_data")
        monkeypatch.setenv("XCAGI_DATA_DIR", "/tmp/generic_data")
        result = ao._runtime_metrics_dir()
        assert result == Path("/tmp/autonomy_data")

    def test_falls_back_to_xcagi_data_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_AUTONOMY_DATA_DIR", raising=False)
        monkeypatch.setenv("XCAGI_DATA_DIR", "/tmp/generic_data")
        result = ao._runtime_metrics_dir()
        assert result == Path("/tmp/generic_data")

    def test_default_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_AUTONOMY_DATA_DIR", raising=False)
        monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
        result = ao._runtime_metrics_dir()
        assert result == ao._FHD_ROOT / "metrics"

    def test_whitespace_only_env_treated_as_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", "   ")
        monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
        result = ao._runtime_metrics_dir()
        assert result == ao._FHD_ROOT / "metrics"

    def test_expanduser_tilde(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", "~/autonomy")
        result = ao._runtime_metrics_dir()
        assert result == Path.home() / "autonomy"


class TestDeployEventsPath:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", "/tmp/deploy.jsonl")
        assert ao.deploy_events_path() == Path("/tmp/deploy.jsonl")

    def test_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_DEPLOY_EVENTS_PATH", raising=False)
        assert ao.deploy_events_path() == ao._FHD_ROOT / "metrics" / "deploy_events.jsonl"

    def test_expanduser(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", "~/deploy.jsonl")
        assert ao.deploy_events_path() == Path.home() / "deploy.jsonl"

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", "  /tmp/x.jsonl  ")
        assert ao.deploy_events_path() == Path("/tmp/x.jsonl")


class TestAutonomyMetricsPath:
    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", "/tmp/metrics.jsonl")
        assert ao.autonomy_metrics_path() == Path("/tmp/metrics.jsonl")

    def test_default_uses_runtime_metrics_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", raising=False)
        monkeypatch.delenv("XCAGI_AUTONOMY_DATA_DIR", raising=False)
        monkeypatch.delenv("XCAGI_DATA_DIR", raising=False)
        assert ao.autonomy_metrics_path() == ao._FHD_ROOT / "metrics" / "autonomy-metrics.jsonl"

    def test_default_honors_runtime_dir_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", raising=False)
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", "/tmp/rt")
        assert ao.autonomy_metrics_path() == Path("/tmp/rt/autonomy-metrics.jsonl")


# ---------------------------------------------------------------------------
# _read_jsonl
# ---------------------------------------------------------------------------


class TestReadJsonl:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert ao._read_jsonl(tmp_path / "nope.jsonl") == []

    def test_reads_valid_jsonl_newest_first(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text(
            json.dumps({"i": 1}) + "\n" + json.dumps({"i": 2}) + "\n",
            encoding="utf-8",
        )
        rows = ao._read_jsonl(path)
        assert [r["i"] for r in rows] == [2, 1]

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text("\n" + json.dumps({"i": 1}) + "\n\n   \n", encoding="utf-8")
        assert ao._read_jsonl(path) == [{"i": 1}]

    def test_skips_invalid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text(
            "not json\n" + json.dumps({"i": 1}) + "\n{bad\n",
            encoding="utf-8",
        )
        assert ao._read_jsonl(path) == [{"i": 1}]

    def test_skips_non_dict_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text(
            json.dumps([1, 2]) + "\n" + json.dumps("str") + "\n" + json.dumps({"i": 1}) + "\n",
            encoding="utf-8",
        )
        assert ao._read_jsonl(path) == [{"i": 1}]

    def test_limit_caps_items(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        lines = [json.dumps({"i": n}) for n in range(10)]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rows = ao._read_jsonl(path, limit=3)
        assert [r["i"] for r in rows] == [9, 8, 7]

    def test_limit_zero_treated_as_one(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text(json.dumps({"i": 1}) + "\n" + json.dumps({"i": 2}) + "\n", encoding="utf-8")
        rows = ao._read_jsonl(path, limit=0)
        assert rows == [{"i": 2}]

    def test_negative_limit_treated_as_one(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text(json.dumps({"i": 1}) + "\n" + json.dumps({"i": 2}) + "\n", encoding="utf-8")
        rows = ao._read_jsonl(path, limit=-5)
        assert rows == [{"i": 2}]

    def test_os_error_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "f.jsonl"
        path.write_text(json.dumps({"i": 1}) + "\n", encoding="utf-8")

        with patch.object(Path, "read_text", side_effect=OSError("boom")):
            assert ao._read_jsonl(path) == []

    def test_is_file_false_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.jsonl"
        with patch.object(Path, "is_file", return_value=False):
            assert ao._read_jsonl(path) == []


# ---------------------------------------------------------------------------
# list_deploy_events
# ---------------------------------------------------------------------------


class TestListDeployEvents:
    def _write_events(self, path: Path, count: int) -> None:
        lines = [
            json.dumps({"deploy_id": f"d{n}", "deployed_at": f"2026-07-{n:02d}"})
            for n in range(1, count + 1)
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_empty_file_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        path.write_text("", encoding="utf-8")
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        data = ao.list_deploy_events(limit=10)
        assert data["count"] == 0
        assert data["items"] == []
        assert data["next_cursor"] is None

    def test_cursor_stops_before_matching_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 5)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        # newest first: d5 d4 d3 d2 d1; cursor "d3" → stop before d3 → [d5, d4]
        data = ao.list_deploy_events(limit=10, since_cursor="d3")
        assert [item["deploy_id"] for item in data["items"]] == ["d5", "d4"]

    def test_cursor_matches_first_row_returns_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 3)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        data = ao.list_deploy_events(limit=10, since_cursor="d3")
        assert data["items"] == []
        assert data["count"] == 0
        assert data["next_cursor"] is None

    def test_cursor_not_matched_returns_up_to_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 5)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        data = ao.list_deploy_events(limit=3, since_cursor="nonexistent")
        assert [item["deploy_id"] for item in data["items"]] == ["d5", "d4", "d3"]
        assert data["next_cursor"] == "d3"

    def test_cursor_with_whitespace_stripped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 3)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        data = ao.list_deploy_events(limit=10, since_cursor="  d2  ")
        # newest first: d3 d2 d1; cursor "d2" → stop before d2 → [d3]
        assert [item["deploy_id"] for item in data["items"]] == ["d3"]

    def test_limit_below_one_clamped_to_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 3)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        # limit=-1 (negative) clamps to 1 via max(1, ...); limit=0 is falsy → defaults to 20
        data = ao.list_deploy_events(limit=-1)
        assert data["count"] == 1
        assert data["items"][0]["deploy_id"] == "d3"

    def test_limit_above_200_clamped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 3)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        # only 3 rows exist, so clamping to 200 doesn't matter; verify no error
        data = ao.list_deploy_events(limit=999)
        assert data["count"] == 3

    def test_limit_none_defaults_to_20(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 3)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        data = ao.list_deploy_events(limit=None)  # type: ignore[arg-type]
        assert data["count"] == 3

    def test_next_cursor_from_last_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "deploy.jsonl"
        self._write_events(path, 3)
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        # newest first: d3, d2, d1; limit=2 → [d3, d2], next_cursor = last item's deploy_id
        data = ao.list_deploy_events(limit=2)
        assert data["next_cursor"] == "d2"

    def test_row_fields_mapped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        path = tmp_path / "deploy.jsonl"
        path.write_text(
            json.dumps(
                {
                    "deploy_id": "x1",
                    "deployed_at": "2026-07-01",
                    "commit_at": "2026-06-30",
                    "status": "success",
                    "restored_at": None,
                    "source_workflow": "wf",
                    "head_branch": "main",
                    "extra_field": "ignored",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("XCAGI_DEPLOY_EVENTS_PATH", str(path))
        data = ao.list_deploy_events(limit=5)
        item = data["items"][0]
        assert item == {
            "deploy_id": "x1",
            "deployed_at": "2026-07-01",
            "commit_at": "2026-06-30",
            "status": "success",
            "restored_at": None,
            "source_workflow": "wf",
            "head_branch": "main",
        }
        assert "extra_field" not in item


# ---------------------------------------------------------------------------
# operating_metrics_windows
# ---------------------------------------------------------------------------


class TestOperatingMetricsWindows:
    def test_recoverable_error_falls_back_to_error_report(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise(days: int) -> dict[str, Any]:
            raise OSError(f"boom-{days}")

        monkeypatch.setattr(
            "app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _raise
        )
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", "/nonexistent/path.jsonl")
        data = ao.operating_metrics_windows()
        assert data["windows"]["30"]["action_count"] == 0
        assert data["windows"]["30"]["veto_rate"] == 0.0
        assert data["windows"]["90"]["action_count"] == 0

    def test_veto_count_fallback_for_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reports = {
            30: {"veto_rate": 0.5, "total": 10, "veto_count": 4, "status": "ok"},
            90: {"veto_rate": 0.2, "total": 20, "veto_count": 2, "status": "ok"},
        }

        def _fake(days: int) -> dict[str, Any]:
            return reports[days]

        monkeypatch.setattr("app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _fake)
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", "/nonexistent/path.jsonl")
        data = ao.operating_metrics_windows()
        assert data["windows"]["30"]["blocked_count"] == 4
        assert data["windows"]["90"]["blocked_count"] == 2

    def test_blocked_count_fallback_when_no_veto_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        reports = {
            30: {"veto_rate": 0.5, "total": 10, "blocked_count": 7},
            90: {"veto_rate": 0.2, "total": 20, "blocked_count": 3},
        }

        def _fake(days: int) -> dict[str, Any]:
            return reports[days]

        monkeypatch.setattr("app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _fake)
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", "/nonexistent/path.jsonl")
        data = ao.operating_metrics_windows()
        assert data["windows"]["30"]["blocked_count"] == 7
        assert data["windows"]["90"]["blocked_count"] == 3

    def test_by_decision_blocked_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reports = {
            30: {"veto_rate": 0.5, "total": 10, "by_decision": {"blocked": 6}},
            90: {"veto_rate": 0.2, "total": 20, "by_decision": {"blocked": 8}},
        }

        def _fake(days: int) -> dict[str, Any]:
            return reports[days]

        monkeypatch.setattr("app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _fake)
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", "/nonexistent/path.jsonl")
        data = ao.operating_metrics_windows()
        assert data["windows"]["30"]["blocked_count"] == 6
        assert data["windows"]["90"]["blocked_count"] == 8

    def test_by_decision_BLOCKED_uppercase_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        reports = {
            30: {"veto_rate": 0.5, "total": 10, "by_decision": {"BLOCKED": 9}},
            90: {"veto_rate": 0.2, "total": 20, "by_decision": {"BLOCKED": 1}},
        }

        def _fake(days: int) -> dict[str, Any]:
            return reports[days]

        monkeypatch.setattr("app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _fake)
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", "/nonexistent/path.jsonl")
        data = ao.operating_metrics_windows()
        assert data["windows"]["30"]["blocked_count"] == 9
        assert data["windows"]["90"]["blocked_count"] == 1

    def test_trend_30_filters_only_window_30(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        metrics_path = tmp_path / "autonomy-metrics.jsonl"
        rows = [
            {
                "window_days": 30,
                "snapshot_date": "2026-07-01",
                "veto_rate": 0.1,
                "total": 5,
            },
            {
                "window_days": 90,
                "snapshot_date": "2026-07-01",
                "veto_rate": 0.2,
                "total": 10,
            },
            {
                "window_days": 30,
                "snapshot_date": "2026-07-02",
                "veto_rate": 0.3,
                "total": 8,
            },
        ]
        metrics_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(metrics_path))

        def _fake(days: int) -> dict[str, Any]:
            return {"veto_rate": 0.0, "total": 0}

        monkeypatch.setattr("app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _fake)
        data = ao.operating_metrics_windows()
        trend = data["veto_rate_trend_30d"]
        # history is read newest-first then reversed → chronological: 07-01, 07-02
        assert len(trend) == 2
        assert trend[0]["snapshot_date"] == "2026-07-01"
        assert trend[1]["snapshot_date"] == "2026-07-02"

    def test_trend_30_capped_at_30(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        metrics_path = tmp_path / "autonomy-metrics.jsonl"
        rows = [
            {
                "window_days": 30,
                "snapshot_date": f"2026-07-{n:02d}",
                "veto_rate": 0.1,
                "total": 1,
            }
            for n in range(1, 41)
        ]
        metrics_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_METRICS_LOG_PATH", str(metrics_path))

        def _fake(days: int) -> dict[str, Any]:
            return {"veto_rate": 0.0, "total": 0}

        monkeypatch.setattr("app.domain.autonomy.operating_metrics.evaluate_autonomy_window", _fake)
        data = ao.operating_metrics_windows()
        assert len(data["veto_rate_trend_30d"]) <= 30


# ---------------------------------------------------------------------------
# extract_loop_run_summary
# ---------------------------------------------------------------------------


class TestExtractLoopRunSummary:
    def test_none_returns_unknown(self) -> None:
        result = ao.extract_loop_run_summary(None)
        assert result["status"] == "unknown"
        assert result["run_id"] is None
        assert result["branch"] is None
        assert result["completed_at"] is None
        assert result["triggered_by"] is None

    def test_non_dict_input_returns_unknown(self) -> None:
        result = ao.extract_loop_run_summary(["not", "a", "dict"])  # type: ignore[arg-type]
        assert result["status"] == "unknown"
        assert result["run_id"] is None

    def test_empty_dict(self) -> None:
        result = ao.extract_loop_run_summary({})
        assert result["status"] == "unknown"

    def test_memory_not_dict_uses_timelines(self) -> None:
        result = ao.extract_loop_run_summary({"memory": "not a dict"})
        assert result["status"] == "unknown"

    def test_last_run_not_dict_uses_timelines(self) -> None:
        result = ao.extract_loop_run_summary({"memory": {"last_run": "nope"}})
        assert result["status"] == "unknown"

    def test_status_from_last_run(self) -> None:
        result = ao.extract_loop_run_summary(
            {"memory": {"last_run": {"status": "completed", "run_id": "r1", "branch": "b1"}}}
        )
        assert result["status"] == "completed"
        assert result["run_id"] == "r1"
        assert result["branch"] == "b1"

    def test_status_from_timeline_when_no_last_run_status(self) -> None:
        result = ao.extract_loop_run_summary(
            {"run_timelines": [{"status": "running", "run_id": "t1", "branch": "tb"}]}
        )
        assert result["status"] == "running"
        assert result["run_id"] == "t1"
        assert result["branch"] == "tb"

    def test_status_from_data_when_no_last_run_no_timeline(self) -> None:
        result = ao.extract_loop_run_summary({"status": "idle"})
        assert result["status"] == "idle"
        assert result["run_id"] is None

    def test_timelines_not_list_ignored(self) -> None:
        result = ao.extract_loop_run_summary({"run_timelines": "nope"})
        assert result["status"] == "unknown"

    def test_timelines_empty(self) -> None:
        result = ao.extract_loop_run_summary({"run_timelines": []})
        assert result["status"] == "unknown"

    def test_timelines_first_not_dict(self) -> None:
        result = ao.extract_loop_run_summary({"run_timelines": ["nope"]})
        assert result["status"] == "unknown"

    def test_last_run_status_takes_precedence_over_timeline(self) -> None:
        result = ao.extract_loop_run_summary(
            {
                "memory": {"last_run": {"status": "completed", "run_id": "r1"}},
                "run_timelines": [{"status": "running", "run_id": "t1"}],
            }
        )
        assert result["status"] == "completed"
        assert result["run_id"] == "r1"

    def test_run_id_falls_back_to_timeline(self) -> None:
        result = ao.extract_loop_run_summary(
            {"memory": {"last_run": {}}, "run_timelines": [{"run_id": "t1"}]}
        )
        assert result["run_id"] == "t1"

    def test_branch_falls_back_to_timeline(self) -> None:
        result = ao.extract_loop_run_summary(
            {"memory": {"last_run": {}}, "run_timelines": [{"branch": "tb"}]}
        )
        assert result["branch"] == "tb"

    def test_completed_at_only_from_last_run(self) -> None:
        result = ao.extract_loop_run_summary(
            {
                "memory": {"last_run": {"completed_at": "2026-07-01"}},
                "run_timelines": [{"completed_at": "ignored"}],
            }
        )
        assert result["completed_at"] == "2026-07-01"

    def test_triggered_by_only_from_last_run(self) -> None:
        result = ao.extract_loop_run_summary(
            {
                "memory": {"last_run": {"triggered_by": "ci"}},
                "run_timelines": [{"triggered_by": "ignored"}],
            }
        )
        assert result["triggered_by"] == "ci"


# ---------------------------------------------------------------------------
# closure_gap_count
# ---------------------------------------------------------------------------


class TestClosureGapCount:
    def test_none_returns_zero(self) -> None:
        assert ao.closure_gap_count(None) == 0

    def test_non_dict_returns_zero(self) -> None:
        assert ao.closure_gap_count(["nope"]) == 0  # type: ignore[arg-type]

    def test_empty_dict_returns_zero(self) -> None:
        assert ao.closure_gap_count({}) == 0

    def test_gap_count_key(self) -> None:
        assert ao.closure_gap_count({"gap_count": 5}) == 5

    def test_closure_gap_count_key(self) -> None:
        assert ao.closure_gap_count({"closure_gap_count": 3}) == 3

    def test_open_gap_count_key(self) -> None:
        assert ao.closure_gap_count({"open_gap_count": 7}) == 7

    def test_gap_count_none_value_returns_zero(self) -> None:
        assert ao.closure_gap_count({"gap_count": None}) == 0

    def test_gap_count_with_type_error_falls_through(self) -> None:
        # int(dict) raises TypeError → falls through to gaps/missing/rows
        payload = {"gap_count": {"nested": 1}, "gaps": [1, 2]}
        assert ao.closure_gap_count(payload) == 2

    def test_gap_count_with_value_error_falls_through(self) -> None:
        # int("abc") raises ValueError → falls through
        payload = {"gap_count": "abc", "gaps": [1, 2, 3]}
        assert ao.closure_gap_count(payload) == 3

    def test_data_wrapper_dict(self) -> None:
        assert ao.closure_gap_count({"data": {"gap_count": 9}}) == 9

    def test_data_wrapper_not_dict_uses_outer(self) -> None:
        assert ao.closure_gap_count({"data": "nope", "gap_count": 2}) == 2

    def test_gaps_list_length(self) -> None:
        assert ao.closure_gap_count({"gaps": [1, 2, 3]}) == 3

    def test_gaps_not_list_ignored(self) -> None:
        assert ao.closure_gap_count({"gaps": "not a list"}) == 0

    def test_missing_remote_list(self) -> None:
        assert ao.closure_gap_count({"missing_remote": ["a", "b"]}) == 2

    def test_missing_local_list_when_no_missing_remote(self) -> None:
        assert ao.closure_gap_count({"missing_local": ["a", "b", "c"]}) == 3

    def test_missing_remote_falsy_uses_missing_local(self) -> None:
        assert ao.closure_gap_count({"missing_remote": [], "missing_local": ["a"]}) == 1

    def test_missing_not_list_ignored(self) -> None:
        assert ao.closure_gap_count({"missing_remote": "nope"}) == 0

    def test_roster_rows_missing_remote(self) -> None:
        payload = {"roster_rows": [{"missing_remote": True}, {"missing_remote": False}]}
        assert ao.closure_gap_count(payload) == 1

    def test_roster_rows_missing_local(self) -> None:
        payload = {"roster_rows": [{"missing_local": True}, {"missing_local": False}]}
        assert ao.closure_gap_count(payload) == 1

    def test_roster_rows_gap_flag(self) -> None:
        payload = {"roster_rows": [{"gap": True}, {"gap": False}, {"gap": 1}]}
        assert ao.closure_gap_count(payload) == 2

    def test_roster_rows_status_gap(self) -> None:
        payload = {"roster_rows": [{"status": "gap"}, {"status": "ok"}]}
        assert ao.closure_gap_count(payload) == 1

    def test_roster_rows_status_missing(self) -> None:
        payload = {"roster_rows": [{"status": "missing"}, {"status": "ok"}]}
        assert ao.closure_gap_count(payload) == 1

    def test_roster_rows_status_chinese(self) -> None:
        payload = {"roster_rows": [{"status": "缺岗"}, {"status": "ok"}]}
        assert ao.closure_gap_count(payload) == 1

    def test_roster_rows_status_case_insensitive(self) -> None:
        payload = {"roster_rows": [{"status": "GAP"}, {"status": "MISSING"}]}
        assert ao.closure_gap_count(payload) == 2

    def test_roster_rows_non_dict_row_skipped(self) -> None:
        payload = {"roster_rows": ["not dict", {"status": "gap"}]}
        assert ao.closure_gap_count(payload) == 1

    def test_rows_key_alias(self) -> None:
        payload = {"rows": [{"status": "gap"}, {"status": "ok"}]}
        assert ao.closure_gap_count(payload) == 1

    def test_roster_rows_takes_precedence_over_rows(self) -> None:
        # roster_rows is checked first via `or`
        payload = {
            "roster_rows": [{"status": "gap"}],
            "rows": [{"status": "gap"}, {"status": "gap"}],
        }
        assert ao.closure_gap_count(payload) == 1

    def test_empty_roster_rows(self) -> None:
        assert ao.closure_gap_count({"roster_rows": []}) == 0


# ---------------------------------------------------------------------------
# list_github_human_items
# ---------------------------------------------------------------------------


def _make_proc(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


class TestListGithubHumanItems:
    def test_successful_prs_and_issues(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": 1,
                "title": "PR 1",
                "url": "https://example.com/pr/1",
                "labels": [{"name": "ai-self-heal"}, {"name": "needs-human"}],
                "updatedAt": "2026-07-02T00:00:00Z",
                "author": {"login": "alice"},
                "headRefName": "fix-1",
            }
        ]
        issues = [
            {
                "number": 2,
                "title": "Issue 2",
                "url": "https://example.com/issue/2",
                "labels": ["needs-human"],
                "updatedAt": "2026-07-01T00:00:00Z",
                "author": "bob",
            }
        ]
        calls: list[list[str]] = []

        def _fake_run(args, **kwargs):
            calls.append(args)
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout=json.dumps(issues))

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=30)
        assert data["count"] == 2
        # sorted by updated_at desc → PR 1 first
        assert data["items"][0]["kind"] == "pr"
        assert data["items"][0]["number"] == 1
        assert data["items"][0]["labels"] == ["ai-self-heal", "needs-human"]
        assert data["items"][0]["author"] == "alice"
        assert data["items"][0]["head_ref"] == "fix-1"
        assert data["items"][1]["kind"] == "issue"
        assert data["items"][1]["author"] == "bob"
        assert data["items"][1]["labels"] == ["needs-human"]
        assert "head_ref" not in data["items"][1]
        assert data["available"] is True
        assert data["errors"] == []

    def test_os_error_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            raise OSError("gh not found")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"] == []
        assert data["count"] == 0
        assert len(data["errors"]) == 2  # one for pr, one for issue
        assert data["available"] is False

    def test_timeout_error_recorded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args, timeout=45)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"] == []
        assert len(data["errors"]) == 2
        assert data["available"] is False

    def test_nonzero_returncode_with_stderr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            return _make_proc(stderr="gh auth error", returncode=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"] == []
        assert data["errors"] == ["gh auth error", "gh auth error"]

    def test_nonzero_returncode_with_stdout_no_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fake_run(args, **kwargs):
            return _make_proc(stdout="some warning", stderr="", returncode=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["errors"] == ["some warning", "some warning"]

    def test_nonzero_returncode_no_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            return _make_proc(stdout="", stderr="", returncode=2)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["errors"] == ["exit 2", "exit 2"]

    def test_json_decode_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            return _make_proc(stdout="not json")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"] == []
        assert all(e.startswith("json:") for e in data["errors"])

    def test_non_list_payload_treated_as_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            return _make_proc(stdout=json.dumps({"not": "a list"}))

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"] == []
        assert data["errors"] == []

    def test_empty_stdout_parsed_as_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run(args, **kwargs):
            return _make_proc(stdout="")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"] == []

    def test_author_string_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": 1,
                "title": "PR 1",
                "url": "u1",
                "labels": [],
                "updatedAt": "2026-07-01",
                "author": "string-author",
                "headRefName": "b1",
            }
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"][0]["author"] == "string-author"

    def test_author_none_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": 1,
                "title": "PR 1",
                "url": "u1",
                "labels": [],
                "updatedAt": "2026-07-01",
                "author": None,
                "headRefName": "b1",
            }
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"][0]["author"] is None

    def test_labels_mixed_dict_and_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": 1,
                "title": "PR 1",
                "url": "u1",
                "labels": [{"name": "label-a"}, "label-b", 42],
                "updatedAt": "2026-07-01",
                "author": None,
                "headRefName": "b1",
            }
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["items"][0]["labels"] == ["label-a", "label-b", "42"]

    def test_limit_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": n,
                "title": f"PR {n}",
                "url": f"u{n}",
                "labels": [],
                "updatedAt": f"2026-07-{n:02d}",
                "author": None,
                "headRefName": "b",
            }
            for n in range(1, 4)
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        # limit=-1 (negative) clamps to 1; limit=0 is falsy → defaults to 30
        data = ao.list_github_human_items(limit=-1)
        assert data["count"] == 1
        assert data["items"][0]["number"] == 3  # newest

    def test_limit_clamped_to_100(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": n,
                "title": f"PR {n}",
                "url": f"u{n}",
                "labels": [],
                "updatedAt": f"2026-07-{n:02d}",
                "author": None,
                "headRefName": "b",
            }
            for n in range(1, 5)
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=999)
        assert data["count"] == 4

    def test_limit_none_defaults_to_30(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": 1,
                "title": "PR 1",
                "url": "u1",
                "labels": [],
                "updatedAt": "2026-07-01",
                "author": None,
                "headRefName": "b",
            }
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=None)  # type: ignore[arg-type]
        assert data["count"] == 1

    def test_sorting_by_updated_at_desc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            {
                "number": 1,
                "title": "old",
                "url": "u1",
                "labels": [],
                "updatedAt": "2026-07-01",
                "author": None,
                "headRefName": "b",
            },
            {
                "number": 2,
                "title": "new",
                "url": "u2",
                "labels": [],
                "updatedAt": "2026-07-05",
                "author": None,
                "headRefName": "b",
            },
            {
                "number": 3,
                "title": "mid",
                "url": "u3",
                "labels": [],
                "updatedAt": "2026-07-03",
                "author": None,
                "headRefName": "b",
            },
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            return _make_proc(stdout="[]")

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        numbers = [item["number"] for item in data["items"]]
        assert numbers == [2, 3, 1]

    def test_available_true_when_items_exist_despite_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prs = [
            {
                "number": 1,
                "title": "PR 1",
                "url": "u1",
                "labels": [],
                "updatedAt": "2026-07-01",
                "author": None,
                "headRefName": "b",
            }
        ]

        def _fake_run(args, **kwargs):
            if "pr" in args:
                return _make_proc(stdout=json.dumps(prs))
            # issue call fails
            return _make_proc(stderr="issue error", returncode=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)
        data = ao.list_github_human_items(limit=10)
        assert data["count"] == 1
        assert len(data["errors"]) == 1
        assert data["available"] is True


# ---------------------------------------------------------------------------
# _load_cross_tier_check
# ---------------------------------------------------------------------------


class TestLoadCrossTierCheck:
    def test_loads_check_before_action(self) -> None:
        check = ao._load_cross_tier_check()
        assert callable(check)
        # verify it behaves like the real one
        result = check("desktop", "rollback_version", {"server_manifest_frozen": False})
        assert result.allow is True

    def test_exec_module_failure_removes_from_sys_modules(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Force exec_module to raise; ensure sys.modules entry is cleaned up
        original_module = sys.modules.get("xcagi_cross_tier_gate")

        bad_loader = MagicMock()
        bad_loader.exec_module.side_effect = RuntimeError("exec failed")

        bad_spec = MagicMock()
        bad_spec.loader = bad_loader

        monkeypatch.setattr(
            importlib.util,
            "spec_from_file_location",
            lambda name, path: bad_spec,
        )

        # Force a clean slate
        sys.modules.pop("xcagi_cross_tier_gate", None)

        with pytest.raises(RuntimeError, match="exec failed"):
            ao._load_cross_tier_check()

        assert "xcagi_cross_tier_gate" not in sys.modules

        # restore if it was there originally
        if original_module is not None:
            sys.modules["xcagi_cross_tier_gate"] = original_module


# ---------------------------------------------------------------------------
# evaluate_cross_tier_gate_snapshot
# ---------------------------------------------------------------------------


class TestEvaluateCrossTierGateSnapshot:
    def test_all_allow_when_state_clean(self) -> None:
        snap = ao.evaluate_cross_tier_gate_snapshot(
            {"server_manifest_frozen": False, "desktop_pending_rollback_marker": False}
        )
        assert snap["ok"] is True
        assert len(snap["rules"]) == 3
        assert all(r["allow"] for r in snap["rules"])
        assert all(r["reasons"] == [] for r in snap["rules"])

    def test_server_manifest_frozen_blocks_desktop_and_ci(self) -> None:
        snap = ao.evaluate_cross_tier_gate_snapshot(
            {"server_manifest_frozen": True, "desktop_pending_rollback_marker": False}
        )
        assert snap["ok"] is False
        # desktop rollback_version blocked, ci cvm-push-release blocked
        rules_by_tier = {r["tier"]: r for r in snap["rules"]}
        assert rules_by_tier["desktop"]["allow"] is False
        assert len(rules_by_tier["desktop"]["reasons"]) == 1
        assert rules_by_tier["ci"]["allow"] is False
        assert len(rules_by_tier["ci"]["reasons"]) == 1
        # server rollback is NOT blocked by frozen manifest
        assert rules_by_tier["server"]["allow"] is True

    def test_desktop_pending_marker_blocks_server(self) -> None:
        snap = ao.evaluate_cross_tier_gate_snapshot(
            {"server_manifest_frozen": False, "desktop_pending_rollback_marker": True}
        )
        assert snap["ok"] is False
        rules_by_tier = {r["tier"]: r for r in snap["rules"]}
        assert rules_by_tier["server"]["allow"] is False
        assert len(rules_by_tier["server"]["reasons"]) == 1
        # desktop and ci are fine
        assert rules_by_tier["desktop"]["allow"] is True
        assert rules_by_tier["ci"]["allow"] is True

    def test_remote_state_none_uses_default(self) -> None:
        # _default_remote_state should return both False on a clean dev box
        snap = ao.evaluate_cross_tier_gate_snapshot(None)
        assert snap["ok"] is True
        assert "remote_state" in snap
        assert "collected_at" in snap["remote_state"]

    def test_remote_state_non_dict_uses_default(self) -> None:
        snap = ao.evaluate_cross_tier_gate_snapshot(["not", "a", "dict"])  # type: ignore[arg-type]
        assert snap["ok"] is True
        assert "collected_at" in snap["remote_state"]

    def test_rules_labels(self) -> None:
        snap = ao.evaluate_cross_tier_gate_snapshot(
            {"server_manifest_frozen": False, "desktop_pending_rollback_marker": False}
        )
        labels = [r["label"] for r in snap["rules"]]
        assert "桌面回滚 ↔ 服务器 manifest 冻结" in labels
        assert "服务器回滚 ↔ 桌面 pending marker" in labels
        assert "CI 推送 ↔ 服务器 manifest 冻结" in labels

    def test_action_types(self) -> None:
        snap = ao.evaluate_cross_tier_gate_snapshot(
            {"server_manifest_frozen": False, "desktop_pending_rollback_marker": False}
        )
        actions = [r["action_type"] for r in snap["rules"]]
        assert actions == [
            "rollback_version",
            "rollback_to_last_tarball",
            "cvm-push-release",
        ]


# ---------------------------------------------------------------------------
# _default_remote_state
# ---------------------------------------------------------------------------


class TestDefaultRemoteState:
    def test_clean_state_returns_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Point XCAGI_FHD_RUNTIME_ROOT at a non-existent dir so no .frozen found
        monkeypatch.setenv("XCAGI_FHD_RUNTIME_ROOT", str(tmp_path / "nope"))
        state = ao._default_remote_state()
        assert state["server_manifest_frozen"] is False
        assert state["desktop_pending_rollback_marker"] is False
        assert "collected_at" in state

    def test_frozen_file_at_fhd_root(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # _FHD_ROOT/.frozen — create and clean up
        frozen_path = ao._FHD_ROOT / ".frozen"
        created = False
        if not frozen_path.exists():
            frozen_path.write_text("frozen", encoding="utf-8")
            created = True
        try:
            # Point runtime root elsewhere so only _FHD_ROOT/.frozen matches
            monkeypatch.setenv("XCAGI_FHD_RUNTIME_ROOT", str(tmp_path / "nope"))
            state = ao._default_remote_state()
            assert state["server_manifest_frozen"] is True
        finally:
            if created:
                frozen_path.unlink(missing_ok=True)

    def test_frozen_file_at_runtime_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        runtime_root = tmp_path / "rt"
        runtime_root.mkdir()
        (runtime_root / ".frozen").write_text("frozen", encoding="utf-8")
        monkeypatch.setenv("XCAGI_FHD_RUNTIME_ROOT", str(runtime_root))
        # Ensure _FHD_ROOT/.frozen doesn't exist (it shouldn't normally)
        state = ao._default_remote_state()
        assert state["server_manifest_frozen"] is True

    def test_pending_marker_at_fhd_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        marker_path = ao._FHD_ROOT / "desktop" / "autonomy" / "pending-rollback.marker"
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        created = False
        if not marker_path.exists():
            marker_path.write_text("pending", encoding="utf-8")
            created = True
        try:
            state = ao._default_remote_state()
            assert state["desktop_pending_rollback_marker"] is True
        finally:
            if created:
                marker_path.unlink(missing_ok=True)

    def test_os_error_on_frozen_check_handled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Force Path.exists to raise OSError for the frozen candidates
        original_exists = Path.exists

        call_count = {"n": 0}

        def _flaky_exists(self):
            call_count["n"] += 1
            # Only raise for the first 3 calls (the frozen candidates)
            if call_count["n"] <= 3:
                raise OSError("boom")
            return original_exists(self)

        monkeypatch.setattr(Path, "exists", _flaky_exists)
        state = ao._default_remote_state()
        # OSError caught → frozen stays False
        assert state["server_manifest_frozen"] is False


# ---------------------------------------------------------------------------
# read_cross_tier_audit
# ---------------------------------------------------------------------------


class TestReadCrossTierAudit:
    def test_tier_none_defaults_to_server(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # point server path to a tmp file so we don't read real /opt
        audit_path = tmp_path / "audit.jsonl"
        audit_path.write_text(json.dumps({"tier": "server", "ts": "t1"}) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier=None, limit=10)  # type: ignore[arg-type]
        assert data["tier"] == "server"
        assert data["count"] == 1
        assert data["exists"] is True

    def test_tier_empty_defaults_to_server(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        audit_path = tmp_path / "audit.jsonl"
        audit_path.write_text("", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="", limit=10)
        assert data["tier"] == "server"
        assert data["count"] == 0

    def test_tier_whitespace_and_case_normalized(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        audit_path = tmp_path / "audit.jsonl"
        audit_path.write_text(json.dumps({"i": 1}) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="  SERVER  ", limit=10)
        assert data["tier"] == "server"
        assert data["count"] == 1

    def test_desktop_tier_uses_home_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        audit_dir = home_dir / ".xcagi" / "autonomy"
        audit_dir.mkdir(parents=True)
        audit_path = audit_dir / "audit.jsonl"
        audit_path.write_text(json.dumps({"i": 1}) + "\n", encoding="utf-8")
        monkeypatch.setenv("HOME", str(home_dir))
        data = ao.read_cross_tier_audit(tier="desktop", limit=10)
        assert data["tier"] == "desktop"
        assert data["count"] == 1
        assert data["exists"] is True

    def test_ci_tier_uses_fhd_root_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        data = ao.read_cross_tier_audit(tier="ci", limit=10)
        assert data["tier"] == "ci"
        # path is under _FHD_ROOT/.trae/autonomy-ci/audit.jsonl
        assert str(ao._FHD_ROOT / ".trae" / "autonomy-ci" / "audit.jsonl") == data["path"]

    def test_unknown_tier_falls_back_to_server(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        audit_path = tmp_path / "audit.jsonl"
        audit_path.write_text(json.dumps({"i": 1}) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="unknown_tier", limit=10)
        assert data["tier"] == "unknown_tier"
        # path falls back to server path
        assert data["path"] == str(audit_path)

    def test_server_fallback_to_runtime_metrics_parent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Primary server path missing, fallback exists
        runtime_dir = tmp_path / "rt"
        runtime_dir.mkdir()
        autonomy_dir = runtime_dir.parent / "autonomy"
        autonomy_dir.mkdir()
        fallback_path = autonomy_dir / "audit.jsonl"
        fallback_path.write_text(json.dumps({"i": 99}) + "\n", encoding="utf-8")

        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "missing.jsonl"))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(runtime_dir))
        data = ao.read_cross_tier_audit(tier="server", limit=10)
        assert data["count"] == 1
        assert data["items"][0]["i"] == 99
        assert data["path"] == str(fallback_path)

    def test_limit_clamped_to_one(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        audit_path = tmp_path / "audit.jsonl"
        rows = [json.dumps({"i": n}) for n in range(5)]
        audit_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        # limit=-1 (negative) clamps to 1; limit=0 is falsy → defaults to 50
        data = ao.read_cross_tier_audit(tier="server", limit=-1)
        assert data["count"] == 1

    def test_limit_clamped_to_300(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        audit_path = tmp_path / "audit.jsonl"
        rows = [json.dumps({"i": n}) for n in range(3)]
        audit_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="server", limit=99999)
        assert data["count"] == 3

    def test_limit_none_defaults_to_50(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        audit_path = tmp_path / "audit.jsonl"
        rows = [json.dumps({"i": n}) for n in range(3)]
        audit_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="server", limit=None)  # type: ignore[arg-type]
        assert data["count"] == 3

    def test_missing_file_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(tmp_path / "missing.jsonl"))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="server", limit=10)
        assert data["count"] == 0
        assert data["exists"] is False
        assert data["items"] == []

    def test_reads_newest_first(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        audit_path = tmp_path / "audit.jsonl"
        rows = [json.dumps({"i": n}) for n in range(1, 4)]
        audit_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        monkeypatch.setenv("XCAGI_AUTONOMY_AUDIT_LOG_PATH", str(audit_path))
        monkeypatch.setenv("XCAGI_AUTONOMY_DATA_DIR", str(tmp_path / "nope"))
        data = ao.read_cross_tier_audit(tier="server", limit=10)
        assert [item["i"] for item in data["items"]] == [3, 2, 1]
