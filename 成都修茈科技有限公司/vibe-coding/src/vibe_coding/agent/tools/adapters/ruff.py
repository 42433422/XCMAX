"""Ruff adapter — lint + format check."""

from __future__ import annotations

import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport


class RuffAdapter:
    """Run ``ruff check`` (and optionally ``ruff format --check``) via the sandbox."""

    name = "ruff"
    languages = ("python",)

    def __init__(
        self,
        *,
        args: tuple[str, ...] = ("check", "--output-format=concise", "."),
        format_check: bool = True,
    ) -> None:
        self._args = args
        self._format_check = format_check

    def is_available(self) -> bool:
        return shutil.which("ruff") is not None

    def run(
        self,
        root: str | Path,
        *,
        sandbox: SandboxDriver,
        policy: SandboxPolicy | None,
    ) -> ToolReport:
        pol = policy or SandboxPolicy(timeout_s=60, max_output_size=100_000)
        root = Path(root)

        lint_res = sandbox.execute(
            SandboxJob(
                kind="command",
                workspace_dir=str(root),
                command=["ruff"] + list(self._args),
            ),
            policy=pol,
        )
        issues = _parse_ruff(lint_res.stdout + lint_res.stderr)
        passed = lint_res.success

        if self._format_check and passed:
            fmt_res = sandbox.execute(
                SandboxJob(
                    kind="command",
                    workspace_dir=str(root),
                    command=["ruff", "format", "--check", "."],
                ),
                policy=pol,
            )
            if not fmt_res.success:
                issues.extend(_parse_ruff(fmt_res.stdout + fmt_res.stderr))
                passed = False

        return ToolReport(
            tool=self.name,
            passed=passed,
            issues=issues,
            stdout=lint_res.stdout,
            stderr=lint_res.stderr,
            exit_code=lint_res.exit_code,
            duration_ms=lint_res.duration_ms,
        )


def _parse_ruff(output: str) -> list[str]:
    issues: list[str] = []
    for line in (output or "").splitlines():
        line = line.strip()
        if line and not line.startswith("Found") and "error" not in line.lower()[:6]:
            continue
        if line:
            issues.append(line)
    return issues
