#!/usr/bin/env python3
"""扫描 app/fastapi_routes 与 mods blueprints 的路由装饰器，标记疑似 stub/legacy。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = [
    ROOT / "app" / "fastapi_routes",
    ROOT / "mods",
]

ROUTE_RE = re.compile(
    r"@(?:router|bp|app)\.(?:get|post|put|patch|delete|api_route)\(\s*[\"']([^\"']+)"
)
LEGACY_RE = re.compile(r"legacy_|xcagi_compat_|/health|/ping|/status")


def scan_file(path: Path) -> list[tuple[str, str, str]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.relative_to(ROOT))
    out: list[tuple[str, str, str]] = []
    for m in ROUTE_RE.finditer(text):
        route = m.group(1)
        tag = "legacy" if LEGACY_RE.search(rel + route) else "normal"
        if route in ("/health", "/ping", "/api/health"):
            tag = "health"
        out.append((rel, route, tag))
    return out


def main() -> int:
    rows: list[tuple[str, str, str]] = []
    for base in SCAN_DIRS:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rows.extend(scan_file(path))
    legacy = [r for r in rows if r[2] == "legacy"]
    health = [r for r in rows if r[2] == "health"]
    print(f"total routes: {len(rows)}")
    print(f"legacy/compat/health tagged: {len(legacy) + len(health)}")
    for rel, route, tag in legacy[:80]:
        print(f"[{tag}] {rel} {route}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
