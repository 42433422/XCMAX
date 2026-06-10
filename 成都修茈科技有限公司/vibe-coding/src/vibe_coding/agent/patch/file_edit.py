""":class:`FileEdit` and :class:`ProjectPatch`.

A :class:`FileEdit` is one of four operations:

- ``modify`` — apply a list of :class:`Hunk` to an existing file
- ``create`` — write ``contents`` to a new path (must not already exist)
- ``delete`` — remove an existing file
- ``rename`` — move ``path`` to ``new_path``; can additionally carry hunks to
  apply to the file *before* the rename

A :class:`ProjectPatch` aggregates many edits with a top-level summary so the
ledger entry reads cleanly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from ..security.paths import PathSafetyError, safe_relative_path
from .hunk import Hunk

Operation = Literal["modify", "create", "delete", "rename"]


@dataclass(slots=True)
class FileEdit:
    """A single file-level operation in a :class:`ProjectPatch`."""

    path: str
    operation: Operation = "modify"
    hunks: list[Hunk] = field(default_factory=list)
    contents: str | None = None
    new_path: str | None = None
    description: str = ""

    def __post_init__(self) -> None:
        self.path = _norm_rel(self.path)
        if self.new_path is not None:
            self.new_path = _norm_rel(self.new_path)
        self.operation = self.operation if self.operation in {"modify", "create", "delete", "rename"} else "modify"
        self._validate()

    def _validate(self) -> None:
        if self.operation == "create":
            if self.contents is None:
                raise ValueError(f"FileEdit({self.path!r}): create needs contents")
            if self.hunks:
                raise ValueError(f"FileEdit({self.path!r}): create cannot have hunks")
        elif self.operation == "delete":
            if self.hunks or self.contents is not None:
                raise ValueError(f"FileEdit({self.path!r}): delete must not carry hunks/contents")
        elif self.operation == "rename":
            if not self.new_path:
                raise ValueError(f"FileEdit({self.path!r}): rename needs new_path")
        elif self.operation == "modify":
            if self.contents is not None:
                # Tolerated for round-tripping but warned via empty hunks rule.
                pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "hunks": [h.to_dict() for h in self.hunks],
            "contents": self.contents,
            "new_path": self.new_path,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FileEdit:
        op = str(raw.get("operation") or "modify")
        if op not in {"modify", "create", "delete", "rename"}:
            op = "modify"
        return cls(
            path=str(raw.get("path") or ""),
            operation=op,  # type: ignore[arg-type]
            hunks=[Hunk.from_dict(h) for h in raw.get("hunks") or [] if isinstance(h, dict)],
            contents=raw.get("contents"),
            new_path=str(raw["new_path"]) if raw.get("new_path") else None,
            description=str(raw.get("description") or ""),
        )


@dataclass(slots=True)
class ProjectPatch:
    """An ordered, atomic group of :class:`FileEdit`."""

    patch_id: str = field(default_factory=lambda: f"patch-{uuid4().hex[:10]}")
    summary: str = ""
    rationale: str = ""
    edits: list[FileEdit] = field(default_factory=list)

    def files_touched(self) -> list[str]:
        seen: list[str] = []
        for edit in self.edits:
            if edit.path not in seen:
                seen.append(edit.path)
            if edit.new_path and edit.new_path not in seen:
                seen.append(edit.new_path)
        return seen

    def stats(self) -> dict[str, int]:
        out = {"modify": 0, "create": 0, "delete": 0, "rename": 0, "hunks": 0}
        for edit in self.edits:
            out[edit.operation] += 1
            out["hunks"] += len(edit.hunks)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "summary": self.summary,
            "rationale": self.rationale,
            "edits": [e.to_dict() for e in self.edits],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProjectPatch:
        return cls(
            patch_id=str(raw.get("patch_id") or f"patch-{uuid4().hex[:10]}"),
            summary=str(raw.get("summary") or ""),
            rationale=str(raw.get("rationale") or ""),
            edits=[FileEdit.from_dict(e) for e in raw.get("edits") or [] if isinstance(e, dict)],
        )


def _norm_rel(value: str) -> str:
    """Normalise a relative path used in a :class:`FileEdit`.

    We accept anything :func:`safe_relative_path` accepts and simply return
    the empty string for falsy inputs (the ``ProjectPatch`` parser tolerates
    that and lets the applier raise a friendlier error). Unsafe inputs
    (absolute paths, ``..`` segments, NUL bytes …) raise :class:`ValueError`
    here so the rejection happens at construction time.
    """
    if not value:
        return ""
    try:
        return safe_relative_path(value)
    except PathSafetyError as exc:
        raise ValueError(str(exc)) from exc


# PurePosixPath imported above is used by _norm_rel internals; reference
# it once so static analysers don't flag the import as unused after the
# refactor.
_ = PurePosixPath


__all__ = ["FileEdit", "Operation", "ProjectPatch"]
