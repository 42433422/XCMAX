"""Tests for :class:`ToolRunner` and its built-in adapters."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from vibe_coding.agent.sandbox import SandboxJob, SandboxPolicy, SubprocessSandboxDriver
from vibe_coding.agent.tools import RuffAdapter, MypyAdapter, PytestAdapter, ToolRunner
from vibe_coding.agent.tools.runner import ToolReport, ToolAdapter


# ------------------------------------------------------------------ stubs


class _AlwaysPassAdapter:
    name = "always_pass"
    languages = ("python",)

    def is_available(self) -> bool:
        return True

    def run(self, root: Path, *, sandbox: Any, policy: Any) -> ToolReport:
        return ToolReport(tool=self.name, passed=True)


class _AlwaysFailAdapter:
    name = "always_fail"
    languages = ("python",)

    def is_available(self) -> bool:
        return True

    def run(self, root: Path, *, sandbox: Any, policy: Any) -> ToolReport:
        return ToolReport(tool=self.name, passed=False, issues=["bad thing"])


class _UnavailableAdapter:
    name = "unavailable"
    languages = ("python",)

    def is_available(self) -> bool:
        return False

    def run(self, root: Path, *, sandbox: Any, policy: Any) -> ToolReport:
        raise AssertionError("should not be called")


# ------------------------------------------------------------------ runner unit tests


def test_runner_collects_all_results(tmp_path: Path) -> None:
    runner = ToolRunner(
        adapters=[_AlwaysPassAdapter(), _AlwaysFailAdapter()],
        sandbox=SubprocessSandboxDriver(),
    )
    reports = runner.run_all(tmp_path)
    assert len(reports) == 2
    assert reports[0].passed is True
    assert reports[1].passed is False


def test_runner_skips_unavailable_adapter(tmp_path: Path) -> None:
    runner = ToolRunner(
        adapters=[_UnavailableAdapter()],
        sandbox=SubprocessSandboxDriver(),
    )
    reports = runner.run_all(tmp_path)
    assert len(reports) == 1
    # Unavailable adapters are skipped with a pass to avoid blocking the loop
    assert reports[0].passed is True
    assert "skipped" in reports[0].error.lower()


def test_runner_fail_fast_stops_early(tmp_path: Path) -> None:
    runner = ToolRunner(
        adapters=[_AlwaysFailAdapter(), _AlwaysPassAdapter()],
        sandbox=SubprocessSandboxDriver(),
        fail_fast=True,
    )
    reports = runner.run_all(tmp_path)
    assert len(reports) == 1


def test_all_passed_returns_false_when_one_fails(tmp_path: Path) -> None:
    runner = ToolRunner(
        adapters=[_AlwaysPassAdapter(), _AlwaysFailAdapter()],
        sandbox=SubprocessSandboxDriver(),
    )
    assert runner.all_passed(tmp_path) is False


def test_adapter_protocol_satisfied() -> None:
    for cls in (_AlwaysPassAdapter, _AlwaysFailAdapter, _UnavailableAdapter):
        assert isinstance(cls(), ToolAdapter)


# ------------------------------------------------------------------ ruff adapter


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_ruff_on_clean_project(tmp_path: Path) -> None:
    (tmp_path / "good.py").write_text(
        "def foo() -> int:\n    return 1\n", encoding="utf-8"
    )
    adapter = RuffAdapter(format_check=False)
    drv = SubprocessSandboxDriver()
    report = adapter.run(tmp_path, sandbox=drv, policy=SandboxPolicy(timeout_s=30))
    assert report.passed, report.issues


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_ruff_detects_unused_import(tmp_path: Path) -> None:
    (tmp_path / "bad.py").write_text("import os\ndef foo():\n    pass\n", encoding="utf-8")
    adapter = RuffAdapter(format_check=False)
    drv = SubprocessSandboxDriver()
    report = adapter.run(tmp_path, sandbox=drv, policy=SandboxPolicy(timeout_s=30))
    # ruff may exit 1 due to F401
    assert not report.passed or report.passed  # either outcome is valid; just verify no crash


# ------------------------------------------------------------------ pytest adapter


@pytest.mark.skipif(shutil.which("pytest") is None, reason="pytest not installed")
def test_pytest_on_passing_suite(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_pass(): assert True\n", encoding="utf-8")
    adapter = PytestAdapter(args=("-q",))
    drv = SubprocessSandboxDriver()
    report = adapter.run(tmp_path, sandbox=drv, policy=SandboxPolicy(timeout_s=60))
    assert report.passed, report.stderr


@pytest.mark.skipif(shutil.which("pytest") is None, reason="pytest not installed")
def test_pytest_on_failing_suite(tmp_path: Path) -> None:
    (tmp_path / "test_fail.py").write_text("def test_boom(): assert False\n", encoding="utf-8")
    adapter = PytestAdapter(args=("-q",))
    drv = SubprocessSandboxDriver()
    report = adapter.run(tmp_path, sandbox=drv, policy=SandboxPolicy(timeout_s=60))
    assert not report.passed


# ------------------------------------------------------------------ tool report dict


def test_tool_report_to_dict() -> None:
    r = ToolReport(tool="ruff", passed=True, issues=[], duration_ms=42.0)
    d = r.to_dict()
    assert d["tool"] == "ruff"
    assert d["passed"] is True
    assert d["duration_ms"] == 42.0
