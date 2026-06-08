#!/usr/bin/env python3
"""校验 deploy/requirements-server-api.txt 与 lock 文件顶层包名一致。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "deploy" / "requirements-server-api.txt"
LOCK = ROOT / "deploy" / "requirements-server-api.lock.txt"

PKG_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*([=<>!~]+.*)?$")


def normalize_name(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def parse_requirements(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        base = line.split("[", 1)[0].strip()
        m = PKG_RE.match(base)
        if m:
            names.add(normalize_name(m.group(1)))
    return names


def parse_lock(path: Path) -> set[str]:
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " via " in line or line.startswith("    #"):
            continue
        pkg = line.split("==", 1)[0].strip()
        if pkg:
            names.add(normalize_name(pkg))
    return names


def main() -> int:
    if not REQ.is_file():
        print(f"missing {REQ}", file=sys.stderr)
        return 1
    if not LOCK.is_file():
        print(f"missing {LOCK}", file=sys.stderr)
        return 1

    req_names = parse_requirements(REQ)
    lock_names = parse_lock(LOCK)
    missing = sorted(req_names - lock_names)
    if missing:
        print("lock file missing top-level packages from requirements-server-api.txt:", file=sys.stderr)
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print("Regenerate: pip install -r deploy/requirements-server-api.txt && pip freeze > deploy/requirements-server-api.lock.txt", file=sys.stderr)
        return 1
    print(f"requirements lock OK ({len(req_names)} top-level packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
