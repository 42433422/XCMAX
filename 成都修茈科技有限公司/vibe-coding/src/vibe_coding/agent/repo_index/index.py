"""Data model + persistence for :class:`RepoIndex`.

Designed to be **stable on disk**: the JSON layout is deterministic (sorted
keys, snake_case fields, paths normalised to POSIX) so repos can compare
indexes across machines without churn.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


@dataclass(slots=True)
class Symbol:
    """A named definition extracted from a source file.

    ``kind`` is intentionally open-ended so language adapters can use the
    natural vocabulary of the language (``"function"`` / ``"class"`` /
    ``"variable"`` for Python, ``"export"`` / ``"interface"`` / ``"component"``
    for TypeScript / Vue, ...).
    """

    name: str
    kind: str
    file: str
    start_line: int
    end_line: int
    signature: str = ""
    docstring: str = ""
    parent: str = ""
    exported: bool = True

    @property
    def qualified_name(self) -> str:
        return f"{self.parent}.{self.name}" if self.parent else self.name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Symbol:
        return cls(
            name=str(raw.get("name") or ""),
            kind=str(raw.get("kind") or ""),
            file=str(raw.get("file") or ""),
            start_line=int(raw.get("start_line") or 1),
            end_line=int(raw.get("end_line") or 1),
            signature=str(raw.get("signature") or ""),
            docstring=str(raw.get("docstring") or ""),
            parent=str(raw.get("parent") or ""),
            exported=bool(raw.get("exported", True)),
        )


@dataclass(slots=True)
class Reference:
    """A read-only mention of a symbol (function call, attribute, name load)."""

    name: str
    file: str
    line: int
    column: int = 0
    context: str = ""  # surrounding line for human-readable display

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Reference:
        return cls(
            name=str(raw.get("name") or ""),
            file=str(raw.get("file") or ""),
            line=int(raw.get("line") or 1),
            column=int(raw.get("column") or 0),
            context=str(raw.get("context") or ""),
        )


@dataclass(slots=True)
class FileEntry:
    """A single source file in the index."""

    path: str
    language: str
    sha1: str
    size: int
    line_count: int
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    parse_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "language": self.language,
            "sha1": self.sha1,
            "size": self.size,
            "line_count": self.line_count,
            "symbols": [s.to_dict() for s in self.symbols],
            "imports": list(self.imports),
            "references": [r.to_dict() for r in self.references],
            "parse_error": self.parse_error,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FileEntry:
        return cls(
            path=str(raw.get("path") or ""),
            language=str(raw.get("language") or ""),
            sha1=str(raw.get("sha1") or ""),
            size=int(raw.get("size") or 0),
            line_count=int(raw.get("line_count") or 0),
            symbols=[Symbol.from_dict(s) for s in raw.get("symbols") or [] if isinstance(s, dict)],
            imports=[str(x) for x in raw.get("imports") or []],
            references=[Reference.from_dict(r) for r in raw.get("references") or [] if isinstance(r, dict)],
            parse_error=str(raw.get("parse_error") or ""),
        )


@dataclass(slots=True)
class RepoIndex:
    """Project-wide, language-agnostic index.

    The ``files`` mapping uses POSIX-style paths *relative to the repo root* so
    the index is portable across operating systems. ``root`` is kept around
    only as a convenience for absolute-path resolution; it is **not** persisted.
    """

    root: Path
    files: dict[str, FileEntry] = field(default_factory=dict)
    languages: list[str] = field(default_factory=list)
    version: int = 1

    # ------------------------------------------------------------------ lookups

    def get_file(self, rel_path: str | Path) -> FileEntry | None:
        return self.files.get(_norm_rel(rel_path))

    def find_symbol(self, name: str) -> list[Symbol]:
        """Case-sensitive lookup by short name across the project."""
        out: list[Symbol] = []
        for entry in self.files.values():
            for sym in entry.symbols:
                if sym.name == name:
                    out.append(sym)
        return out

    def find_qualified(self, qualified: str) -> list[Symbol]:
        out: list[Symbol] = []
        for entry in self.files.values():
            for sym in entry.symbols:
                if sym.qualified_name == qualified:
                    out.append(sym)
        return out

    def references_to(self, name: str) -> list[Reference]:
        out: list[Reference] = []
        for entry in self.files.values():
            for ref in entry.references:
                if ref.name == name:
                    out.append(ref)
        return out

    def files_by_language(self, language: str) -> list[FileEntry]:
        return [e for e in self.files.values() if e.language == language]

    # ------------------------------------------------------------------ stats

    def summary(self) -> dict[str, Any]:
        by_lang: dict[str, int] = {}
        sym_total = 0
        for entry in self.files.values():
            by_lang[entry.language] = by_lang.get(entry.language, 0) + 1
            sym_total += len(entry.symbols)
        return {
            "files": len(self.files),
            "symbols": sym_total,
            "languages": dict(sorted(by_lang.items())),
            "version": self.version,
        }

    # ------------------------------------------------------------------ persist

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "languages": sorted(self.languages),
            "files": {p: e.to_dict() for p, e in sorted(self.files.items())},
        }

    @classmethod
    def from_dict(cls, root: str | Path, raw: dict[str, Any]) -> RepoIndex:
        files_raw = raw.get("files") or {}
        files = {
            str(p): FileEntry.from_dict(v)
            for p, v in files_raw.items()
            if isinstance(v, dict)
        }
        return cls(
            root=Path(root),
            files=files,
            languages=[str(x) for x in raw.get("languages") or []],
            version=int(raw.get("version") or 1),
        )

    def save(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return out

    @classmethod
    def load(cls, root: str | Path, path: str | Path) -> RepoIndex | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        return cls.from_dict(root, raw)

    def update_files(self, entries: Iterable[FileEntry]) -> None:
        for entry in entries:
            self.files[entry.path] = entry
        self.languages = sorted({e.language for e in self.files.values()})

    def remove_files(self, rel_paths: Iterable[str]) -> None:
        for rel in rel_paths:
            self.files.pop(_norm_rel(rel), None)
        self.languages = sorted({e.language for e in self.files.values()})


def _norm_rel(value: str | Path) -> str:
    """Normalise ``value`` to a POSIX-style relative path."""
    p = Path(value)
    return str(PurePosixPath(*p.parts))
