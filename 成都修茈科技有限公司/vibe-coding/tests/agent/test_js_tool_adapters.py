"""Unit tests for the JS / TS / Vue tool adapters.

These tests don't depend on a real `eslint` / `tsc` / `vitest` install —
they wire a tiny stub :class:`SandboxDriver` so we can verify the
output-parsing logic deterministically. End-to-end tests (with the real
binaries) live behind `pytest.mark.integration` markers and are run by
the CI image that ships Node.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from vibe_coding.agent.sandbox import SandboxJob, SandboxPolicy, SandboxResult
from vibe_coding.agent.tools import (
    ESLintAdapter,
    PrettierAdapter,
    TSCAdapter,
    VitestAdapter,
    default_javascript_adapters,
    default_polyglot_adapters,
)


# ----------------------------------------------------- stub sandbox


class _StubDriver:
    name = "stub"

    def __init__(self, stdout: str = "", stderr: str = "", exit_code: int = 0) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._exit_code = exit_code
        self.last_job: SandboxJob | None = None

    def is_available(self) -> bool:
        return True

    def execute(
        self,
        job: SandboxJob,
        policy: SandboxPolicy | None = None,
    ) -> SandboxResult:
        self.last_job = job
        return SandboxResult(
            success=self._exit_code == 0,
            driver=self.name,
            stdout=self._stdout,
            stderr=self._stderr,
            exit_code=self._exit_code,
            duration_ms=1.0,
        )


# ----------------------------------------------------- eslint


def test_eslint_parses_compact_output(tmp_path: Path) -> None:
    out = (
        "/abs/src/foo.ts: line 12, col 3, Error - 'foo' is defined but never used. "
        "(no-unused-vars)\n"
        "/abs/src/foo.ts: line 14, col 1, Warning - prefer const. (prefer-const)\n"
    )
    drv = _StubDriver(stdout=out, exit_code=1)
    adapter = ESLintAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is False
    assert any("no-unused-vars" in issue for issue in report.issues)
    assert any("prefer-const" in issue for issue in report.issues)


def test_eslint_passes_on_empty_output(tmp_path: Path) -> None:
    drv = _StubDriver(stdout="", exit_code=0)
    adapter = ESLintAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is True
    assert report.issues == []


def test_eslint_skips_when_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adapter should self-skip with a `skipped` error when no binary exists."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    adapter = ESLintAdapter(npx_fallback=False)
    drv = _StubDriver()
    report = adapter.run(tmp_path, sandbox=drv, policy=None)
    assert report.passed is True
    assert "skipped" in report.error.lower()


# ----------------------------------------------------- tsc


def test_tsc_parses_diagnostics(tmp_path: Path) -> None:
    out = (
        "src/foo.ts(12,5): error TS2304: Cannot find name 'bar'.\n"
        "src/foo.ts(13,1): error TS1005: ';' expected.\n"
    )
    drv = _StubDriver(stdout=out, exit_code=1)
    adapter = TSCAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is False
    assert any("TS2304" in issue for issue in report.issues)
    assert any("TS1005" in issue for issue in report.issues)


def test_tsc_passes_on_clean_run(tmp_path: Path) -> None:
    drv = _StubDriver(stdout="", exit_code=0)
    adapter = TSCAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is True


# ----------------------------------------------------- vitest


def test_vitest_parses_failures(tmp_path: Path) -> None:
    out = (
        "FAIL src/foo.test.ts > foo > rejects bad input\n"
        "FAIL src/bar.test.ts > bar\n"
        "PASS src/baz.test.ts\n"
    )
    drv = _StubDriver(stdout=out, exit_code=1)
    adapter = VitestAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is False
    # Both files appear, deduplicated.
    issues = report.issues
    assert any("foo.test.ts" in i for i in issues)
    assert any("bar.test.ts" in i for i in issues)


def test_vitest_passes_on_clean_run(tmp_path: Path) -> None:
    drv = _StubDriver(
        stdout="Test Files  3 passed (3)\nTests  12 passed (12)\n",
        exit_code=0,
    )
    adapter = VitestAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is True


# ----------------------------------------------------- prettier


def test_prettier_parses_unformatted(tmp_path: Path) -> None:
    out = (
        "Checking formatting...\n"
        "[warn] src/foo.ts\n"
        "[warn] src/bar.vue\n"
        "[warn] Code style issues found in 2 files. Forgot to run Prettier?\n"
    )
    drv = _StubDriver(stdout=out, exit_code=1)
    adapter = PrettierAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is False
    assert any("foo.ts" in i for i in report.issues)
    assert any("bar.vue" in i for i in report.issues)


def test_prettier_passes_when_clean(tmp_path: Path) -> None:
    drv = _StubDriver(stdout="All matched files use Prettier code style!\n", exit_code=0)
    adapter = PrettierAdapter()
    report = _run_with_force_available(adapter, tmp_path, drv)
    assert report.passed is True


# ----------------------------------------------------- defaults


def test_default_javascript_adapters_includes_all_four() -> None:
    names = {a.name for a in default_javascript_adapters()}
    assert {"eslint", "tsc", "vitest", "prettier"} <= names


def test_default_polyglot_adapters_includes_python_and_js() -> None:
    names = {a.name for a in default_polyglot_adapters()}
    assert {"ruff", "mypy", "pytest", "eslint", "tsc", "vitest", "prettier"} <= names


# ----------------------------------------------------- helpers


def _run_with_force_available(
    adapter: Any,
    root: Path,
    drv: Any,
) -> Any:
    """Bypass ``is_available`` so the stub sandbox can drive output parsing.

    Each adapter resolves its command via ``_resolve_command`` which does
    its own ``shutil.which`` lookup. We monkey-patch that on the
    instance so the adapter returns a synthetic command and the stub
    sandbox records what it would have run.
    """
    adapter._resolve_command = lambda: ["fake-binary"]  # type: ignore[attr-defined]
    return adapter.run(root, sandbox=drv, policy=None)
