#!/usr/bin/env python3
"""扫描 docs/ 产品版本表述是否与 VERSION.md 锚点 10.0.0 对齐。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERSION_MD = REPO / "VERSION.md"
DOCS = REPO / "docs"

# 历史 CHANGELOG 节标题允许旧版本
SKIP_FILES = {
    "CHANGELOG.md",
    "CLAIMED_VS_ACTUAL.md",
}

SKIP_DIR_PARTS = {
    "reports",  # 历史对比/留证，允许旧版本叙述
    "legal",
    "evidence",
}

# 匹配对外产品版本 7.x / 8.x（非依赖版本如 python 3.11）
BAD_PATTERNS = [
    re.compile(r"\bXCAGI\s*v?8\.0(?:\.0)?\b", re.I),
    re.compile(r"\bXCAGI\s*v?7\.0(?:\.0)?\b", re.I),
    re.compile(r"\bxcagi:8\.0\b", re.I),
    re.compile(r"\bxcagi:7\.0\b", re.I),
    re.compile(r"镜像.*xcagi:7\.0", re.I),
    re.compile(r"Version\s+8\.0\.0", re.I),
    re.compile(r"Setup\s+8\.0\.0", re.I),
]


def expected_version() -> str:
    text = VERSION_MD.read_text(encoding="utf-8")
    m = re.search(r"^\|\s*\*\*产品版本\*\*\s*\|\s*`([^`]+)`", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"10\.0\.0", text)
    return m.group(0) if m else "10.0.0"


def main() -> int:
    if not DOCS.is_dir():
        print("docs/ missing", file=sys.stderr)
        return 1
    anchor = expected_version()
    violations: list[str] = []
    for path in sorted(DOCS.rglob("*.md")):
        if path.name in SKIP_FILES:
            continue
        if SKIP_DIR_PARTS.intersection(path.parts):
            continue
        if "software-copyright" in path.parts:
            continue
        rel = path.relative_to(REPO)
        for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if any(k in line for k in ("历史", "曾使用", "原 v", "当时对比", "升级到 v7")):
                continue
            for pat in BAD_PATTERNS:
                if pat.search(line):
                    violations.append(f"{rel}:{i}: {line.strip()[:120]}")
    if violations:
        print(f"Doc version drift vs anchor {anchor} ({len(violations)} hits):", file=sys.stderr)
        for v in violations[:50]:
            print(f"  - {v}", file=sys.stderr)
        if len(violations) > 50:
            print(f"  ... and {len(violations) - 50} more", file=sys.stderr)
        return 1
    print(f"OK: docs/*.md aligned with product anchor {anchor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
