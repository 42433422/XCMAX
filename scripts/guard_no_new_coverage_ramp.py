#!/usr/bin/env python3
"""Pre-commit / CI: block newly added test_coverage_ramp_phase* test files."""

from __future__ import annotations

import re
import sys
from pathlib import Path

BANNED = re.compile(r"test_coverage_ramp_phase\d+", re.IGNORECASE)
ALLOWED_PREFIXES = (
    "FHD/tests/",
    "成都修茈科技有限公司/MODstore_deploy/tests/",
    "成都修茈科技有限公司/vibe-coding/tests/",
    "packages/",
)


def _is_test_path(path: str) -> bool:
    p = path.replace("\\", "/")
    if "_archive/" in p:
        return False
    if not any(p.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        return False
    return p.endswith(".py") and "/tests/" in p


def main(argv: list[str]) -> int:
    paths = argv[1:] if len(argv) > 1 else []
    violations: list[str] = []
    for raw in paths:
        norm = raw.replace("\\", "/")
        if not _is_test_path(norm):
            continue
        name = Path(norm).name
        if BANNED.search(name):
            violations.append(norm)
    if violations:
        print(
            "禁止新增 test_coverage_ramp_phase* 测试文件。"
            " 请按 specs/test-naming.md 写入 tests/unit/ 或 tests/routes/。\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
