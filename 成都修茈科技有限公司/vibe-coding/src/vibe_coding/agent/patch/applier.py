"""Atomic, transactional :class:`ProjectPatch` applier.

Workflow per :meth:`PatchApplier.apply` call:

1. **Stage** — Compute the post-patch contents of every file affected. If
   *any* hunk fails to locate (anchor + ``old_text`` not found within fuzzy
   tolerance), the whole patch is rejected with a :class:`PatchConflict`.
2. **Commit** — Write all staged buffers in one pass, after backing up the
   pre-patch contents to ``backup_dir`` keyed by ``patch_id``. The backup
   ledger entry makes :meth:`PatchApplier.rollback` deterministic.
3. **Rollback** — On any IO failure mid-commit, restore from backup and
   surface the underlying error to the caller. This keeps the working tree
   consistent even when the disk fills up halfway through.

By default the applier rejects edits that escape the project root, refuses to
overwrite created files that already exist, and requires existing files to be
present for ``modify`` / ``delete`` / ``rename`` (configurable via
:class:`PatchApplier`'s constructor).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from vibe_coding.operational_errors import BOUNDARY_ERRORS

from ..security.paths import PathSafetyError, resolve_within_root
from .file_edit import FileEdit, ProjectPatch
from .hunk import Hunk

DEFAULT_FUZZY_LINES = 10
DEFAULT_BACKUP_DIRNAME = "patch_backups"


class PatchConflict(RuntimeError):
    """Raised when a hunk cannot be located and the whole patch must be aborted."""

    def __init__(self, *, file: str, reason: str, hunk_index: int = -1):
        super().__init__(f"{file}: {reason} (hunk_index={hunk_index})")
        self.file = file
        self.reason = reason
        self.hunk_index = hunk_index


@dataclass(slots=True)
class FileResult:
    path: str
    operation: str
    bytes_before: int = 0
    bytes_after: int = 0
    hunks_applied: int = 0
    fuzzy_hunks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "operation": self.operation,
            "bytes_before": self.bytes_before,
            "bytes_after": self.bytes_after,
            "hunks_applied": self.hunks_applied,
            "fuzzy_hunks": self.fuzzy_hunks,
        }


@dataclass(slots=True)
class ApplyResult:
    patch_id: str
    applied: bool
    dry_run: bool
    files: list[FileResult] = field(default_factory=list)
    error: str = ""
    backup_dir: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "patch_id": self.patch_id,
            "applied": self.applied,
            "dry_run": self.dry_run,
            "files": [f.to_dict() for f in self.files],
            "error": self.error,
            "backup_dir": self.backup_dir,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class PatchApplier:
    """Apply a :class:`ProjectPatch` atomically.

    ``backup_dir`` defaults to ``<root>/.vibe_coding/patch_backups`` so the
    project's normal ignore rules naturally exclude it.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        backup_dir: str | Path | None = None,
        fuzzy_lines: int = DEFAULT_FUZZY_LINES,
    ):
        self.root = Path(root).resolve()
        if backup_dir is None:
            backup_dir = self.root / ".vibe_coding" / DEFAULT_BACKUP_DIRNAME
        self.backup_dir = Path(backup_dir).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.fuzzy_lines = max(0, int(fuzzy_lines))
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ public

    def apply(self, patch: ProjectPatch, *, dry_run: bool = False) -> ApplyResult:
        result = ApplyResult(patch_id=patch.patch_id, applied=False, dry_run=dry_run)
        with self._lock:
            try:
                staged = self._stage(patch)
            except PatchConflict as exc:
                result.error = str(exc)
                result.completed_at = time.time()
                return result

            result.files = [s.result for s in staged]
            if dry_run:
                result.applied = True
                result.completed_at = time.time()
                return result

            backup_path = self.backup_dir / (
                f"{self._backup_key(patch.patch_id)}-{time.time_ns()}-{uuid4().hex[:6]}"
            )
            try:
                self._commit(
                    staged,
                    backup_path=backup_path,
                    patch_id=patch.patch_id,
                    summary=patch.summary,
                )
            except BOUNDARY_ERRORS as exc:
                self._rollback(backup_path)
                result.error = f"commit_failed:{type(exc).__name__}:{exc}"
                result.completed_at = time.time()
                return result
            result.backup_dir = str(backup_path)
            result.applied = True
            result.completed_at = time.time()
            return result

    def rollback(self, patch_id: str) -> bool:
        """Restore files from the most recent backup matching ``patch_id``."""
        with self._lock:
            backup_key = self._backup_key(patch_id)
            candidates = sorted(self.backup_dir.glob(f"{backup_key}-*"), reverse=True)
            for backup in candidates:
                try:
                    backup = self._validated_backup_dir(backup)
                    manifest = self._backup_file(backup, "manifest.json")
                except PatchConflict:
                    continue
                if manifest.is_symlink() or not manifest.is_file():
                    continue
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict) or data.get("patch_id") != patch_id:
                    continue
                try:
                    self._restore_from_manifest(backup, data)
                except (OSError, PatchConflict, TypeError, ValueError):
                    return False
                return True
            return False

    # ------------------------------------------------------------------ stage

    def _stage(self, patch: ProjectPatch) -> list[_StagedFile]:
        staged: list[_StagedFile] = []
        seen_paths: set[str] = set()
        for edit in patch.edits:
            self._reject_unsafe(edit.path)
            if edit.new_path:
                self._reject_unsafe(edit.new_path)
            if edit.path in seen_paths:
                raise PatchConflict(
                    file=edit.path, reason="duplicate edit for path within one patch"
                )
            seen_paths.add(edit.path)

            if edit.operation == "create":
                staged.append(self._stage_create(edit))
            elif edit.operation == "delete":
                staged.append(self._stage_delete(edit))
            elif edit.operation == "rename":
                staged.append(self._stage_rename(edit))
            else:
                staged.append(self._stage_modify(edit))
        return staged

    def _stage_modify(self, edit: FileEdit) -> _StagedFile:
        target = self._abs(edit.path)
        if not target.is_file():
            raise PatchConflict(file=edit.path, reason="modify target does not exist")
        original = target.read_text(encoding="utf-8")
        new_text, applied, fuzzy = self._apply_hunks(edit.path, original, edit.hunks)
        return _StagedFile(
            edit=edit,
            target=target,
            original_bytes=original.encode("utf-8"),
            new_bytes=new_text.encode("utf-8"),
            existed=True,
            result=FileResult(
                path=edit.path,
                operation="modify",
                bytes_before=len(original.encode("utf-8")),
                bytes_after=len(new_text.encode("utf-8")),
                hunks_applied=applied,
                fuzzy_hunks=fuzzy,
            ),
        )

    def _stage_create(self, edit: FileEdit) -> _StagedFile:
        target = self._abs(edit.path)
        if target.exists():
            raise PatchConflict(file=edit.path, reason="create target already exists")
        contents = edit.contents or ""
        return _StagedFile(
            edit=edit,
            target=target,
            original_bytes=b"",
            new_bytes=contents.encode("utf-8"),
            existed=False,
            result=FileResult(
                path=edit.path,
                operation="create",
                bytes_before=0,
                bytes_after=len(contents.encode("utf-8")),
                hunks_applied=0,
                fuzzy_hunks=0,
            ),
        )

    def _stage_delete(self, edit: FileEdit) -> _StagedFile:
        target = self._abs(edit.path)
        if not target.exists():
            raise PatchConflict(file=edit.path, reason="delete target does not exist")
        if target.is_dir():
            raise PatchConflict(
                file=edit.path, reason="delete target is a directory; not supported"
            )
        original = target.read_bytes()
        return _StagedFile(
            edit=edit,
            target=target,
            original_bytes=original,
            new_bytes=None,
            existed=True,
            result=FileResult(
                path=edit.path,
                operation="delete",
                bytes_before=len(original),
                bytes_after=0,
            ),
        )

    def _stage_rename(self, edit: FileEdit) -> _StagedFile:
        if not edit.new_path:
            raise PatchConflict(file=edit.path, reason="rename missing new_path")
        target = self._abs(edit.path)
        new_target = self._abs(edit.new_path)
        if not target.is_file():
            raise PatchConflict(file=edit.path, reason="rename source does not exist")
        if new_target.exists() and new_target.resolve() != target.resolve():
            raise PatchConflict(
                file=edit.new_path, reason="rename destination already exists"
            )
        original = target.read_text(encoding="utf-8")
        if edit.hunks:
            new_text, applied, fuzzy = self._apply_hunks(
                edit.path, original, edit.hunks
            )
        else:
            new_text, applied, fuzzy = original, 0, 0
        return _StagedFile(
            edit=edit,
            target=target,
            new_target=new_target,
            original_bytes=original.encode("utf-8"),
            new_bytes=new_text.encode("utf-8"),
            existed=True,
            result=FileResult(
                path=edit.path,
                operation="rename",
                bytes_before=len(original.encode("utf-8")),
                bytes_after=len(new_text.encode("utf-8")),
                hunks_applied=applied,
                fuzzy_hunks=fuzzy,
            ),
        )

    # ---------------------------------------------------------------- commit

    def _commit(
        self,
        staged: list[_StagedFile],
        *,
        backup_path: Path,
        patch_id: str,
        summary: str,
    ) -> None:
        backup_path.mkdir(parents=True, exist_ok=False)
        manifest: dict[str, Any] = {
            "patch_id": patch_id,
            "summary": summary,
            "entries": [],
        }
        try:
            # Build the complete recovery ledger before the first project
            # mutation. A mid-commit failure can therefore always restore all
            # files already written by the second loop.
            for item in staged:
                self._backup_one(item, backup_path, manifest)
            (backup_path / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            for item in staged:
                self._write_one(item)
        except BOUNDARY_ERRORS:
            # Caller is expected to invoke _rollback; re-raise to bubble up.
            raise

    def _backup_one(
        self,
        item: _StagedFile,
        backup_path: Path,
        manifest: dict[str, Any],
    ) -> None:
        entry: dict[str, Any] = {
            "operation": item.edit.operation,
            "path": item.edit.path,
            "new_path": item.edit.new_path,
            "existed": item.existed,
        }
        if item.existed:
            backup_file = self._backup_file(backup_path, item.edit.path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            backup_file.write_bytes(item.original_bytes)
            entry["backup_file"] = str(backup_file.relative_to(backup_path).as_posix())
        manifest["entries"].append(entry)

    def _write_one(self, item: _StagedFile) -> None:
        op = item.edit.operation
        if op == "delete":
            item.target.unlink()
            return
        if op == "rename" and item.new_target is not None:
            assert item.new_bytes is not None
            item.new_target.parent.mkdir(parents=True, exist_ok=True)
            self._atomic_write(item.new_target, item.new_bytes)
            if item.target.resolve() != item.new_target.resolve():
                with contextlib.suppress(FileNotFoundError):
                    item.target.unlink()
            return
        # create / modify
        assert item.new_bytes is not None
        item.target.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(item.target, item.new_bytes)

    def _atomic_write(self, target: Path, data: bytes) -> None:
        tmp = target.with_suffix(target.suffix + f".tmp-{uuid4().hex[:8]}")
        tmp.write_bytes(data)
        os.replace(tmp, target)

    def _rollback(self, backup_path: Path) -> None:
        if not backup_path.exists():
            return
        manifest_path = backup_path / "manifest.json"
        if not manifest_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            shutil.rmtree(backup_path, ignore_errors=True)
            return
        self._restore_from_manifest(backup_path, data)

    def _restore_from_manifest(self, backup_path: Path, data: dict[str, Any]) -> None:
        entries = data.get("entries")
        if not isinstance(entries, list):
            raise PatchConflict(
                file="manifest.json", reason="backup entries must be a list"
            )
        for entry in reversed(entries):
            if not isinstance(entry, dict):
                raise PatchConflict(
                    file="manifest.json", reason="backup entry must be an object"
                )
            self._restore_entry(backup_path, entry)

    def _restore_entry(self, backup_path: Path, entry: dict[str, Any]) -> None:
        op = entry.get("operation")
        if op not in {"create", "delete", "rename", "modify"}:
            raise PatchConflict(file="manifest.json", reason="unknown backup operation")
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise PatchConflict(
                file="manifest.json", reason="backup path must be a string"
            )
        new_path = entry.get("new_path")
        if new_path is not None and not isinstance(new_path, str):
            raise PatchConflict(
                file="manifest.json", reason="backup new_path must be a string"
            )
        existed = bool(entry.get("existed", False))
        target = self._abs(path)
        backup_file = entry.get("backup_file")
        if backup_file is not None and (
            not isinstance(backup_file, str) or not backup_file
        ):
            raise PatchConflict(
                file="manifest.json", reason="backup_file must be a string"
            )

        if op == "create":
            if target.exists():
                with contextlib.suppress(OSError):
                    target.unlink()
            return
        if op == "delete":
            if backup_file:
                source = self._backup_source(backup_path, backup_file)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            return
        if op == "rename":
            if new_path:
                new_target = self._abs(str(new_path))
                if new_target.exists() and new_target.resolve() != target.resolve():
                    with contextlib.suppress(OSError):
                        new_target.unlink()
            if existed and backup_file:
                source = self._backup_source(backup_path, backup_file)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            return
        # modify
        if existed and backup_file:
            source = self._backup_source(backup_path, backup_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    # --------------------------------------------------------------- helpers

    def _abs(self, rel: str) -> Path:
        try:
            return resolve_within_root(self.root, rel)
        except PathSafetyError as exc:
            raise PatchConflict(file=rel, reason=exc.reason) from exc

    def _reject_unsafe(self, rel: str) -> None:
        """Centralised path-safety gate (delegates to :mod:`agent.security.paths`).

        Catches: empty paths, ``..``, absolute paths, drive letters, NUL bytes,
        symlink escape (resolved path lands outside root). Raises a
        :class:`PatchConflict` so the failure bubbles into the existing
        rollback flow.
        """
        self._abs(rel)

    @staticmethod
    def _backup_key(patch_id: str) -> str:
        """Map an untrusted patch identifier to a fixed path-safe key."""
        return hashlib.sha256(patch_id.encode("utf-8")).hexdigest()

    def _validated_backup_dir(self, candidate: Path) -> Path:
        """Return a real backup directory contained by ``self.backup_dir``."""
        if candidate.is_symlink():
            raise PatchConflict(
                file=str(candidate), reason="backup directory cannot be a symlink"
            )
        try:
            relative = candidate.relative_to(self.backup_dir)
            resolved = resolve_within_root(self.backup_dir, relative)
        except (PathSafetyError, ValueError) as exc:
            reason = (
                exc.reason
                if isinstance(exc, PathSafetyError)
                else "backup escapes backup root"
            )
            raise PatchConflict(file=str(candidate), reason=reason) from exc
        if not resolved.is_dir():
            raise PatchConflict(
                file=str(candidate), reason="backup directory does not exist"
            )
        return resolved

    @staticmethod
    def _backup_file(backup_path: Path, rel: str) -> Path:
        try:
            return resolve_within_root(backup_path, rel)
        except PathSafetyError as exc:
            raise PatchConflict(
                file=rel, reason=f"unsafe backup path: {exc.reason}"
            ) from exc

    def _backup_source(self, backup_path: Path, rel: str) -> Path:
        backup_path = self._validated_backup_dir(backup_path)
        source = self._backup_file(backup_path, rel)
        if source.is_symlink() or not source.is_file():
            raise PatchConflict(file=rel, reason="backup source is not a regular file")
        return source

    def _apply_hunks(
        self, path: str, source: str, hunks: list[Hunk]
    ) -> tuple[str, int, int]:
        """Return ``(new_source, hunks_applied, fuzzy_hunks)``."""
        if not hunks:
            return source, 0, 0
        text = source
        applied = 0
        fuzzy = 0
        for idx, hunk in enumerate(hunks):
            text, used_fuzzy = self._apply_one(path, text, hunk, idx)
            applied += 1
            if used_fuzzy:
                fuzzy += 1
        return text, applied, fuzzy

    def _apply_one(
        self, path: str, source: str, hunk: Hunk, idx: int
    ) -> tuple[str, bool]:
        """Apply one hunk via the shared cascade in :mod:`.repair`.

        The cascade tries (in order): strict anchor match → anchors-only
        insertion → fuzzy anchor + old_text within ``fuzzy_lines`` window →
        unique ``old_text`` replacement → leading-whitespace-tolerant
        ``old_text`` match → anchor_after-only insertion → file-level
        append. The bool we return signals whether the strategy was a
        non-strict one (the ``ApplyResult`` aggregates this for telemetry).
        """
        from .repair import HunkApplyError, apply_hunks_to_source

        try:
            outcome = apply_hunks_to_source(
                source,
                [hunk],
                fuzzy_lines=self.fuzzy_lines,
                raise_on_failure=True,
            )
        except HunkApplyError as exc:
            raise PatchConflict(
                file=path,
                reason=exc.reason or "anchors and old_text could not be located",
                hunk_index=idx,
            ) from exc
        strategy = outcome.results[0].strategy
        return outcome.source, strategy != "strict"


@dataclass(slots=True)
class _StagedFile:
    edit: FileEdit
    target: Path
    original_bytes: bytes
    new_bytes: bytes | None
    existed: bool
    result: FileResult
    new_target: Path | None = None


__all__ = ["ApplyResult", "FileResult", "PatchApplier", "PatchConflict"]
