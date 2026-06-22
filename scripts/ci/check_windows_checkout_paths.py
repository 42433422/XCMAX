#!/usr/bin/env python3
"""Fail when tracked paths cannot be checked out on Windows."""

from __future__ import annotations

import subprocess
import sys


WINDOWS_INVALID_CHARS = set('<>:"|?*')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _tracked_paths() -> list[str]:
    output = subprocess.check_output(["git", "ls-files", "-z"])
    return [
        raw.decode("utf-8", "surrogateescape")
        for raw in output.split(b"\0")
        if raw
    ]


def _windows_component_error(component: str) -> str | None:
    if any(char in WINDOWS_INVALID_CHARS for char in component):
        return "contains a Windows-invalid character"
    if component.endswith(" ") or component.endswith("."):
        return "ends with a space or dot"

    stem = component.split(".", 1)[0].upper()
    if stem in WINDOWS_RESERVED_NAMES:
        return "uses a Windows reserved device name"

    return None


def _bad_paths(paths: list[str]) -> list[tuple[str, str, str]]:
    bad: list[tuple[str, str, str]] = []
    for path in paths:
        for component in path.split("/"):
            error = _windows_component_error(component)
            if error:
                bad.append((path, component, error))
                break
    return bad


def main() -> int:
    bad = _bad_paths(_tracked_paths())
    if not bad:
        print("Windows checkout path check passed.")
        return 0

    print("Tracked paths that cannot be checked out on Windows:", file=sys.stderr)
    for path, component, error in bad:
        print(f"- {path} ({component!r}: {error})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
