"""Security boundaries for filesystem and observability data."""

from __future__ import annotations

import hashlib
import hmac
import os
import stat
from pathlib import Path
from typing import Iterable


class UnsafePath(ValueError):
    """Raised when a requested path crosses its assigned filesystem root."""


_OBSERVABILITY_KEY = os.urandom(32)


def opaque_ref(value: object, *, namespace: str = "value") -> str:
    """Return a process-local, non-reversible reference suitable for logs."""

    payload = (namespace + ":" + str(value)).encode("utf-8", errors="replace")
    return hmac.new(_OBSERVABILITY_KEY, payload, hashlib.sha256).hexdigest()[:16]


def resolve_path_under_root(
    root: str | os.PathLike[str],
    requested_path: str | os.PathLike[str],
    *,
    require_relative: bool = True,
    reject_symlinks: bool = True,
) -> Path:
    """Resolve beneath root and reject traversal and symlink escapes."""

    raw = os.fspath(requested_path)
    if not isinstance(raw, str):
        raw = os.fsdecode(raw)
    if not raw or chr(0) in raw:
        raise UnsafePath("path is empty or contains NUL")
    if require_relative and os.path.isabs(raw):
        raise UnsafePath("absolute paths are not allowed")

    root_real = os.path.realpath(os.path.abspath(os.path.expanduser(os.fspath(root))))
    root_prefix = root_real if root_real.endswith(os.sep) else root_real + os.sep
    candidate_lexical = os.path.normpath(os.path.join(root_real, raw))
    if candidate_lexical != root_real and not candidate_lexical.startswith(root_prefix):
        raise UnsafePath("path is outside the assigned root")

    if reject_symlinks:
        relative = Path(candidate_lexical).relative_to(Path(root_real))
        cursor = Path(root_real)
        for component in relative.parts:
            cursor = cursor / component
            cursor_lexical = os.path.normpath(os.fspath(cursor))
            if cursor_lexical != root_real and not cursor_lexical.startswith(root_prefix):
                raise UnsafePath("path is outside the assigned root")
            cursor_real = os.path.realpath(cursor_lexical)
            if cursor_real != root_real and not cursor_real.startswith(root_prefix):
                raise UnsafePath("path is outside the assigned root")
            try:
                mode = os.lstat(cursor_lexical).st_mode
            except FileNotFoundError:
                break
            if stat.S_ISLNK(mode):
                raise UnsafePath("symlink components are not allowed")

    candidate_real = os.path.realpath(candidate_lexical)
    if candidate_real != root_real and not candidate_real.startswith(root_prefix):
        raise UnsafePath("path is outside the assigned root")

    return Path(candidate_real)


def select_authorized_root(
    requested_root: str | os.PathLike[str],
    authorized_roots: Iterable[str | os.PathLike[str]],
) -> Path:
    """Select an exact server-owned root without resolving untrusted input."""

    raw = os.fspath(requested_root)
    if not isinstance(raw, str):
        raw = os.fsdecode(raw)
    if not raw or chr(0) in raw:
        raise UnsafePath("workspace root is empty or invalid")
    requested_key = os.path.normcase(os.path.abspath(os.path.expanduser(raw)))
    for configured in authorized_roots:
        configured_raw = os.fspath(configured)
        if not configured_raw:
            continue
        configured_key = os.path.normcase(
            os.path.abspath(os.path.expanduser(os.fsdecode(configured_raw)))
        )
        resolved = Path(configured_raw).expanduser().resolve()
        resolved_key = os.path.normcase(str(resolved))
        if requested_key in {configured_key, resolved_key}:
            return resolved
    raise UnsafePath("workspace root is not server-authorized")


__all__ = [
    "UnsafePath",
    "opaque_ref",
    "resolve_path_under_root",
    "select_authorized_root",
]
