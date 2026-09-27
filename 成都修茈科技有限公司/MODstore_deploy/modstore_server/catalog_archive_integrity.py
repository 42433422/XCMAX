"""Resolve only immutable catalog archive bytes matching their published SHA256."""

from __future__ import annotations

import hashlib
import stat
from functools import lru_cache
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache(maxsize=512)
def _archive_digest(path: str, identity: tuple[int, ...]) -> str:
    return sha256_file(Path(path))


def archive_path(filename: Any, expected_sha256: Any, roots: tuple[Path, ...]) -> Path | None:
    name = str(filename or "").strip()
    digest = str(expected_sha256 or "").strip().lower()
    if not name or Path(name).name != name or "\\" in name:
        return None
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return None
    for root in roots:
        path = root / name
        try:
            before = path.lstat()
            if not stat.S_ISREG(before.st_mode):
                continue
            identity = (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            if _archive_digest(str(path), identity) != digest:
                continue
            after = path.lstat()
            if identity == (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                return path
        except OSError:
            continue
    return None
