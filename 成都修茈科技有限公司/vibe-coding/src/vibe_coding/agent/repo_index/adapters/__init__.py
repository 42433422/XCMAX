"""Language adapters for :class:`RepoIndex`.

A :class:`LanguageAdapter` extracts symbols, imports, and references from a
single source file. Adapters are stateless and cheap to construct so the
builder can pick one per file based on extension.

Python ships in tree (:class:`vibe_coding.agent.repo_index.adapters.python.PythonLanguageAdapter`).
TypeScript / Vue stubs live in :mod:`._tree_sitter`; they raise
``NotImplementedError`` until the second-phase tree-sitter integration lands,
which keeps the public surface stable for downstream code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class ParsedFile:
    """Output of a :class:`LanguageAdapter`.parse call."""

    language: str
    symbols: list[Any] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    references: list[Any] = field(default_factory=list)
    parse_error: str = ""


@runtime_checkable
class LanguageAdapter(Protocol):
    """Minimum contract every language adapter must satisfy.

    Adapter implementations should be stateless: builders may instantiate one
    per file or share a single instance across the whole project. ``parse`` is
    expected to be tolerant — partial output (with ``parse_error`` populated)
    is preferred over raising.
    """

    @property
    def language(self) -> str:  # pragma: no cover - trivial
        ...

    @property
    def extensions(self) -> tuple[str, ...]:  # pragma: no cover - trivial
        ...

    def parse(self, *, path: str, source: str) -> ParsedFile:  # pragma: no cover - protocol
        ...


__all__ = ["LanguageAdapter", "ParsedFile"]
