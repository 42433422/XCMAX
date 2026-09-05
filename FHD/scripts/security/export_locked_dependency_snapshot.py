#!/usr/bin/env python3
"""Export every pin in the shipped Python lockfiles at an immutable Git commit.

Use one stable detector/correlator when submitting successive snapshots. Changing
that identity per commit can retain old snapshots alongside the current pins.
This reports lockfile contents only; production-image and host scans stay required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

LOCKFILES = (
    "FHD/XCAGI/requirements.lock.txt",
    "FHD/deploy/requirements-server-api.lock.txt",
)
DETECTOR = "xcmax-locked-python"
CORRELATOR = "xcmax-locked-python-main"
PIN = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9][A-Za-z0-9.!+_-]*)"
)


def parse_pins(content: str) -> dict[str, dict[str, str]]:
    """Reject unsupported lines instead of silently omitting dependencies."""
    resolved: dict[str, dict[str, str]] = {}
    for number, raw in enumerate(content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.fullmatch(line)
        if not match:
            raise ValueError(f"line {number}: expected one exact package==version pin")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in resolved:
            raise ValueError(f"line {number}: duplicate package {name}")
        resolved[name] = {"package_url": f"pkg:pypi/{name}@{quote(match[2], safe='.-')}"}
    if not resolved:
        raise ValueError("lockfile has no pinned dependencies")
    return resolved


def build_snapshot(root: Path, sha: str, job_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("sha must be a full lowercase Git commit SHA")
    if not job_id.strip():
        raise ValueError("job_id is required")
    manifests = {}
    for filename in LOCKFILES:
        raw = subprocess.run(
            ["git", "show", f"{sha}:{filename}"],
            cwd=root,
            check=True,
            capture_output=True,
        ).stdout
        manifests[filename] = {
            "name": filename,
            "file": {"source_location": filename},
            "metadata": {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_kind": "all_declared_lockfile_pins",
            },
            "resolved": parse_pins(raw.decode("utf-8")),
        }
    return {
        "version": 0,
        "sha": sha,
        "ref": "refs/heads/main",
        "job": {"id": job_id, "correlator": CORRELATOR},
        "detector": {
            "name": DETECTOR,
            "version": "1.0.0",
            "url": "https://github.com/42433422/XCMAX/blob/main/FHD/scripts/security/export_locked_dependency_snapshot.py",
        },
        "scanned": datetime.now(UTC).isoformat(),
        "manifests": manifests,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--sha", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = build_snapshot(args.repo_root, args.sha, args.job_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "sha": args.sha,
                "manifests": {
                    name: len(manifest["resolved"])
                    for name, manifest in snapshot["manifests"].items()
                },
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
