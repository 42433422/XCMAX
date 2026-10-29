"""Tool runner: iterate adapters, collect reports, surface aggregated results."""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from vibe_coding.operational_errors import BOUNDARY_ERRORS

if TYPE_CHECKING:
    from ..sandbox import SandboxDriver, SandboxPolicy


@dataclass(slots=True)
class ToolReport:
    """Outcome of running one tool against a workspace.

    An unavailable tool is not an executed failure and must never be a pass.
    Keep ``passed`` for existing consumers, with an explicit execution state.
    """

    tool: str
    passed: bool
    issues: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    error: str = ""
    executed: bool = True

    def __post_init__(self) -> None:
        if not self.executed:
            self.passed = False

    @property
    def status(self) -> str:
        if not self.executed:
            return "UNAVAILABLE"
        return "PASS" if self.passed else "FAIL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "passed": self.passed,
            "issues": list(self.issues),
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "executed": self.executed,
            "status": self.status,
        }


@runtime_checkable
class ToolAdapter(Protocol):
    """Minimum contract every tool adapter must satisfy."""

    @property
    def name(self) -> str: ...

    @property
    def languages(self) -> tuple[str, ...]: ...

    def is_available(self) -> bool: ...

    def run(
        self,
        root: str | Path,
        *,
        sandbox: SandboxDriver,
        policy: SandboxPolicy | None,
    ) -> ToolReport: ...


class ToolRunner:
    """Run configured verification tools; none may silently count as passed.

    ``fail_fast=True`` stops after the first failure or unavailable tool.
    """

    def __init__(
        self,
        adapters: Sequence[ToolAdapter] | None = None,
        *,
        sandbox: SandboxDriver | None = None,
        policy: SandboxPolicy | None = None,
        fail_fast: bool = False,
    ) -> None:
        self.adapters: list[ToolAdapter] = list(
            _default_adapters() if adapters is None else adapters
        )
        if sandbox is None:
            from ..sandbox import SubprocessSandboxDriver

            sandbox = SubprocessSandboxDriver()
        self.sandbox: SandboxDriver = sandbox
        self.policy: SandboxPolicy | None = policy
        self.fail_fast = fail_fast

    def run_all(self, root: str | Path) -> list[ToolReport]:
        root = Path(root)
        reports: list[ToolReport] = []
        if not self.adapters:
            return [ToolReport(
                tool="verification", passed=False, executed=False, exit_code=-1,
                error="no verification adapters configured",
            )]
        for adapter in self.adapters:
            t0 = time.perf_counter()
            executed = False
            try:
                if not adapter.is_available():
                    report = ToolReport(
                        tool=adapter.name,
                        passed=False,
                        executed=False,
                        exit_code=-1,
                        error=f"{adapter.name} not available; verification not executed",
                    )
                else:
                    executed = True
                    report = adapter.run(root, sandbox=self.sandbox, policy=self.policy)
            except BOUNDARY_ERRORS as exc:
                report = ToolReport(
                    tool=adapter.name,
                    passed=False,
                    executed=executed,
                    exit_code=-1,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                )
            # A custom adapter cannot turn an explicit non-execution into pass.
            if not report.executed:
                report.passed = False
            reports.append(report)
            if self.fail_fast and not report.passed:
                break
        return reports

    def all_passed(self, root: str | Path) -> bool:
        reports = self.run_all(root)
        return bool(reports) and all(r.executed and r.passed for r in reports)


def _default_adapters() -> list[ToolAdapter]:
    from .adapters.mypy import MypyAdapter
    from .adapters.pytest import PytestAdapter
    from .adapters.ruff import RuffAdapter

    return [RuffAdapter(), MypyAdapter(), PytestAdapter()]


__all__ = ["ToolAdapter", "ToolReport", "ToolRunner"]
