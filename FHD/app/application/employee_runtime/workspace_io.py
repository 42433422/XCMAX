"""No-follow, descriptor-relative access below an explicitly selected workspace."""

from __future__ import annotations

import errno
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

_WINDOWS = os.name == "nt"


def _require_secure_handles():
    if (
        not all(getattr(os, flag, 0) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC"))
        or not {os.open, os.mkdir}.issubset(getattr(os, "supports_dir_fd", set()))
        or os.listdir not in getattr(os, "supports_fd", set())
    ):
        raise OSError(errno.ENOTSUP, "secure workspace handles are unavailable")


def component(value: str) -> str:
    if not re.fullmatch(r"[^/\\\x00]+", value) or value in (".", ".."):
        raise ValueError("workspace filename must be one component")
    return value


@contextmanager
def workspace_directory(workspace: str | Path, directory: str | Path, *, create=False):
    # Do not resolve links: opening every component with NOFOLLOW rejects them.
    root, target = Path(os.path.abspath(workspace)), Path(os.path.abspath(directory))
    target.relative_to(root)
    if _WINDOWS:
        from app.application.shipment_excel_etl_security import (
            _windows_open_anchor,
            _windows_open_relative,
        )

        fd = _windows_open_anchor(root.anchor, list_directory=True)
        try:
            for part in (*root.parts[1:], *target.relative_to(root).parts):
                next_fd = _windows_open_relative(
                    fd, component(part), directory=True, create=False, list_directory=True
                )
                os.close(fd)
                fd = next_fd
            if create:
                raise OSError(errno.ENOTSUP, "Windows workspace ledger writes are unavailable")
            yield fd
        finally:
            os.close(fd)
        return
    _require_secure_handles()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    # POSIX absolute paths always anchor at the filesystem root; use a constant
    # so no caller-provided string reaches os.open.
    fd = os.open(os.sep, flags)
    try:
        for part in root.parts[1:]:
            next_fd = os.open(component(part), flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        for part in target.relative_to(root).parts:
            name = component(part)
            if create:
                try:
                    os.mkdir(name, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


@contextmanager
def workspace_file(parent_fd: int, name: str, flags: int, mode: str):
    if _WINDOWS:
        if flags != os.O_RDONLY or mode != "r":
            raise OSError(errno.ENOTSUP, "Windows workspace ledger writes are unavailable")
        from app.application.shipment_excel_etl_security import _windows_open_relative

        fd = _windows_open_relative(
            parent_fd, component(name), directory=False, create=False, for_input=True
        )
    else:
        _require_secure_handles()
        safe_name = os.path.basename(name)
        if (
            safe_name != name
            or not safe_name
            or safe_name in (".", "..")
            or "\x00" in safe_name
        ):
            raise ValueError("workspace filename must be one component")
        fd = os.open(
            safe_name,
            flags | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise ValueError("workspace file must be a single-link regular file")
        stream = os.fdopen(fd, mode, encoding="utf-8")
        fd = -1
        with stream:
            yield stream
    finally:
        if fd >= 0:
            os.close(fd)


def workspace_names(parent_fd: int) -> list[str]:
    if _WINDOWS:
        from app.application.shipment_etl.directory_listing import list_directory_names

        return list_directory_names(parent_fd)
    return os.listdir(parent_fd)
