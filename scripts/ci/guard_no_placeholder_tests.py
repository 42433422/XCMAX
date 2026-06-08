#!/usr/bin/env python3
"""Block newly added test files with 'placeholder' in the filename."""

from __future__ import annotations

import sys
from pathlib import Path

FORBIDDEN = "placeholder"


def main(argv: list[str]) -> int:
    paths = argv[1:] if len(argv) > 1 else []
    bad = [p for p in paths if FORBIDDEN in Path(p).name.lower() and p.endswith(".py")]
    if bad:
        print("禁止新增含 placeholder 的测试文件名；请使用真实域命名。")
        for p in sorted(bad):
            print(f"  - {p}")
        return 1
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(main(sys.argv))
