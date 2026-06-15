"""TypeScript compiler (``tsc``) adapter — type checking via ``--noEmit``.

We never want to *build* during validation; ``--noEmit`` runs the type
checker and exits with a non-zero status when there are errors but
without producing JS output that would clutter the workspace. Most
projects use a ``tsconfig.json`` at the workspace root which ``tsc``
picks up automatically.

For monorepos that use TypeScript project references, pass ``--build`` /
``-b`` via the ``args`` constructor parameter.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport

_DEFAULT_ARGS: tuple[str, ...] = ("--noEmit", "--pretty", "false")


class TSCAdapter:
    """Run TypeScript ``tsc`` against the workspace and surface diagnostics."""

    name = "tsc"
    languages = ("typescript", "vue")

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
        if shutil.which("tsc") is not None:
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
        pol = policy or SandboxPolicy(timeout_s=180, max_output_size=300_000)
        cmd = self._resolve_command()
        if cmd is None:
            return ToolReport(
                tool=self.name,
                passed=True,
                error="tsc not available; skipped",
            )
        res = sandbox.execute(
            SandboxJob(
                kind="command",
                workspace_dir=str(Path(root)),
                command=cmd + list(self._args),
            ),
            policy=pol,
        )
        issues = _parse_tsc_diagnostics(res.stdout + res.stderr)
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
        if shutil.which("tsc"):
            return ["tsc"]
        if self._npx_fallback and shutil.which("npx"):
            return ["npx", "--yes", "tsc"]
        return None


# tsc emits diagnostics like:
#   src/foo.ts(12,5): error TS2304: Cannot find name 'bar'.
_DIAG_RE = re.compile(
    r"^(?P<file>[^()]+)\((?P<line>\d+),(?P<col>\d+)\):\s*"
    r"(?P<sev>error|warning)\s+(?P<code>TS\d+):\s*(?P<msg>.+)$"
)


def _parse_tsc_diagnostics(output: str) -> list[str]:
    issues: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _DIAG_RE.match(line)
        if not m:
            continue
        issues.append(
            f"{m.group('file')}:{m.group('line')}:{m.group('col')} "
            f"{m.group('sev')} {m.group('code')} {m.group('msg').strip()}"
        )
    return issues


__all__ = ["TSCAdapter"]
