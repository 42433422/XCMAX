from __future__ import annotations

from pathlib import Path

from retort_engine.quality_metrics import (
    code_line_count,
    is_behavior_test_file,
    is_generated_absorption_file,
    is_project_behavior_source_file,
    latest_absorption_change_health,
    project_files,
    project_relative,
    test_code_health as build_test_code_health,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_code_line_count_ignores_blank_python_and_js_comments(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    _write(
        path,
        """
# ignored

value = 1
// ignored when present in mixed snippets
def run():
    return value
""",
    )

    assert code_line_count(path) == 3


def test_generated_absorption_files_are_excluded() -> None:
    assert is_generated_absorption_file("docs/retort_external_review_report.json") is True
    assert is_generated_absorption_file("docs/retort_code_graph_proof_abc.json") is True
    assert is_generated_absorption_file("retort_engine/absorbed_capabilities.py") is True
    assert is_generated_absorption_file(".retort/cache/github/repo/file.py") is True
    assert is_generated_absorption_file("retort_engine/core.py") is False


def test_behavior_source_and_test_classification() -> None:
    assert is_behavior_test_file("tests/test_core.py") is True
    assert is_behavior_test_file("retort_engine/test_core.py") is True
    assert is_behavior_test_file("retort_engine/core.py") is False
    assert is_project_behavior_source_file("retort_engine/core.py") is True
    assert is_project_behavior_source_file("tests/test_core.py") is False
    assert is_project_behavior_source_file("docs/retort_external_review_report.json") is False


def test_project_files_skip_cache_and_virtualenv(tmp_path: Path) -> None:
    _write(tmp_path / "retort_engine" / "core.py", "x = 1\n")
    _write(tmp_path / ".retort" / "cache" / "skip.py", "x = 1\n")
    _write(tmp_path / ".venv" / "lib" / "skip.py", "x = 1\n")
    _write(tmp_path / "node_modules" / "skip.js", "x = 1\n")

    rels = {project_relative(tmp_path, path) for path in project_files(tmp_path, {".retort", ".venv", "node_modules"})}

    assert rels == {"retort_engine/core.py"}


def test_test_code_health_reports_global_and_latest_ratios(tmp_path: Path) -> None:
    _write(tmp_path / "retort_engine" / "core.py", "a = 1\nb = 2\nc = 3\n")
    _write(tmp_path / "tests" / "test_core.py", "def test_a():\n    assert True\n")
    _write(tmp_path / "docs" / "retort_external_review_report.json", "{}\n")

    health = build_test_code_health(
        tmp_path,
        latest={"changed_files": [str(tmp_path / "retort_engine" / "core.py"), str(tmp_path / "tests" / "test_core.py")]},
    )

    assert health["source_file_count"] == 1
    assert health["test_file_count"] == 1
    assert health["source_line_count"] == 3
    assert health["test_line_count"] == 2
    assert health["test_to_source_ratio"] == 0.667
    assert health["test_to_source_ratio_status"] == "healthy"
    assert health["latest_test_to_source_ratio"] == 0.667
    assert health["latest_test_to_source_ratio_status"] == "healthy"


def test_latest_absorption_change_health_splits_source_test_and_other(tmp_path: Path) -> None:
    source = tmp_path / "retort_engine" / "core.py"
    test = tmp_path / "tests" / "test_core.py"
    report = tmp_path / "docs" / "retort_external_review_report.json"
    missing = tmp_path / "missing.py"
    _write(source, "a = 1\nb = 2\n")
    _write(test, "def test_a():\n    assert True\n")
    _write(report, "{}\n")

    health = latest_absorption_change_health(tmp_path, {"changed_files": [str(source), str(test), str(report), str(missing)]})

    assert health["latest_changed_file_count"] == 4
    assert health["latest_changed_source_file_count"] == 1
    assert health["latest_changed_test_file_count"] == 1
    assert health["latest_changed_other_file_count"] == 2
    assert health["latest_test_to_source_ratio"] == 1.0


def test_project_relative_keeps_external_paths_readable(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-retort-file.py"

    assert project_relative(tmp_path, outside).endswith("outside-retort-file.py")
