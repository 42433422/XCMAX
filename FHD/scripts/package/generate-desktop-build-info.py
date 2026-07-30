#!/usr/bin/env python3
"""Generate the immutable desktop build identity copied into packaged apps."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

try:
    from datetime import UTC, datetime
except ImportError:  # Python < 3.11
    from datetime import datetime, timezone

    UTC = timezone.utc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "desktop" / "resources" / "build-info.json"
GIT_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


def resolve_git_sha(explicit: str | None = None) -> str:
    candidates = (
        explicit,
        os.environ.get("GITHUB_SHA"),
        os.environ.get("XCAGI_BUILD_SHA"),
    )
    git_sha = next(
        (str(value).strip() for value in candidates if str(value or "").strip()), ""
    )
    if not git_sha:
        git_sha = subprocess.check_output(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    if not GIT_SHA_PATTERN.fullmatch(git_sha):
        raise ValueError(
            f"desktop build identity requires a full Git SHA, got: {git_sha!r}"
        )
    return git_sha.lower()


def write_build_info(*, version: str, git_sha: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "gitSha": git_sha,
        "version": version,
        "builtAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }
    output.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--git-sha")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    git_sha = resolve_git_sha(args.git_sha)
    write_build_info(version=args.version, git_sha=git_sha, output=args.output)
    print(git_sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
