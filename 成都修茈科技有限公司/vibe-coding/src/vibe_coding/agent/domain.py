"""Project-level domain guard for :class:`ProjectPatch`.

The single-skill flow already has a domain guard
(:meth:`vibe_coding.runtime.runtime.CodeSkillRuntime._is_within_domain`)
that rejects inputs whose JSON doesn't mention any of the skill's
``domain_keywords``. The project agent has no equivalent — an LLM that
gets a vague brief like "add logging" can happily rewrite half the
codebase before any guard rail kicks in.

:class:`ProjectDomainGuard` is the equivalent for project-scope edits.
Configure it once on the :class:`ProjectVibeCoder` (or pass it
per-call to :meth:`apply_patch`) and it will reject patches that:

- Touch paths outside ``allowed_paths`` (glob list).
- Touch any path matching ``forbidden_paths`` (glob list).
- Add modules listed in ``forbidden_imports`` to any modified file.
- Exceed ``max_files_changed`` files.
- Exceed ``max_lines_added`` net lines added.
- Match any custom ``custom_predicates`` callable returning a non-empty
  reason string.

The guard returns a :class:`DomainViolation` list — empty list means
"approved". Callers decide whether to abort, repair, or downgrade. The
default :class:`ProjectVibeCoder.apply_patch` integration treats any
violation as a hard block and surfaces them in the apply result.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from .patch import ProjectPatch

# Common forbidden imports that almost never belong in a "small refactor"
# patch. Customisable via the constructor.
DEFAULT_FORBIDDEN_IMPORTS: tuple[str, ...] = (
    "os.system",
    "subprocess",
    "ctypes",
    "socket",
)

PatchPredicate = Callable[["ProjectPatch"], str]


@dataclass(slots=True)
class DomainViolation:
    """One reason the patch was rejected."""

    code: str
    message: str
    file: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "file": self.file}


@dataclass(slots=True)
class ProjectDomainGuard:
    """Policy gate run before :class:`PatchApplier` accepts a patch."""

    allowed_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    forbidden_imports: tuple[str, ...] = field(
        default_factory=lambda: tuple(DEFAULT_FORBIDDEN_IMPORTS)
    )
    max_files_changed: int = 50
    max_lines_added: int = 5_000
    custom_predicates: tuple[PatchPredicate, ...] = ()

    def validate(self, patch: "ProjectPatch") -> list[DomainViolation]:
        """Run every check; return all violations (empty list = approved)."""
        violations: list[DomainViolation] = []

        files = patch.files_touched()
        if self.max_files_changed and len(files) > self.max_files_changed:
            violations.append(
                DomainViolation(
                    code="too_many_files",
                    message=(
                        f"patch touches {len(files)} files but max_files_changed="
                        f"{self.max_files_changed}"
                    ),
                )
            )

        for path in files:
            if self.allowed_paths and not _matches_any(path, self.allowed_paths):
                violations.append(
                    DomainViolation(
                        code="path_not_allowed",
                        message=f"path is outside allowed globs {list(self.allowed_paths)}",
                        file=path,
                    )
                )
            if self.forbidden_paths and _matches_any(path, self.forbidden_paths):
                violations.append(
                    DomainViolation(
                        code="path_forbidden",
                        message=f"path matches a forbidden glob {list(self.forbidden_paths)}",
                        file=path,
                    )
                )

        added_lines = _count_added_lines(patch)
        if self.max_lines_added and added_lines > self.max_lines_added:
            violations.append(
                DomainViolation(
                    code="too_many_lines",
                    message=(
                        f"patch adds {added_lines} net lines but max_lines_added="
                        f"{self.max_lines_added}"
                    ),
                )
            )

        if self.forbidden_imports:
            forbidden = tuple(self.forbidden_imports)
            for edit in patch.edits:
                if edit.operation == "delete":
                    continue
                added_imports = _added_imports(edit)
                for imp in added_imports:
                    for fb in forbidden:
                        if imp == fb or imp.startswith(fb + "."):
                            violations.append(
                                DomainViolation(
                                    code="forbidden_import",
                                    message=(
                                        f"patch introduces forbidden import {imp!r}"
                                    ),
                                    file=edit.path,
                                )
                            )

        for predicate in self.custom_predicates:
            try:
                reason = predicate(patch) or ""
            except Exception as exc:  # noqa: BLE001
                violations.append(
                    DomainViolation(
                        code="predicate_error",
                        message=(
                            f"custom predicate raised {type(exc).__name__}: {exc}"
                        ),
                    )
                )
                continue
            if reason:
                violations.append(
                    DomainViolation(code="custom_predicate", message=reason)
                )

        return violations

    def is_safe(self, patch: "ProjectPatch") -> bool:
        return not self.validate(patch)


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    rel = path.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatchcase(rel, pat):
            return True
        # Also allow ``src/**`` style by checking against any prefix.
        if pat.endswith("/**") and rel.startswith(pat[:-3] + "/"):
            return True
        if fnmatch.fnmatchcase(rel, pat + "/**"):
            return True
    return False


def _count_added_lines(patch: "ProjectPatch") -> int:
    total = 0
    for edit in patch.edits:
        if edit.operation == "create" and edit.contents:
            total += edit.contents.count("\n") + (
                0 if edit.contents.endswith("\n") else 1
            )
            continue
        if edit.operation == "delete":
            continue
        for hunk in edit.hunks:
            old_lines = (hunk.old_text or "").count("\n")
            new_lines = (hunk.new_text or "").count("\n")
            total += max(0, new_lines - old_lines)
    return total


def _added_imports(edit: Any) -> list[str]:
    """Pull import-looking lines out of every hunk's ``new_text``.

    Detects Python ``import x`` / ``from x import y`` and TS/JS
    ``import ... from "x"`` / ``require("x")`` so the guard works
    across the languages the project agent supports today.
    """
    out: list[str] = []
    if edit.operation == "create" and edit.contents:
        out.extend(_imports_in_text(edit.contents))
    for hunk in getattr(edit, "hunks", []) or []:
        new_text = getattr(hunk, "new_text", "") or ""
        old_text = getattr(hunk, "old_text", "") or ""
        new_imports = set(_imports_in_text(new_text))
        old_imports = set(_imports_in_text(old_text))
        for imp in sorted(new_imports - old_imports):
            out.append(imp)
    return out


def _imports_in_text(text: str) -> list[str]:
    import re as _re

    out: list[str] = []
    py_import = _re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", _re.MULTILINE)
    for m in py_import.finditer(text):
        mod = m.group(1) or m.group(2)
        if mod:
            out.append(mod.split(",")[0].strip())
    js_import = _re.compile(
        r"""(?:import\s+[^'"\n]*?\s+from\s+|require\s*\(\s*)['"]([^'"]+)['"]"""
    )
    for m in js_import.finditer(text):
        out.append(m.group(1))
    return out


__all__ = ["DomainViolation", "PatchPredicate", "ProjectDomainGuard"]
