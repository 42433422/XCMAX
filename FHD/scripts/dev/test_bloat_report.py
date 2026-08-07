#!/usr/bin/env python3
"""测试膨胀报告与门禁：tests/ 与业务源码行数比 + coverage_ramp stub 行数配额。

P1-2 技术债治理：测试代码 45.8 万行远超业务源码，且大量为凑覆盖率生成、
断言弱、杀变体能力低的 coverage_ramp stub。本脚本：

* 统计 tests 总行数 vs app 业务源码行数，计算测试/源码比值
* 单独统计 test_coverage_ramp_* stub 行数
* 输出报告并追加到 metrics/test-bloat-history.jsonl
* --check 门禁（棘轮）：以历史基线为起点，只拦截回退（比值/行数不增）
  存量已超标项不阻断，任何新增膨胀立即失败。绝对目标仅文档化。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = FHD_ROOT / "tests"
APP_DIR = FHD_ROOT / "app"
METRICS_FILE = FHD_ROOT / "metrics" / "test-bloat-history.jsonl"

RATIO_GOAL = 1.5
STUB_LINES_GOAL = 50_000
RATIO_TOLERANCE = 0.02
STUB_TOLERANCE = 2_000
STUB_PREFIX = "test_coverage_ramp_"


def _line_count(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8", errors="replace"))
    except (OSError, UnicodeDecodeError):
        return 0


def _py_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def collect() -> dict:
    test_files = _py_files(TESTS_DIR)
    src_files = _py_files(APP_DIR)
    test_lines = sum(_line_count(p) for p in test_files)
    src_lines = sum(_line_count(p) for p in src_files)
    stub_files = [p for p in test_files if p.name.startswith(STUB_PREFIX)]
    stub_lines = sum(_line_count(p) for p in stub_files)
    ratio = round(test_lines / src_lines, 3) if src_lines else 0.0
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "test_files": len(test_files),
        "test_lines": test_lines,
        "src_files": len(src_files),
        "src_lines": src_lines,
        "ratio": ratio,
        "stub_files": len(stub_files),
        "stub_lines": stub_lines,
    }


def append_history(rec: dict) -> None:
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with METRICS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _last_baseline() -> dict | None:
    if not METRICS_FILE.exists():
        return None
    last = None
    try:
        with METRICS_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    last = json.loads(line)
    except (OSError, ValueError):
        return None
    return last or None


def cmd_report() -> int:
    rec = collect()
    print(f"[test-bloat] tests {rec['test_files']} files / {rec['test_lines']} lines")
    print(f"[test-bloat] app   {rec['src_files']} files / {rec['src_lines']} lines")
    print(f"[test-bloat] ratio={rec['ratio']} (goal {RATIO_GOAL})")
    print(f"[test-bloat] stub_lines={rec['stub_lines']} (goal {STUB_LINES_GOAL})")
    append_history(rec)
    return 0


def cmd_check(seed: bool = False) -> int:
    rec = collect()
    ratio = rec["ratio"]
    stub_lines = rec["stub_lines"]
    baseline = None if seed else _last_baseline()
    if baseline is None:
        append_history(rec)
        print(f"[test-bloat] seed baseline: ratio={ratio} stub_lines={stub_lines}")
        print("[test-bloat] OK - seeded ratchet baseline")
        return 0
    base_ratio = baseline.get("ratio", ratio)
    base_stub = baseline.get("stub_lines", stub_lines)
    print(f"[test-bloat] ratio={ratio} (baseline {base_ratio} tol {RATIO_TOLERANCE})")
    print(f"[test-bloat] stub_lines={stub_lines} (baseline {base_stub} tol {STUB_TOLERANCE})")
    print(f"[test-bloat] goals ratio<={RATIO_GOAL} stub<={STUB_LINES_GOAL} (documented)")
    failed = False
    if ratio > base_ratio + RATIO_TOLERANCE:
        print(f"[test-bloat] FAIL: ratio {ratio} > baseline {base_ratio} + tol {RATIO_TOLERANCE}",
              file=sys.stderr)
        failed = True
    if stub_lines > base_stub + STUB_TOLERANCE:
        print(f"[test-bloat] FAIL: stub_lines {stub_lines} > baseline {base_stub} + tol {STUB_TOLERANCE}",
              file=sys.stderr)
        failed = True
    if failed:
        stub_files = sorted(
            (p for p in _py_files(TESTS_DIR) if p.name.startswith(STUB_PREFIX)),
            key=_line_count,
            reverse=True,
        )[:10]
        for p in stub_files:
            print(f"  stub: {p.relative_to(FHD_ROOT).as_posix()} ({_line_count(p)} lines)",
                  file=sys.stderr)
        return 1
    append_history(rec)
    print("[test-bloat] OK - no regression")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="CI ratchet gate")
    parser.add_argument("--seed", action="store_true", help="seed baseline")
    args = parser.parse_args(argv)
    if not args.check:
        return cmd_report()
    return cmd_check(seed=args.seed)


if __name__ == "__main__":
    sys.exit(main())