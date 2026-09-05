"""Durable label-job state and non-serializable authorization at the spool boundary."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

_dispatch_context: ContextVar[tuple[Path, str] | None] = ContextVar(
    "label_dispatch_context", default=None
)


@contextmanager
def label_job_lock(directory: Path) -> Iterator[None]:
    lock = directory / "job.lock"
    if lock.is_symlink():
        raise OSError("Invalid label lock path")
    with lock.open("a+b") as handle:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_label_job(directory: Path, job: dict) -> None:
    temporary = directory / f"manifest-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8") as file:
            json.dump(job, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(0o600)
        temporary.replace(directory / "job.json")
        if os.name == "posix":
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def authorized_label_dispatch(path: Path, credential: str) -> Iterator[None]:
    """Only the confirmed application use case creates this in-process context."""
    token = _dispatch_context.set((path, credential))
    try:
        yield
    finally:
        _dispatch_context.reset(token)


def claim_label_dispatch(path: Path, printer: str | None, copies: int = 1) -> bool:
    """Atomically claim exactly one spool call; lost context always fails closed."""
    context = _dispatch_context.get()
    if context is None or context[0] != path or copies != 1:
        return False
    directory = path.parent
    manifest = directory / "job.json"
    if manifest.is_symlink() or not manifest.is_file():
        return False
    try:
        with label_job_lock(directory):
            job = json.loads(manifest.read_text(encoding="utf-8"))
            digest = str(job.get("dispatch_hash") or "")
            if (
                job.get("status") != "submitting"
                or job.get("dispatch_claimed") is not False
                or str(job.get("tenant_id")) != directory.parent.parent.name
                or str(job.get("user_id")) != directory.parent.name
                or job.get("id") != directory.name
                or not printer
                or job.get("printer") != printer
                or not secrets.compare_digest(
                    digest, hashlib.sha256(context[1].encode()).hexdigest()
                )
                or hashlib.sha256(path.read_bytes()).hexdigest() != job.get("sha256")
            ):
                return False
            job["dispatch_claimed"] = True
            job.pop("dispatch_hash", None)
            write_label_job(directory, job)
            return True
    except (ValueError, OSError):
        return False
