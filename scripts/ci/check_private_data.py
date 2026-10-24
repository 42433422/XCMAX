#!/usr/bin/env python3
"""Reject private runtime data from the Git index, including embedded copies.

Reading staged blobs (not working files) also catches ``git add -f`` and renamed
copies. Customer originals belong in external, account-scoped runtime storage.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_SUFFIXES = {".zip", ".xcemp", ".xcmod", ".xlsx", ".xlsm", ".docx", ".pptx"}
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 3


def private_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if "employee_draft_assets" in parts:
        return True
    if path.startswith(("outputs/", "FHD/dataset_rag/")):
        return True
    if path.startswith("FHD/delivery/sunbird-seed/"):
        return path != "FHD/delivery/sunbird-seed/README.md"
    name = PurePosixPath(path).name
    if name.startswith("_conv_") and name.endswith((".xlsx", ".xlsm")):
        return True
    return path.startswith("FHD/.cursor/") and name.endswith((".docx", ".xlsx", ".xls"))


def inspect_blob(
    path: str, data: bytes, blocked: set[str], *, depth: int = 0
) -> list[str]:
    if hashlib.sha256(data).hexdigest() in blocked:
        return [f"{path}: archived private-data fingerprint"]
    if PurePosixPath(
        path
    ).suffix.lower() not in ARCHIVE_SUFFIXES and not data.startswith(
        (b"PK\x03\x04", b"PK\x05\x06")
    ):
        return []
    if not zipfile.is_zipfile(io.BytesIO(data)):
        return [f"{path}: invalid or uninspectable archive"]
    if depth >= MAX_ARCHIVE_DEPTH:
        return [f"{path}: nested archive exceeds inspection depth"]
    errors = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED_BYTES:
                return [f"{path}: archive exceeds inspection size budget"]
            for entry in entries:
                member = entry.filename.replace("\\", "/")
                label = f"{path}!{member}"
                if private_path(member):
                    errors.append(f"{label}: private runtime path")
                errors.extend(
                    inspect_blob(label, archive.read(entry), blocked, depth=depth + 1)
                )
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, NotImplementedError):
        errors.append(f"{path}: archive contents cannot be inspected")
    return errors


def check_index(root: Path, blocked: set[str]) -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=root)
    errors: list[str] = []
    # One batch process keeps the full-tree gate inexpensive even in a monorepo.
    objects: dict[str, list[str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, name = record.split(b"\t", 1)
        mode, oid, stage = meta.decode().split()
        path = name.decode("utf-8")
        if stage != "0":
            errors.append(f"{path}: unresolved index entry")
            continue
        if mode == "160000":
            continue
        if private_path(path):
            errors.append(f"{path}: private runtime path")
        objects.setdefault(oid, []).append(path)
    with subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    ) as proc:
        assert proc.stdin is not None and proc.stdout is not None
        for oid, paths in objects.items():
            proc.stdin.write(oid.encode() + b"\n")
            proc.stdin.flush()
            header = proc.stdout.readline().decode().split()
            if len(header) != 3 or header[1] != "blob":
                raise RuntimeError(f"cannot inspect Git blob {oid}")
            data = proc.stdout.read(int(header[2]))
            if proc.stdout.read(1) != b"\n":
                raise RuntimeError("invalid Git batch response")
            # A blob may be renamed with another extension; inspect archive copies too.
            path = next(
                (
                    p
                    for p in paths
                    if PurePosixPath(p).suffix.lower() in ARCHIVE_SUFFIXES
                ),
                paths[0],
            )
            findings = inspect_blob(path, data, blocked)
            errors.extend(findings)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("Git blob inspection failed")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args()
    policy = json.loads(
        Path(__file__).with_name("private_data_fingerprints.json").read_text()
    )
    errors = check_index(args.root.resolve(), set(policy["blocked_sha256"]))
    for error in errors:
        print(error)
    print(f"private-data gate: {len(errors)} violation(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
