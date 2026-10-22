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
    ".install-receipts",
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
    "scripts/deploy/xcmax-release-sync.sh",
    "scripts/deploy/xcmax_release_sync_prune.py",
    "scripts/deploy/lib/mod_tree_guard.py",
    "scripts/deploy/lib/verify_release_archive.py",
    "scripts/deploy/lib/service_quiescence.sh",
    "scripts/deploy/lib/apply_recovery.sh",
    "scripts/deploy/lib/version.sh",
    "scripts/deploy/fhd-load-release-image.sh",
    "scripts/autonomy/corp_site_health_probe.py",
    "scripts/autonomy/cvm_autonomy_watcher.py",
    "scripts/ci/_approval_ledger_client.py",
    "scripts/ci/_im_notify_client.py",
}


def _normalise(raw_name: str) -> str:
    # Tar archives produced by fhd-pack-release use a single leading ./.
    # Strip only that prefix; reject internal dot, empty, and parent components
    # rather than accepting multiple spellings for the same extracted path.
    raw_name = raw_name.removeprefix("./")
    raw_name = raw_name.rstrip("/")
    if raw_name in ("", "."):
        return ""
    if raw_name.startswith("/"):
        return raw_name
    parts = raw_name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return raw_name
    return "/".join(parts)


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
    entries: dict[str, tarfile.TarInfo] = {}
    violations: list[str] = []
    file_count = 0
    try:
        archive = tarfile.open(path, mode="r:*")
    except (OSError, tarfile.TarError) as exc:
        raise ValueError(f"cannot read release archive: {exc}") from exc

    with archive:
        for member in archive.getmembers():
            if not member.name:
                violations.append("unnamed archive member is forbidden")
            if member.name.startswith("/"):
                violations.append(f"unsafe member path: {member.name}")
            name = _normalise(member.name)
            if not name:
                if not member.isdir():
                    violations.append("archive root member must be a directory")
                continue
            if name in seen:
                violations.append(f"duplicate member target: {name}")
            seen.add(name)
            entries[name] = member
            if name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/")):
                violations.append(f"unsafe member path: {member.name}")
            if name != member.name.removeprefix("./").rstrip("/"):
                violations.append(f"non-canonical member path: {member.name}")
            if reason := _forbidden_reason(name):
                violations.append(f"{name}: {reason}")
            if member.isdev():
                violations.append(f"device member is forbidden: {name}")
            if member.isfile():
                file_count += 1
            # Release payloads contain regular files/directories. Refuse all
            # links so chained aliases cannot write or expose another path.
            if member.issym() or member.islnk():
                violations.append(f"release archive links are forbidden: {name}")

    symlinks = {name for name, member in entries.items() if member.issym()}
    for name, member in entries.items():
        parts = name.split("/")
        for end in range(1, len(parts)):
            parent = "/".join(parts[:end])
            if parent in symlinks:
                violations.append(f"member traverses symlink parent: {name} via {parent}")
                break
    missing = sorted(REQUIRED_RUNTIME_MEMBERS.difference(seen))
    if missing:
        violations.append("missing required runtime members: " + ", ".join(missing))
    for name in REQUIRED_RUNTIME_MEMBERS.intersection(entries):
        if not entries[name].isfile():
            violations.append("required runtime member is not a regular file: " + name)

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
