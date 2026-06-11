"""Tool runner: iterate adapters, collect reports, surface aggregated results."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence, runtime_checkable

from ..sandbox import SandboxDriver, SandboxJob, SandboxPolicy, SubprocessSandboxDriver


@dataclass(slots=True)
class ToolReport:
    """Outcome of running one tool against a workspace."""

    tool: str
    passed: bool
    issues: list[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0
    error: str = ""

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
    """Run a collection of :class:`ToolAdapter` instances sequentially.

    ``fail_fast=True`` stops after the first failing tool (default ``False``
    so all diagnostics are collected in one pass — useful for the
    ``heal_project`` loop that needs the full picture to compose a repair).
    """

    def __init__(
        self,
        adapters: Sequence[ToolAdapter] | None = None,
        *,
        sandbox: SandboxDriver | None = None,
        policy: SandboxPolicy | None = None,
        fail_fast: bool = False,
    ) -> None:
        self.adapters: list[ToolAdapter] = list(adapters or _default_adapters())
        self.sandbox: SandboxDriver = sandbox or SubprocessSandboxDriver()
        self.policy: SandboxPolicy | None = policy
        self.fail_fast = fail_fast

    def run_all(self, root: str | Path) -> list[ToolReport]:
        root = Path(root)
        reports: list[ToolReport] = []
        for adapter in self.adapters:
            if not adapter.is_available():
                reports.append(
                    ToolReport(
                        tool=adapter.name,
                        passed=True,
                        error=f"{adapter.name} not available; skipped",
                    )
                )
                continue
            t0 = time.perf_counter()
            try:
                report = adapter.run(root, sandbox=self.sandbox, policy=self.policy)
            except Exception as exc:  # noqa: BLE001
                report = ToolReport(
                    tool=adapter.name,
                    passed=False,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                )
            reports.append(report)
            if self.fail_fast and not report.passed:
                break
        return reports

    def all_passed(self, root: str | Path) -> bool:
        return all(r.passed for r in self.run_all(root))


def _default_adapters() -> list[ToolAdapter]:
    from .adapters.ruff import RuffAdapter
    from .adapters.mypy import MypyAdapter
    from .adapters.pytest import PytestAdapter

    return [RuffAdapter(), MypyAdapter(), PytestAdapter()]


__all__ = ["ToolAdapter", "ToolReport", "ToolRunner"]
