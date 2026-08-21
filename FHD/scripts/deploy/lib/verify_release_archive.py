#!/usr/bin/env python3
"""Reject unsafe or local-only members in an FHD release archive."""

from __future__ import annotations

import argparse
import json
import sys
import tarfile
from pathlib import Path, PurePosixPath

FORBIDDEN_PARTS = {
    ".DS_Store",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".secrets",
    ".venv",
    "__pycache__",
    "node_modules",
}
FORBIDDEN_SUFFIXES = (".pyc", ".pyo")
REQUIRED_RUNTIME_MEMBERS = {
    ".build-identity.json",
    "requirements-langgraph-runtime.txt",
    "templates/admin-vue-dist/index.html",
    "packages/xcagi_langgraph_core/langgraph/graph/state.py",
    "packages/xcagi_langgraph_checkpoint/langgraph/checkpoint/base/__init__.py",
    "packages/xcagi_langgraph_checkpoint_backends/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py",
    "packages/xcagi_langgraph_checkpoint_backends/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py",
    "packages/xcagi_langgraph_prebuilt/langgraph/prebuilt/tool_node.py",
    "packages/xcagi_langgraph_sdk/langgraph_sdk/client.py",
}


def _normalise(raw_name: str) -> str:
    while raw_name.startswith("./"):
        raw_name = raw_name[2:]
    return raw_name.rstrip("/")


def _safe_relative(raw_path: str, base: PurePosixPath | None = None) -> bool:
    path = PurePosixPath(raw_path)
    if path.is_absolute():
        return False
    stack = list((base or PurePosixPath()).parts)
    for part in path.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                return False
            stack.pop()
        else:
            stack.append(part)
    return True


def _forbidden_reason(name: str) -> str | None:
    for part in PurePosixPath(name).parts:
        if part in FORBIDDEN_PARTS:
            return f"forbidden path component: {part}"
        if part.startswith("._"):
            return "AppleDouble metadata is forbidden"
        if part == ".env" or part.startswith(".env."):
            return "environment files are forbidden"
    if name.endswith(FORBIDDEN_SUFFIXES):
        return "Python bytecode is forbidden"
    return None


def verify_archive(path: Path) -> dict[str, int | str]:
    seen: set[str] = set()
    violations: list[str] = []
    file_count = 0
    try:
        archive = tarfile.open(path, mode="r:*")
    except (OSError, tarfile.TarError) as exc:
        raise ValueError(f"cannot read release archive: {exc}") from exc

    with archive:
        for member in archive.getmembers():
            name = _normalise(member.name)
            if not name:
                continue
            if name in seen:
                violations.append(f"duplicate member: {name}")
            seen.add(name)
            if not _safe_relative(name):
                violations.append(f"unsafe member path: {member.name}")
            if reason := _forbidden_reason(name):
                violations.append(f"{name}: {reason}")
            if member.isdev():
                violations.append(f"device member is forbidden: {name}")
            if member.isfile():
                file_count += 1
            if member.issym() and not _safe_relative(member.linkname, PurePosixPath(name).parent):
                violations.append(f"unsafe symlink target: {name} -> {member.linkname}")
            if member.islnk() and not _safe_relative(member.linkname):
                violations.append(f"unsafe hardlink target: {name} -> {member.linkname}")

    missing = sorted(REQUIRED_RUNTIME_MEMBERS.difference(seen))
    if missing:
        violations.append("missing required runtime members: " + ", ".join(missing))

    if violations:
        preview = "; ".join(violations[:12])
        if len(violations) > 12:
            preview += f"; ... and {len(violations) - 12} more"
        raise ValueError(preview)
    return {
        "archive": str(path),
        "files": file_count,
        "members": len(seen),
        "status": "verified",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = verify_archive(args.archive)
    except ValueError as exc:
        print(f"[err] release archive verification failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
