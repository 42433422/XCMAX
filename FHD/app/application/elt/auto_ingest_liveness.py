"""Worker ownership, not permission to replay an interrupted business write."""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.utils.process_lock import _try_lock, _unlock


def acquire(ledger: Path, batch_id: str):
    path = ledger.parent / (hashlib.sha256(batch_id.encode()).hexdigest() + ".worker.lock")
    handle = path.open("a+b")
    transferred = False
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        _try_lock(handle)
        transferred = True
        return handle
    finally:
        if not transferred:
            handle.close()


def release(handle):
    try:
        _unlock(handle)
    finally:
        handle.close()


def orphaned(ledger: Path, batch: dict) -> bool:
    # Old workers never owned this lock: absence cannot prove their death.
    if batch.get("worker_protocol") != 1 or batch.get("status") != "running":
        return False
    try:
        handle = acquire(ledger, batch["batch_id"])
    except OSError:
        return False
    release(handle)
    return True
