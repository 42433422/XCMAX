#!/usr/bin/env python3
"""Select old DR incoming releases that can be removed before upload."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENTS = ("modstore", "fhd")


def parse_component_releases(
    lines: list[str], component: str
) -> list[tuple[datetime, str]]:
    marker_suffix = f"/{component}.SHA"
    releases: dict[str, datetime] = {}

    for raw_line in lines:
        parts = raw_line.split(maxsplit=4)
        if len(parts) != 5 or not parts[0].startswith("-"):
            continue
        date_text, time_text, path = parts[2], parts[3], parts[4]
        if not path.endswith(marker_suffix):
            continue
        sha, separator, marker = path.partition("/")
        if (
            separator != "/"
            or marker != f"{component}.SHA"
            or not SHA_RE.fullmatch(sha)
        ):
            raise ValueError("invalid remote release marker")
        try:
            modified_at = datetime.strptime(
                f"{date_text} {time_text}", "%Y/%m/%d %H:%M:%S"
            )
        except ValueError as exc:
            raise ValueError("invalid remote release timestamp") from exc
        releases[sha] = modified_at

    return sorted((modified_at, sha) for sha, modified_at in releases.items())


def select_victims(
    lines: list[str], component: str, target_sha: str, keep: int
) -> list[str]:
    if component not in COMPONENTS:
        raise ValueError("invalid component")
    if not SHA_RE.fullmatch(target_sha):
        raise ValueError("invalid target sha")
    if keep < 2:
        raise ValueError("incoming component keep must be at least 2")

    releases = parse_component_releases(lines, component)
    if any(sha == target_sha for _, sha in releases):
        return []

    remove_count = max(0, len(releases) + 1 - keep)
    return [sha for _, sha in releases[:remove_count]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--component", choices=COMPONENTS, required=True)
    parser.add_argument("--target-sha", required=True)
    parser.add_argument("--keep", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        victims = select_victims(
            sys.stdin.read().splitlines(),
            args.component,
            args.target_sha,
            args.keep,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for victim in victims:
        print(victim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
