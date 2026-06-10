"""Pytest adapter — run the project's test suite."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport


class PytestAdapter:
    """Run ``pytest`` in the workspace root and parse the summary line."""

    name = "pytest"
    languages = ("python",)

    def __init__(
        self,
        *,
        args: tuple[str, ...] = ("-x", "--tb=short", "-q"),
    ) -> None:
        self._args = args

    def is_available(self) -> bool:
        return shutil.which("pytest") is not None

    def run(
        self,
        root: str | Path,
        *,
        sandbox: SandboxDriver,
        policy: SandboxPolicy | None,
    ) -> ToolReport:
        pol = policy or SandboxPolicy(timeout_s=300, max_output_size=500_000)
        res = sandbox.execute(
            SandboxJob(
                kind="command",
                workspace_dir=str(root),
                command=["pytest"] + list(self._args),
            ),
            policy=pol,
        )
        output = res.stdout + res.stderr
        issues = _parse_failures(output)
        return ToolReport(
            tool=self.name,
            passed=res.success,
            issues=issues,
            stdout=res.stdout,
            stderr=res.stderr,
            exit_code=res.exit_code,
            duration_ms=res.duration_ms,
        )


_FAILED_RE = re.compile(r"FAILED (.+?) -")


def _parse_failures(output: str) -> list[str]:
    failures: list[str] = []
    for line in (output or "").splitlines():
        m = _FAILED_RE.search(line)
        if m:
            failures.append(m.group(1).strip())
    return failures
