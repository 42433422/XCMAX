#!/usr/bin/env python3
"""Export immutable lockfile pins under one stable detector/correlator.

Image and host scans remain required; all uv platform versions are included.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

LOCKFILES = (
    "FHD/XCAGI/requirements.lock.txt",
    "FHD/deploy/requirements-server-api.lock.txt",
    "FHD/uv.lock",
)
DETECTOR = "xcmax-locked-python"
CORRELATOR = "xcmax-locked-python-main"
PIN = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?==([A-Za-z0-9][A-Za-z0-9.!+_-]*)"
)


def parse_pins(content: str, *, multiple_versions: bool = False) -> dict[str, dict[str, str]]:
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
        key = f"{name}@{match[2]}" if multiple_versions else name
        if key in resolved:
            raise ValueError(f"line {number}: duplicate package {name}")
        resolved[key] = {"package_url": f"pkg:pypi/{name}@{quote(match[2], safe='.-')}"}
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
        raw = subprocess.check_output(
            ["git", "show", f"{sha}:{filename}"], cwd=root, stderr=subprocess.PIPE
        )
        content = raw.decode("utf-8")
        uv = filename.endswith("uv.lock")
        if uv:
            content = "\n".join(
                f"{p['name']}=={p['version']}" for p in tomllib.loads(content)["package"]
            )
        manifests[filename] = {
            "name": filename,
            "file": {"source_location": filename},
            "metadata": {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "source_kind": "all_declared_lockfile_pins",
            },
            "resolved": parse_pins(content, multiple_versions=uv),
        }
    return {
        "version": 0,
        "sha": sha,
        "ref": "refs/heads/main",
        "job": {"id": job_id, "correlator": CORRELATOR},
        "detector": {
            "name": DETECTOR,
            "version": "1.1.0",
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
    counts = {name: len(manifest["resolved"]) for name, manifest in snapshot["manifests"].items()}
    print(json.dumps({"sha": args.sha, "manifests": counts}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
