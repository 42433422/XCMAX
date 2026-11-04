"""Read an explicitly bound dataset generation without initialization or locks.

Identity provisioning and deployment fencing are intentionally separate: an
old worker can replace a JSON file without preserving fields it does not know.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import stat
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

MAX_STORE_BYTES = 128 * 1024 * 1024


class StoreIdentityError(Exception):
    """The original dataset identity cannot be proven; do not infer an empty store."""


def valid_store_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
        return str(parsed) == value and parsed.version == 4
    except (ValueError, AttributeError):
        return False


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("invalid numeric constant")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("invalid number")
    return result


def _read_store(path: Path, expected_store_id: str | None) -> dict[str, Any]:
    if (
        not isinstance(path, Path)
        or not path.is_absolute()
        or (expected_store_id is not None and not valid_store_id(expected_store_id))
    ):
        raise StoreIdentityError("dataset binding unavailable")
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_STORE_BYTES:
            raise ValueError("invalid store file")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as file:
            opened = os.fstat(file.fileno())
            if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            ):
                raise ValueError("store changed during open")
            data = file.read(MAX_STORE_BYTES + 1)
            after = os.fstat(file.fileno())
            if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ValueError("store changed during read")
        if len(data) > MAX_STORE_BYTES:
            raise ValueError("store exceeds limit")
        raw = json.loads(
            data, object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float
        )
        if (
            not isinstance(raw, dict)
            or type(raw.get("version")) is not int
            or raw["version"] != 1
            or not isinstance(raw.get("datasets"), dict)
            or not valid_store_id(raw.get("store_id"))
            or (expected_store_id is not None and raw.get("store_id") != expected_store_id)
        ):
            raise ValueError("dataset identity mismatch")
        for dataset_id, dataset in raw["datasets"].items():
            if (
                not isinstance(dataset_id, str)
                or not isinstance(dataset, dict)
                or dataset.get("dataset_id") != dataset_id
                or not isinstance(dataset.get("documents"), dict)
                or not isinstance(dataset.get("chunks"), list)
                or any(not isinstance(row, dict) for row in dataset["documents"].values())
                or any(not isinstance(row, dict) for row in dataset["chunks"])
            ):
                raise ValueError("invalid dataset content")
        return raw
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
        raise StoreIdentityError("dataset binding unavailable") from None


def read_bound_store(path: Path, expected_store_id: str) -> dict[str, Any]:
    """Read exactly one existing generation for a previously trusted identity."""
    if not valid_store_id(expected_store_id):
        raise StoreIdentityError("dataset binding unavailable")
    return _read_store(path, expected_store_id)


def read_existing_store_for_claim(path: Path) -> dict[str, Any]:
    """Select an already provisioned identity for a new claim, never for an old receipt."""
    return _read_store(path, None)


def initialize_new_store(path: Path) -> str:
    """Create only an absent trusted store; never adopt or replace an old one.

    Caller must establish a deployment barrier for workers that do not preserve
    store IDs. The SQLite lock serializes cooperating writers, not old workers
    after this function returns. An error after publication is an unknown
    outcome: callers must inspect the original file, never retry as a new store.
    """
    if not isinstance(path, Path) or not path.is_absolute() or not path.parent.is_dir():
        raise StoreIdentityError("dataset initialization unavailable")
    lock_path = Path(str(path) + ".lock.sqlite3")
    connection = None
    temporary: str | None = None
    try:
        try:
            lock_stat = lock_path.lstat()
        except FileNotFoundError:
            lock_stat = None
        if lock_stat is not None and (
            not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1
        ):
            raise StoreIdentityError("dataset initialization unavailable")
        connection = sqlite3.connect(str(lock_path), timeout=1, isolation_level=None)
        connection.execute("BEGIN IMMEDIATE")
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise StoreIdentityError("dataset already exists; original must be verified")
        store_id = str(uuid4())
        content = json.dumps(
            {"version": 1, "store_id": store_id, "datasets": {}}, ensure_ascii=False
        ).encode("utf-8")
        fd, temporary = tempfile.mkstemp(prefix=".dataset-initializing-", dir=path.parent)
        with os.fdopen(fd, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        # Hard-link publication is atomic and fails if any file appeared at
        # the target, including a competing legacy writer's file or symlink.
        os.link(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        connection.execute("COMMIT")
        return store_id
    except (OSError, sqlite3.Error):
        raise StoreIdentityError(
            "dataset initialization unavailable; inspect original before retry"
        ) from None
    finally:
        if connection is not None:
            connection.close()
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            except OSError:
                raise StoreIdentityError("dataset initialization requires inspection") from None
