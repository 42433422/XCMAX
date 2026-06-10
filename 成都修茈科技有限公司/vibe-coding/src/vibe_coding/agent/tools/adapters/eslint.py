"""ESLint adapter — JS / TS / Vue lint via the sandbox driver.

ESLint is the de-facto front-end linter and the natural counterpart to
:class:`RuffAdapter` for Python. The adapter looks for ``eslint`` on the
``PATH``, then falls back to ``npx eslint`` when the binary isn't directly
installed but the project ships ``node_modules`` — that pattern matches
how most JS/TS projects ship their lint config.

Output parsing keys off ESLint's ``--format=compact`` mode which yields
``<file>: line <n>, col <c>, <severity> - <message> (<rule>)`` so we can
pick out one issue per line without depending on JSON parsers (we already
have a tolerant JSON parser, but staying line-based keeps memory bounded
on huge monorepos).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport

_DEFAULT_ARGS: tuple[str, ...] = (
    ".",
    "--format=compact",
    "--no-error-on-unmatched-pattern",
)


class ESLintAdapter:
    """Run ``eslint`` against a workspace; parse the compact-format output."""

    name = "eslint"
    languages = ("typescript", "javascript", "vue")

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
        if shutil.which("eslint") is not None:
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
                error="eslint not available; skipped",
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
        issues = _parse_eslint_compact(output)
        # ESLint exits 0 with zero issues, 1 with lint problems, 2 with
        # tooling errors. The runner's ``passed`` is an alias for "no
        # issues" so we treat anything but exit 0 as a failure but still
        # report exit_code so callers can disambiguate.
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
        if shutil.which("eslint"):
            return ["eslint"]
        if self._npx_fallback and shutil.which("npx"):
            return ["npx", "--yes", "eslint"]
        return None


# ESLint compact format example:
#   /abs/file.ts: line 12, col 3, Error - 'foo' is defined but never used.
#   (no-unused-vars)
_COMPACT_RE = re.compile(
    r"^(?P<file>[^:]+):\s*line\s*(?P<line>\d+),\s*col\s*(?P<col>\d+),\s*"
    r"(?P<sev>Error|Warning)\s*-\s*(?P<msg>.+?)(?:\s*\((?P<rule>[^)]+)\))?$"
)


def _parse_eslint_compact(output: str) -> list[str]:
    issues: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _COMPACT_RE.match(line)
        if not m:
            continue
        # We deliberately keep the rule id when present — the heal loop's
        # repair prompt needs it to ask the LLM to address a specific rule.
        rule = f" [{m.group('rule')}]" if m.group("rule") else ""
        issues.append(
            f"{m.group('file')}:{m.group('line')}:{m.group('col')} "
            f"{m.group('sev').lower()} {m.group('msg').strip()}{rule}"
        )
    return issues


__all__ = ["ESLintAdapter"]
