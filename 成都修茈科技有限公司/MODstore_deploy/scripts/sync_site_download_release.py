#!/usr/bin/env python3
"""Preserve published desktop pointers during an unrelated server deployment.

Only an explicitly authorized desktop publisher may promote artifacts. Server SHA,
version ordering, build mtime and manual acceptance are never publication authority.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile

MIRRORS = (
    "MODstore_deploy/market/public",
    "MODstore_deploy/market/dist",
    "corp-butler",
)
POINTERS = ("download-release.json", "download-windows-hotfix.json")
PUBLICATION_LOCK = Path(
    os.environ.get("XCMAX_PUBLICATION_LOCK", "/run/lock/xcmax-publication.lock")
)


@contextmanager
def publication_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def _bytes(path: Path) -> bytes | None:
    if path.is_symlink():
        raise ValueError(f"pointer/archive must not be a symlink: {path}")
    return path.read_bytes() if path.exists() else None


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_directory(path.parent)
    if _bytes(path) != content:
        raise OSError(f"archive readback mismatch: {path}")


def _replace(target: Path, content: bytes | None) -> None:
    if content is None:
        target.unlink(missing_ok=True)
    else:
        with NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                os.chmod(temporary, 0o644)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    _sync_directory(target.parent)
    if _bytes(target) != content:
        raise OSError(f"published pointer readback mismatch: {target}")


def pointer_transaction(
    target: Path,
    archive: Path,
    lock: Path = PUBLICATION_LOCK,
    *,
    snapshot: bool = False,
    source: Path | None = None,
    restore: bool = False,
) -> None:
    """Archive/CAS the exact pointer bytes. Never rebuild or delete installer payloads."""
    with publication_lock(lock):
        identity = str(target.resolve())
        current = _bytes(target)
        if snapshot:
            archive.mkdir(parents=True, exist_ok=False)
            if current is not None:
                _durable(archive / "previous", current)
            metadata = {
                "target": identity,
                "previous_sha256": (
                    hashlib.sha256(current).hexdigest() if current is not None else None
                ),
            }
            _durable(archive / "snapshot.json", json.dumps(metadata).encode())
            _sync_directory(archive.parent)
            return
        metadata = json.loads((archive / "snapshot.json").read_bytes())
        previous = _bytes(archive / "previous")
        digest = hashlib.sha256(previous).hexdigest() if previous is not None else None
        if metadata != {"target": identity, "previous_sha256": digest}:
            raise ValueError(
                "pointer target or archived bytes changed; reconcile explicitly"
            )
        replacement = _bytes(archive / "replacement")
        if restore:
            if replacement is None or current != replacement:
                raise ValueError(
                    "rollback refused: current pointer belongs to another publication"
                )
            _replace(target, previous)
            return
        if source is None or current != previous:
            raise ValueError("promotion refused: expected public pointer bytes changed")
        incoming = source.read_bytes()
        data = json.loads(incoming)
        if not isinstance(data, dict) or not data:
            raise ValueError("invalid incoming public pointer")
        if replacement is not None:
            raise ValueError(
                "archive already used; publication requires a fresh snapshot"
            )
        _durable(archive / "replacement", incoming)
        try:
            _replace(target, incoming)
        except OSError:
            # A failed readback may only restore our own bytes, never a later writer.
            if _bytes(target) == incoming:
                _replace(target, previous)
            raise


def preserve(
    site_root: Path,
    published_site_root: Path,
    published_hotfix: Path | None = None,
    *,
    check: bool = False,
) -> None:
    # Validate the complete source set before changing the staged tree. Preserve bytes,
    # including unresolved legacy identity; do not turn preservation into acceptance.
    if not site_root.is_dir():
        raise ValueError(f"missing staged site: {site_root}")
    snapshots: dict[str, bytes | None] = {}
    for name in POINTERS:
        source = (
            published_hotfix
            if name == POINTERS[1] and published_hotfix
            else published_site_root / name
        )
        if not source.exists() and name != POINTERS[0]:
            snapshots[name] = None
            continue
        published_bytes = source.read_bytes()
        data = json.loads(published_bytes)
        if not isinstance(data, dict) or not data:
            raise ValueError(f"invalid published pointer: {source}")
        snapshots[name] = published_bytes
    for name, content in snapshots.items():
        for root in (site_root, *(site_root / mirror for mirror in MIRRORS)):
            if not root.is_dir():
                continue
            target = root / name
            if target.is_symlink() or not root.resolve().is_relative_to(
                site_root.resolve()
            ):
                raise ValueError(
                    f"prepared pointer must be local, not a symlink: {target}"
                )
            if check:
                actual = target.read_bytes() if target.is_file() else None
                if actual != content or (content is None and target.exists()):
                    raise ValueError(
                        f"stale prepared desktop pointer; explicit reconciliation required: {target}"
                    )
            elif content is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(content)
                if target.read_bytes() != content:
                    raise OSError(f"pointer preservation failed: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", type=Path)
    parser.add_argument("--published-site-root", type=Path)
    parser.add_argument("--published-hotfix", type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Read-only byte/absence parity before activation or rollback",
    )
    parser.add_argument("--pointer-target", type=Path)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--publication-lock", type=Path, default=PUBLICATION_LOCK)
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--snapshot", action="store_true")
    operation.add_argument("--promote-source", type=Path)
    operation.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    try:
        if args.snapshot or args.promote_source or args.restore:
            if not args.pointer_target or not args.archive_dir:
                parser.error(
                    "pointer operations require --pointer-target and --archive-dir"
                )
            pointer_transaction(
                args.pointer_target,
                args.archive_dir,
                args.publication_lock,
                snapshot=args.snapshot,
                source=args.promote_source,
                restore=args.restore,
            )
        else:
            if not args.site_root or not args.published_site_root:
                parser.error(
                    "preservation requires --site-root and --published-site-root"
                )
            preserve(
                args.site_root,
                args.published_site_root,
                args.published_hotfix,
                check=args.check,
            )
    except (OSError, ValueError) as exc:
        print(
            f"[error] cannot preserve public desktop pointers: {exc}", file=sys.stderr
        )
        return 1
    print("[ok] public desktop pointer operation verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
