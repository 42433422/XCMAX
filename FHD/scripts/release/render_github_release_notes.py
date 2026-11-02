#!/usr/bin/env python3
"""Render GitHub release notes from the same published pointer used by the download UI."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")


def render(pointer: dict, version: str, sha: str) -> str:
    if (
        not _SHA.fullmatch(sha)
        or pointer.get("schema") != "xcagi.download_release.public/v1"
        or pointer.get("release_ready") is not True
        or pointer.get("version_lock") != version
        or pointer.get("download_version") != version
        or pointer.get("git_sha") != sha
        or pointer.get("release_id") != f"xcagi-{version}-{sha}"
    ):
        raise ValueError("download release identity does not match frozen published build")
    history = pointer.get("release_history")
    if not isinstance(history, list) or not history:
        raise ValueError("release history is missing")
    current = history[0]
    title = current.get("title") if isinstance(current, dict) else None
    notes = current.get("notes") if isinstance(current, dict) else None
    if (
        not isinstance(current, dict)
        or current.get("version") != version
        or not isinstance(title, str) or not title.strip()
        or not isinstance(notes, list) or not notes
        or not all(isinstance(n, str) and n.strip() for n in notes)
    ):
        raise ValueError("release notes are missing from the authoritative version history")
    manifest_url = pointer.get("manifest_url")
    if manifest_url != f"https://xiu-ci.com/xcagi-v{version}/manifest.json":
        raise ValueError("public manifest URL does not match the version")
    bullets = "\n".join(f"- {note.strip()}" for note in notes)
    return (
        f"# XCAGI {version} — {title.strip()}\n\n"
        f"{bullets}\n\n"
        f"Source SHA: `{sha}`\n\n"
        f"Published artifact manifest: {manifest_url}\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    pointer = json.loads(args.pointer.read_text(encoding="utf-8"))
    content = render(pointer, args.version, args.sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
