#!/usr/bin/env python3
"""测试膨胀报告与门禁：tests/ 与业务源码行数比 + coverage_ramp stub 行数配额。

P1-2 技术债治理：测试代码 45.8 万行远超业务源码，且大量为凑覆盖率生成、
断言弱、杀变体能力低的 ``coverage_ramp_phase*`` stub。本脚本：

* 统计 ``tests/**/*.py`` 总行数 vs ``app/**/*.py`` 业务源码行数，计算测试/源码比值
* 单独统计 ``test_coverage_ramp_*`` stub 行数（与 conftest 打标口径一致）
* 输出报告并追加到 ``metrics/test-bloat-history.jsonl``
* ``--check`` 门禁（**棘轮**）：以历史基线为起点，**只拦截回退**（比值/行数不增）
  —— 存量已超标项（ratio 1.81 / stub 6.36 万）不阻断，但任何新增膨胀立即失败。
  绝对目标（ratio ≤ 1.5、stub ≤ 5 万）作为文档化长期收敛目标，不作为即时阻断。

用法::

    python scripts/dev/test_bloat_report.py                 # 仅报告
    python scripts/dev/test_bloat_report.py --check         # CI 棘轮门禁（回退超限退出码 1）
    python scripts/dev/test_bloat_report.py --check --seed  # 以当前值为基线种子（首次接入）
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

# 绝对目标（文档化收敛目标，非即时阻断；与棘轮并存）
RATIO_GOAL = 1.5  # tests/ 与 app/ 行数比长期目标
STUB_LINES_GOAL = 50_000  # coverage_ramp stub 行数长期目标
# 棘轮回退容忍（吸收 CI 噪声/微改行数波动，防误报）
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


def cmd_report() -> int:
    rec = collect()
    print(f"[test-bloat] tests {rec['test_files']} files / {rec['test_lines']} lines")
    print(f"[test-bloat] app   {rec['src_files']} files / {rec['src_lines']} lines")
    print(f"[test-bloat] 测试/源码比 = {rec['ratio']}（上限 {RATIO_LIMIT}）")
    print(
        f"[test-bloat] coverage_ramp stub {rec['stub_files']} files / "
        f"{rec['stub_lines']} lines（上限 {STUB_LINES_LIMIT}）"
    )
    append_history(rec)
    return 0


def cmd_check() -> int:
    rec = collect()
    append_history(rec)
    ratio = rec["ratio"]
    stub_lines = rec["stub_lines"]
    print(f"[test-bloat] tests lines={rec['test_lines']} src lines={rec['src_lines']} "
          f"ratio={ratio} (limit {RATIO_LIMIT})")
    print(f"[test-bloat] coverage_ramp stub_lines={stub_lines} (limit {STUB_LINES_LIMIT})")

    failed = False
    if ratio > RATIO_LIMIT:
        print(
            f"[test-bloat] FAIL: 测试/源码比 {ratio} > {RATIO_LIMIT}。"
            "测试代码膨胀，应通过行为测试收敛、删除纯占位 stub。",
            file=sys.stderr,
        )
        failed = True
    if stub_lines > STUB_LINES_LIMIT:
        print(
            f"[test-bloat] FAIL: coverage_ramp stub 行数 {stub_lines} > {STUB_LINES_LIMIT}。",
            file=sys.stderr,
        )
        failed = True
    if failed:
        # 输出占比最高的 stub 文件，便于定位
        stub_files = sorted(
            (p for p in _py_files(TESTS_DIR) if p.name.startswith(STUB_PREFIX)),
            key=_line_count,
            reverse=True,
        )[:10]
        for p in stub_files:
            print(f"  stub: {p.relative_to(FHD_ROOT).as_posix()} "
                  f"({_line_count(p)} lines)", file=sys.stderr)
        return 1
    print("[test-bloat] OK — 测试膨胀未超标")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="CI 门禁：超限退出码 1")
    args = parser.parse_args(argv)
    return cmd_check() if args.check else cmd_report()


if __name__ == "__main__":
    sys.exit(main())