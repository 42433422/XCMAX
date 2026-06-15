"""Filesystem walker that builds a :class:`RepoIndex` from a project root.

Design points:

- **Incremental.** When an existing index is passed in, files whose
  ``(size, sha1)`` match the index are skipped — typical re-runs touch only
  changed files.
- **Gitignore-aware.** A minimal ``.gitignore`` parser excludes the obvious
  noise (``.git``, ``__pycache__``, ``node_modules``, build artefacts) without
  pulling in the heavyweight ``pathspec`` dependency. Anything fancier should
  switch to ``pathspec`` via a follow-up.
- **Bounded.** Files larger than ``max_file_bytes`` (default 512 KiB) are
  recorded with their hash but not parsed, which keeps the index cheap on
  repositories that contain bundled assets.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .adapters import LanguageAdapter
from .adapters.python import PythonLanguageAdapter
from .adapters.typescript import TypeScriptLanguageAdapter
from .adapters.vue import VueLanguageAdapter
from .index import FileEntry, RepoIndex, Symbol, Reference

DEFAULT_MAX_FILE_BYTES = 512 * 1024
DEFAULT_INDEX_FILENAME = "repo_index.json"


def _default_adapters() -> list[LanguageAdapter]:
    """Return the language adapters wired by default.

    Python ships with the built-in ``ast`` parser; TypeScript / Vue use the
    regex-based fallbacks (no extra dependencies). Callers can pass their
    own list to ``build_index`` to override.
    """
    return [
        PythonLanguageAdapter(),
        TypeScriptLanguageAdapter(),
        VueLanguageAdapter(),
    ]

# Always-skip directory names — applied even before ``.gitignore`` lookup so
# we never wander into ``.git``-internal blobs.
_HARD_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".idea",
        ".vscode",
        ".cursor",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        "node_modules",
        "dist",
        "build",
        ".venv",
        "venv",
        "site-packages",
        "coverage",
        ".next",
        ".nuxt",
        ".turbo",
        "target",
    }
)


@dataclass(slots=True)
class BuildOptions:
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    extra_ignore_patterns: tuple[str, ...] = ()
    follow_symlinks: bool = False


def build_index(
    root: str | Path,
    *,
    adapters: Sequence[LanguageAdapter] | None = None,
    previous: RepoIndex | None = None,
    options: BuildOptions | None = None,
) -> RepoIndex:
    """Build (or refresh) a :class:`RepoIndex` over ``root``.

    Pass ``previous`` (typically loaded via :meth:`RepoIndex.load`) to do an
    incremental refresh. Pass ``adapters`` to override the default adapter set
    (``PythonLanguageAdapter`` ships in tree).
    """
    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise ValueError(f"repo root {root_path!r} is not a directory")

    opts = options or BuildOptions()
    adapter_list: list[LanguageAdapter] = list(adapters or _default_adapters())
    by_ext = _adapter_lookup(adapter_list)
    ignore = _GitignoreMatcher(root_path, extra_patterns=opts.extra_ignore_patterns)

    base_index = previous or RepoIndex(root=root_path)
    if base_index.root != root_path:
        # Don't trust an index built against a different root.
        base_index = RepoIndex(root=root_path)
    new_files: dict[str, FileEntry] = {}
    seen_paths: set[str] = set()

    for abs_path in _walk(root_path, ignore=ignore, follow_symlinks=opts.follow_symlinks):
        rel = _rel_posix(abs_path, root_path)
        seen_paths.add(rel)
        ext = abs_path.suffix.lower()
        adapter = by_ext.get(ext)
        if adapter is None:
            continue

        try:
            stat = abs_path.stat()
        except OSError:
            continue
        if stat.st_size > opts.max_file_bytes:
            entry = FileEntry(
                path=rel,
                language=adapter.language,
                sha1="",
                size=int(stat.st_size),
                line_count=0,
                parse_error=f"file_too_large:{stat.st_size}>{opts.max_file_bytes}",
            )
            new_files[rel] = entry
            continue

        try:
            data = abs_path.read_bytes()
        except OSError as exc:
            new_files[rel] = FileEntry(
                path=rel,
                language=adapter.language,
                sha1="",
                size=int(stat.st_size),
                line_count=0,
                parse_error=f"read_error:{type(exc).__name__}",
            )
            continue

        sha1 = hashlib.sha1(data).hexdigest()
        existing = base_index.files.get(rel)
        if (
            existing is not None
            and existing.sha1 == sha1
            and existing.size == int(stat.st_size)
            and existing.language == adapter.language
        ):
            new_files[rel] = existing
            continue

        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            new_files[rel] = FileEntry(
                path=rel,
                language=adapter.language,
                sha1=sha1,
                size=int(stat.st_size),
                line_count=0,
                parse_error="decode_error:utf-8",
            )
            continue

        parsed = adapter.parse(path=rel, source=text)
        symbols: list[Symbol] = [s for s in parsed.symbols if isinstance(s, Symbol)]
        references: list[Reference] = [r for r in parsed.references if isinstance(r, Reference)]
        new_files[rel] = FileEntry(
            path=rel,
            language=adapter.language,
            sha1=sha1,
            size=int(stat.st_size),
            line_count=text.count("\n") + (1 if text and not text.endswith("\n") else 0),
            symbols=symbols,
            imports=list(parsed.imports),
            references=references,
            parse_error=parsed.parse_error,
        )

    base_index.files = new_files
    base_index.languages = sorted({e.language for e in new_files.values()})
    return base_index


# ---------------------------------------------------------------------- walking


def _walk(root: Path, *, ignore: "_GitignoreMatcher", follow_symlinks: bool) -> Iterable[Path]:
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        entries.sort(key=lambda p: (p.is_file(), p.name))
        for entry in entries:
            if entry.name in _HARD_SKIP_DIRS:
                continue
            if entry.is_symlink() and not follow_symlinks:
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            rel = _rel_posix(entry, root)
            if ignore.match(rel, is_dir=is_dir):
                continue
            if is_dir:
                stack.append(entry)
            elif entry.is_file():
                yield entry


def _rel_posix(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = path.relative_to(root)
    return rel.as_posix()


def _adapter_lookup(adapters: Sequence[LanguageAdapter]) -> dict[str, LanguageAdapter]:
    out: dict[str, LanguageAdapter] = {}
    for adapter in adapters:
        for ext in adapter.extensions:
            out[ext.lower()] = adapter
    return out


# ------------------------------------------------------------------- gitignore


class _GitignoreMatcher:
    """Lightweight ``.gitignore`` matcher: literal globs + leading ``/`` anchors.

    Trade-offs vs. ``pathspec``: we don't support negation (``!``), nested
    ``.gitignore`` files, or character classes beyond what :func:`fnmatch`
    handles. Adequate for excluding noise; switch to ``pathspec`` if more
    fidelity is needed.
    """

    def __init__(self, root: Path, *, extra_patterns: tuple[str, ...] = ()) -> None:
        self.root = root
        self._patterns: list[tuple[str, bool, bool]] = []  # (pattern, anchored, dir_only)
        self._load(root / ".gitignore")
        for pattern in extra_patterns:
            self._add_pattern(pattern)

    def _load(self, path: Path) -> None:
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                # Negation not implemented — silently ignore so we don't
                # accidentally include something the user wanted excluded.
                continue
            self._add_pattern(line)

    def _add_pattern(self, line: str) -> None:
        anchored = False
        dir_only = False
        if line.endswith("/"):
            dir_only = True
            line = line.rstrip("/")
        if line.startswith("/"):
            anchored = True
            line = line.lstrip("/")
        self._patterns.append((line, anchored, dir_only))

    def match(self, rel_path: str, *, is_dir: bool) -> bool:
        if not self._patterns:
            return False
        parts = rel_path.split("/")
        for pattern, anchored, dir_only in self._patterns:
            if dir_only and not is_dir:
                continue
            if anchored:
                if fnmatch.fnmatchcase(rel_path, pattern):
                    return True
            else:
                if fnmatch.fnmatchcase(rel_path, pattern):
                    return True
                if any(fnmatch.fnmatchcase(part, pattern) for part in parts):
                    return True
                if "/" in pattern and fnmatch.fnmatchcase(rel_path, "*/" + pattern):
                    return True
        return False


__all__ = ["BuildOptions", "build_index"]
