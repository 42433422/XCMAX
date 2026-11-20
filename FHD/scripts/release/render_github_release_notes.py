#!/usr/bin/env python3
"""Render GitHub release notes from the same published pointer used by the download UI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_formal_release_identity import manifest_url, published_pointer_errors


def render(pointer: dict, version: str, sha: str) -> str:
    errors = published_pointer_errors(pointer, version, sha)
    if errors:
        raise ValueError("download release identity: " + ", ".join(errors))
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
    url = pointer.get("manifest_url")
    if url != manifest_url(version, sha):
        raise ValueError("public manifest URL does not match the frozen build")
    bullets = "\n".join(f"- {note.strip()}" for note in notes)
    return (
        f"# XCAGI {version} — {title.strip()}\n\n"
        f"{bullets}\n\n"
        f"Source SHA: `{sha}`\n\n"
        f"Published artifact manifest: {url}\n"
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
