#!/usr/bin/env python3
"""Add archive banners to historical docs (idempotent)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
CONFIG = FHD_ROOT / "config" / "docs_archive.json"


def start_here_href(file_path: Path) -> str:
    rel = file_path.relative_to(FHD_ROOT / "docs")
    depth = len(rel.parts) - 1
    return "/".join([".."] * depth) + ("START_HERE.md" if depth else "START_HERE.md")


def banner_for(path: Path, template: str) -> str:
    href = start_here_href(path)
    if not href.startswith("../") and path.parent.name != "docs":
        prefix = "../" * len(path.relative_to(FHD_ROOT / "docs").parts)
        href = prefix + "START_HERE.md"
    # normalize: from docs/reports/foo.md -> ../START_HERE.md
    parts = path.relative_to(FHD_ROOT / "docs").parts
    href = "/".join([".."] * len(parts[:-1]) + ["START_HERE.md"])
    return "\n" + template.format(start_here=href) + "\n"


def collect_targets(data: dict) -> list[Path]:
    out: list[Path] = []
    for rel in data.get("root_archive_files") or []:
        p = FHD_ROOT / rel
        if p.is_file():
            out.append(p)
    excludes = tuple(data.get("exclude_suffixes") or [])
    for pattern in data.get("globs") or []:
        for p in sorted(FHD_ROOT.glob(pattern)):
            if not p.is_file() or p.name in excludes:
                continue
            out.append(p)
    # dedupe
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in out:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def stamp_file(path: Path, marker: str, template: str, check_only: bool) -> bool:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return True
    if check_only:
        return False
    body = banner_for(path, template)
    # insert after optional YAML front matter
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            insert_at = end + len("\n---\n")
            new_text = text[:insert_at] + body + text[insert_at:]
        else:
            new_text = body + text
    else:
        new_text = body + text
    path.write_text(marker + "\n" + new_text, encoding="utf-8")
    return True


def main() -> int:
    check_only = "--check" in sys.argv
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    marker = data["marker"]
    template = data["banner_template"]
    missing: list[str] = []
    stamped = 0
    for path in collect_targets(data):
        ok = stamp_file(path, marker, template, check_only)
        if not ok:
            missing.append(str(path.relative_to(FHD_ROOT)))
        elif not check_only and marker not in path.read_text(encoding="utf-8"):
            stamped += 1
    if check_only and missing:
        print("Archive banner check FAILED:", file=sys.stderr)
        for m in missing[:20]:
            print(f"  - {m}", file=sys.stderr)
        if len(missing) > 20:
            print(f"  ... and {len(missing) - 20} more", file=sys.stderr)
        return 1
    if check_only:
        print(f"OK: archive banners on {len(collect_targets(data))} files")
        return 0
    print(f"Stamped {stamped} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
