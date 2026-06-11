"""Vitest adapter — run a JS/TS test suite via the sandbox driver.

Vitest mirrors pytest's role on the front-end side. The adapter prefers
``vitest`` directly on ``PATH`` (typical when ``node_modules/.bin`` is
exported) and falls back to ``npx vitest`` when only Node is installed.

We always pass ``run`` so vitest doesn't enter watch mode, and
``--reporter=default`` so the failure-summary parser doesn't have to
deal with TTY escape codes. The parser pulls the per-test ``FAIL`` lines
out of the output so the heal loop's repair prompt can target the
specific failing test.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from ...sandbox import SandboxDriver, SandboxJob, SandboxPolicy
from ..runner import ToolReport

_DEFAULT_ARGS: tuple[str, ...] = ("run", "--reporter=default", "--passWithNoTests")


class VitestAdapter:
    """Run ``vitest run`` and parse its summary into a :class:`ToolReport`."""

    name = "vitest"
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
        if shutil.which("vitest") is not None:
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
        pol = policy or SandboxPolicy(timeout_s=600, max_output_size=1_000_000)
        cmd = self._resolve_command()
        if cmd is None:
            return ToolReport(
                tool=self.name,
                passed=True,
                error="vitest not available; skipped",
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

    def _resolve_command(self) -> list[str] | None:
        if self._binary and shutil.which(self._binary):
            return [self._binary]
        if shutil.which("vitest"):
            return ["vitest"]
        if self._npx_fallback and shutil.which("npx"):
            return ["npx", "--yes", "vitest"]
        return None


# Vitest default reporter prefixes failing tests with ``FAIL`` (or ``×``
# in the per-suite breakdown). We match both because some Node TTYs strip
# the unicode glyph in CI.
_FAIL_RE = re.compile(r"^\s*(?:FAIL|×)\s+(?P<file>\S+)\s*[›>]?\s*(?P<name>.*)$")
_FAILED_TEST_RE = re.compile(r"FAILED\s+(.+)")


def _parse_failures(output: str) -> list[str]:
    failures: list[str] = []
    for raw in (output or "").splitlines():
        line = raw.rstrip()
        if not line:
            continue
        m = _FAIL_RE.match(line)
        if m:
            failures.append(f"{m.group('file')} :: {m.group('name').strip() or 'failed'}")
            continue
        m2 = _FAILED_TEST_RE.search(line)
        if m2:
            failures.append(m2.group(1).strip())
    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for f in failures:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    return deduped


__all__ = ["VitestAdapter"]
