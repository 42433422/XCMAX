#!/usr/bin/env python3
"""Select DR release components without allowing automatic rollback."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENTS = ("modstore", "fhd")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_timestamp(path: Path) -> int:
    value = read_text(path)
    return int(value) if value.isdigit() else 0


def current_timestamp(incoming: Path, state: Path, component: str) -> int:
    timestamp = read_timestamp(state / f"release_applied_{component}_created_at")
    if timestamp:
        return timestamp

    current_sha = read_text(state / f"release_applied_{component}_sha")
    if not SHA_RE.fullmatch(current_sha):
        return 0
    return read_timestamp(incoming / current_sha / f"{component}.CREATED_AT")


def should_apply(incoming: Path, state: Path, candidate: Path, component: str) -> bool:
    sha = candidate.name
    if not SHA_RE.fullmatch(sha):
        return False
    if not (candidate / f"{component}.MANIFEST.txt").is_file():
        return False
    if read_text(state / f"release_applied_{component}_sha") == sha:
        return False
    candidate_timestamp = read_timestamp(candidate / f"{component}.CREATED_AT")
    return candidate_timestamp > 0 and candidate_timestamp > current_timestamp(
        incoming, state, component
    )


def select_release(incoming: Path, state: Path) -> Path | None:
    candidates: list[tuple[int, str, Path]] = []
    if not incoming.is_dir():
        return None

    for candidate in incoming.iterdir():
        if not candidate.is_dir() or not SHA_RE.fullmatch(candidate.name):
            continue
        component_timestamps = [
            read_timestamp(candidate / f"{component}.CREATED_AT")
            for component in COMPONENTS
            if should_apply(incoming, state, candidate, component)
        ]
        if component_timestamps:
            candidates.append((max(component_timestamps), candidate.name, candidate))
    if not candidates:
        return None
    return max(candidates)[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incoming", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("select")

    should_parser = subparsers.add_parser("should-apply")
    should_parser.add_argument("--candidate", type=Path, required=True)
    should_parser.add_argument("--component", choices=COMPONENTS, required=True)

    timestamp_parser = subparsers.add_parser("created-at")
    timestamp_parser.add_argument("--candidate", type=Path, required=True)
    timestamp_parser.add_argument("--component", choices=COMPONENTS, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "select":
        selected = select_release(args.incoming, args.state)
        if selected is not None:
            print(selected)
        return 0
    if args.command == "should-apply":
        return (
            0
            if should_apply(args.incoming, args.state, args.candidate, args.component)
            else 3
        )

    timestamp = read_timestamp(args.candidate / f"{args.component}.CREATED_AT")
    if timestamp <= 0:
        return 4
    print(timestamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
