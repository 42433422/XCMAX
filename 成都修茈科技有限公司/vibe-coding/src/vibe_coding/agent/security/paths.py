"""Path-traversal checks shared by every component that touches the filesystem.

Why centralise: we have at least four call sites that need to turn an LLM-
supplied (or generally untrusted) relative path into an absolute filesystem
location — :class:`PatchApplier`, :class:`ProjectVibeCoder`, the sandbox
drivers, and the repo-index builder. Re-implementing the check in each spot
is exactly how a path-traversal bug ends up shipping. ``safe_relative_path``
is the single source of truth.

The check rejects:

- empty / whitespace-only strings
- absolute paths (POSIX ``/etc/passwd``, Windows ``C:\\Windows``, UNC paths)
- ``..`` segments (after normalisation)
- paths containing NUL bytes
- ``~`` / ``~user`` (tilde expansion)
- paths whose ``resolve()`` lands outside ``root`` (catches symlink escape)
- raw drive-letter prefixes on POSIX ``("C:foo")`` — they would look relative
  but Windows-style drives leak through some normalisers

It accepts: forward-slash and backslash separators (transparently
normalised), single-dot segments (stripped), trailing slashes (stripped).
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Iterable

# Reject any path with a NUL byte; some kernels truncate at the NUL which
# would let ``foo\x00/../etc/passwd`` slip past textual checks.
_NUL_RE = re.compile(r"\x00")
# Windows drive prefix even when the rest looks relative ("C:foo" is the
# *current directory on drive C*, not "C:/foo" — both are unsafe in this
# context).
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class PathSafetyError(ValueError):
    """Raised when a relative-path check rejects an LLM-supplied path."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path!r}: {reason}")
        self.path = path
        self.reason = reason


def safe_relative_path(value: str | os.PathLike[str]) -> str:
    """Return a normalised POSIX-style relative path or raise.

    The output never starts with ``/``, never contains ``..`` segments and
    never contains backslashes — it is safe to feed into ``Path(root) /
    result`` regardless of operating system.
    """
    if value is None:
        raise PathSafetyError("", "empty path")
    raw = os.fspath(value)
    if not isinstance(raw, str):
        raise PathSafetyError(str(raw), "path must be a string")
    if not raw or not raw.strip():
        raise PathSafetyError(raw, "empty path")
    if _NUL_RE.search(raw):
        raise PathSafetyError(raw, "path contains NUL byte")
    if raw.startswith("~"):
        raise PathSafetyError(raw, "tilde expansion not allowed")

    normalised = raw.replace("\\", "/").strip()
    if normalised.startswith("/"):
        raise PathSafetyError(raw, "absolute path not allowed")
    if normalised.startswith("//") or normalised.startswith("\\\\"):
        raise PathSafetyError(raw, "UNC path not allowed")
    if _DRIVE_RE.match(normalised):
        raise PathSafetyError(raw, "drive-prefixed path not allowed")

    parts: list[str] = []
    for part in PurePosixPath(normalised).parts:
        if part in {"", "."}:
            continue
        if part == "..":
            raise PathSafetyError(raw, "parent traversal ('..') not allowed")
        if part.startswith("/"):
            raise PathSafetyError(raw, "absolute segment not allowed")
        if _DRIVE_RE.match(part):
            raise PathSafetyError(raw, "drive-prefixed segment not allowed")
        parts.append(part)
    if not parts:
        raise PathSafetyError(raw, "path normalised to empty")
    return str(PurePosixPath(*parts))


def is_safe_relative(value: str | os.PathLike[str]) -> bool:
    """Convenience predicate around :func:`safe_relative_path`."""
    try:
        safe_relative_path(value)
    except PathSafetyError:
        return False
    return True


def resolve_within_root(
    root: str | os.PathLike[str],
    rel: str | os.PathLike[str],
    *,
    allow_existing_symlink: bool = False,
) -> Path:
    """Return an absolute path proven to live inside ``root``.

    Steps:
      1. Normalise ``rel`` via :func:`safe_relative_path` — rejects absolute
         paths, tilde, drive prefixes, ``..`` segments and NUL bytes.
      2. Join with ``root`` and ``resolve()`` (follows symlinks the OS
         already created).
      3. Re-check that the resolved path is still under ``root.resolve()``
         (catches symlinks that point outside).

    ``allow_existing_symlink=True`` skips step 3's strict check for the
    *final* component only — useful for ``rename`` operations where the
    destination might be a fresh path (no symlink yet) but the parent was
    already validated. The default is the strictest behaviour.
    """
    root_p = Path(root)
    if not root_p.is_absolute():
        root_p = root_p.resolve()
    safe_rel = safe_relative_path(rel)
    candidate = (root_p / safe_rel).resolve()
    root_resolved = root_p.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        if allow_existing_symlink:
            # Re-try without resolving the leaf (handles "rename to fresh
            # path that doesn't exist yet").
            parent = (root_p / safe_rel).parent.resolve()
            try:
                parent.relative_to(root_resolved)
            except ValueError:
                raise PathSafetyError(
                    str(rel), f"resolved path escapes root: {candidate} not under {root_resolved}"
                ) from exc
            return root_p / safe_rel
        raise PathSafetyError(
            str(rel), f"resolved path escapes root: {candidate} not under {root_resolved}"
        ) from exc
    return candidate


def filter_safe_paths(values: Iterable[str | os.PathLike[str]]) -> list[str]:
    """Return only the values that pass :func:`is_safe_relative`."""
    return [str(v) for v in values if is_safe_relative(v)]


__all__ = [
    "PathSafetyError",
    "filter_safe_paths",
    "is_safe_relative",
    "resolve_within_root",
    "safe_relative_path",
]
