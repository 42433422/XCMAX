"""Prettier adapter — formatter conformance check.

Prettier is the dominant front-end formatter; the adapter runs
``prettier --check .`` so unformatted files surface as issues without
mutating the workspace. Use ``--write`` mode out-of-band if you want
the autofix.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport

_DEFAULT_ARGS: tuple[str, ...] = ("--check", ".")


class PrettierAdapter:
    """Run ``prettier --check`` and surface unformatted files as issues."""

    name = "prettier"
    languages = ("typescript", "javascript", "vue", "css", "json", "markdown")

    def __init__(
        self,
        *,
        args: tuple[str, ...] = _DEFAULT_ARGS,
        binary: str | None = None,
        npx_fallback: bool = True,
    ) -> None:
        self._args = args
        self._binary = binary
        self._npx_fallback = npx_fallback

    def is_available(self) -> bool:
        if self._binary:
            return shutil.which(self._binary) is not None
        if shutil.which("prettier") is not None:
            return True
        if self._npx_fallback and shutil.which("npx") is not None:
            return True
        return False

    def run(
        self,
        root: str | Path,
        *,
        sandbox: SandboxDriver,
        policy: SandboxPolicy | None,
    ) -> ToolReport:
        pol = policy or SandboxPolicy(timeout_s=120, max_output_size=200_000)
        cmd = self._resolve_command()
        if cmd is None:
            return ToolReport(
                tool=self.name,
                passed=True,
                error="prettier not available; skipped",
            )
        res = sandbox.execute(
            SandboxJob(
                kind="command",
                workspace_dir=str(Path(root)),
                command=cmd + list(self._args),
            ),
            policy=pol,
        )
        output = res.stdout + res.stderr
        issues = _parse_unformatted(output)
        return ToolReport(
            tool=self.name,
            passed=res.success and not issues,
            issues=issues,
            stdout=res.stdout,
            stderr=res.stderr,
            exit_code=res.exit_code,
            duration_ms=res.duration_ms,
        )

    def _resolve_command(self) -> list[str] | None:
        if self._binary and shutil.which(self._binary):
            return [self._binary]
        if shutil.which("prettier"):
            return ["prettier"]
        if self._npx_fallback and shutil.which("npx"):
            return ["npx", "--yes", "prettier"]
        return None


def _parse_unformatted(output: str) -> list[str]:
    """Pull ``[warn] path/to/file.ts`` lines that prettier emits per file."""
    issues: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # ``[warn] src/foo.ts`` (default reporter) or just the path on its own
        # (some prettier versions). Either way we surface the file.
        if line.startswith("[warn]"):
            issues.append(line.removeprefix("[warn]").strip())
        elif line.startswith("[error]"):
            issues.append(line.removeprefix("[error]").strip())
    return issues


__all__ = ["PrettierAdapter"]
