"""Mypy adapter — static type checking."""

from __future__ import annotations

import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport


class MypyAdapter:
    """Run ``mypy`` on the workspace root."""

    name = "mypy"
    languages = ("python",)

    def __init__(
        self,
        *,
        args: tuple[str, ...] = (".", "--ignore-missing-imports", "--no-error-summary"),
    ) -> None:
        self._args = args

    def is_available(self) -> bool:
        return shutil.which("mypy") is not None

    def run(
        self,
        root: str | Path,
        *,
        sandbox: SandboxDriver,
        policy: SandboxPolicy | None,
    ) -> ToolReport:
        pol = policy or SandboxPolicy(timeout_s=120, max_output_size=200_000)
        res = sandbox.execute(
            SandboxJob(
                kind="command",
                workspace_dir=str(root),
                command=["mypy"] + list(self._args),
            ),
            policy=pol,
        )
        output = res.stdout + res.stderr
        issues = [l.strip() for l in output.splitlines() if l.strip() and ": error:" in l]
        return ToolReport(
            tool=self.name,
            passed=res.success,
            issues=issues,
            stdout=res.stdout,
            stderr=res.stderr,
            exit_code=res.exit_code,
            duration_ms=res.duration_ms,
        )
