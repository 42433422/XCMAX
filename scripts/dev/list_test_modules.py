#!/usr/bin/env python3
"""Aggregate pytest file counts by tests/ subdirectory for INDEX.md refresh."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path


def main() -> None:
    tests_root = Path(__file__).resolve().parents[2] / "tests"
    counts: dict[str, int] = defaultdict(int)
    ramp = 0
    for path in sorted(tests_root.rglob("test_*.py")):
        rel = path.relative_to(tests_root)
        top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        counts[top] += 1
        if "test_coverage_ramp_phase" in path.name:
            ramp += 1
    print("# FHD tests 目录索引（自动生成）\n")
    print(f"生成：`python scripts/dev/list_test_modules.py`\n")
    print(f"- 总 `test_*.py`：{sum(counts.values())}")
    print(f"- 其中历史 ramp（`test_coverage_ramp_phase*`）：{ramp}\n")
    print("| 顶层目录 | 文件数 |")
    print("|----------|--------|")
    for key in sorted(counts, key=lambda k: (-counts[k], k)):
        print(f"| `{key}/` | {counts[key]} |")
    print("\n命名规范：[specs/test-naming.md](../../specs/test-naming.md)")


if __name__ == "__main__":
    main()
