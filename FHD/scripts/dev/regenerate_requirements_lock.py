#!/usr/bin/env python3
"""从本机已安装的 server-api 依赖重新生成 deploy/requirements-server-api.lock.txt。"""
from __future__ import annotations

import re
import sys
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "deploy" / "requirements-server-api.txt"
LOCK = ROOT / "deploy" / "requirements-server-api.lock.txt"

PKG_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def parse_top_level(path: Path) -> list[str]:
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        base = line.split("[", 1)[0].strip()
        m = PKG_RE.match(base)
        if m:
            names.append(m.group(1))
    return names


def main() -> int:
    installed: dict[str, str] = {}
    for dist in distributions():
        installed[normalize(dist.metadata["Name"])] = dist.version

    lines = [
        "# Top-level pins from local pip install (deploy/requirements-server-api.txt)",
        "# Regenerate: pip install -r deploy/requirements-server-api.txt && python3 scripts/dev/regenerate_requirements_lock.py",
    ]
    missing: list[str] = []
    for pkg in parse_top_level(REQ):
        ver = installed.get(normalize(pkg))
        if not ver:
            missing.append(pkg)
            continue
        lines.append(f"{pkg}=={ver}")

    if missing:
        print("install missing packages first:", ", ".join(missing), file=sys.stderr)
        print("  pip install -r deploy/requirements-server-api.txt", file=sys.stderr)
        return 1

    LOCK.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {LOCK} ({len(lines) - 2} packages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
