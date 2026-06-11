"""Tool integration: run linters, type checkers and test runners via the sandbox.

Entry points:

- :class:`ToolRunner` — orchestrates a list of :class:`ToolAdapter` instances,
  runs them all against a workspace, aggregates results.
- :class:`ToolReport` — the pass/fail outcome of a single tool run.
- :class:`ToolAdapter` — the Protocol every concrete tool must satisfy.
- Python adapters: :class:`RuffAdapter`, :class:`MypyAdapter`,
  :class:`PytestAdapter`.
- JS / TS / Vue adapters: :class:`ESLintAdapter`, :class:`TSCAdapter`,
  :class:`VitestAdapter`, :class:`PrettierAdapter`.

All adapters delegate execution to a :class:`SandboxDriver` so:

1. The tool runs in a subprocess (or Docker container) rather than inline.
2. Timeouts / memory caps from the driver's :class:`SandboxPolicy` apply.
3. Adding an adapter for eslint / tsc / vitest follows the same pattern.

Convenience factories :func:`default_python_adapters` /
:func:`default_javascript_adapters` / :func:`default_polyglot_adapters`
build curated lists for the most common project layouts.
"""

from __future__ import annotations

from .adapters.eslint import ESLintAdapter
from .adapters.mypy import MypyAdapter
from .adapters.prettier import PrettierAdapter
from .adapters.pytest import PytestAdapter
from .adapters.ruff import RuffAdapter
from .adapters.tsc import TSCAdapter
from .adapters.vitest import VitestAdapter
from .runner import ToolReport, ToolRunner


def default_python_adapters() -> list:
    """Curated default for Python projects (ruff + mypy + pytest)."""
    return [RuffAdapter(), MypyAdapter(), PytestAdapter()]


def default_javascript_adapters() -> list:
    """Curated default for JS/TS/Vue projects (eslint + tsc + vitest + prettier)."""
    return [ESLintAdapter(), TSCAdapter(), VitestAdapter(), PrettierAdapter()]


def default_polyglot_adapters() -> list:
    """Both stacks together. Each adapter self-skips when its tool is missing."""
    return default_python_adapters() + default_javascript_adapters()


__all__ = [
    "ESLintAdapter",
    "MypyAdapter",
    "PrettierAdapter",
    "PytestAdapter",
    "RuffAdapter",
    "TSCAdapter",
    "VitestAdapter",
    "ToolReport",
    "ToolRunner",
    "default_javascript_adapters",
    "default_polyglot_adapters",
    "default_python_adapters",
]
