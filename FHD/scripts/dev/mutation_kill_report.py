#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变异测试杀死率报告生成器。

解析 ``mutmut results`` 输出，计算加权杀死率，记录到
``metrics/mutation-history.jsonl``（追加模式，每行一个 JSON 对象）。

设计取舍
--------
* 版本无关：直接调用 ``mutmut results`` 子进程并解析其 stdout，兼容
  mutmut 2.x（纯文本，如 ``Killed (10)``）与 3.x（带 emoji，如
  ``Killed 🎉 (10)``）两种输出格式。
* 仅用标准库：``argparse`` / ``json`` / ``subprocess`` / ``sys`` /
  ``pathlib`` / ``datetime``，便于在 CI 与本地零依赖运行。
* 加权杀死率 = ``killed / (killed + survived + timeout)``；
  ``no_tests`` 不计入分母（mutmut 3.x 会出现该状态，表示该变体无对应测试）。

退出码
------
* ``0``：杀死率达到阈值。
* ``1``：杀死率低于阈值（CI 门禁失败）。
* ``2``：用法错 / mutmut 未安装 / ``mutmut results`` 超时。

用法::

    python scripts/dev/mutation_kill_report.py                  # 默认阈值 70%
    python scripts/dev/mutation_kill_report.py --threshold 80   # 自定义阈值
    python scripts/dev/mutation_kill_report.py --dry-run        # 不写 history
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# scripts/dev/mutation_kill_report.py → parents[3] = XCMAX/
REPO_ROOT = Path(__file__).resolve().parents[3]
FHD_ROOT = REPO_ROOT / "FHD"
HISTORY_FILE = FHD_ROOT / "metrics" / "mutation-history.jsonl"

# 匹配 "Killed 🎉 (10)" / "Survived 🙁 (2)" / "Timeout ⏰ (1)" / "No tests (0)"
# 也兼容 mutmut 2.x 纯文本 "Killed (10)"。
# 关键字大小写不敏感，emoji 可选，括号内为整数。
_STATUS_RE = re.compile(
    r"^\s*(?P<status>killed|survived|timeout|no[ _-]tests)\b[^\(]*\((?P<count>\d+)\)",
    re.IGNORECASE,
)


def run_mutmut_results() -> str:
    """运行 ``mutmut results``，返回 stdout。

    在 ``FHD_ROOT`` 下执行，便于 mutmut 找到 ``pyproject.toml`` 与缓存目录。
    超时 300s（``mutmut results`` 通常秒级返回，超时视为异常）。
    """
    result = subprocess.run(
        ["mutmut", "results"],
        cwd=FHD_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    # mutmut results 在无缓存时也可能以非零退出，但仍输出有用信息；
    # 这里统一返回 stdout + stderr 供 parse_results 容错。
    return result.stdout + ("\n" + result.stderr if result.stderr else "")


def parse_results(output: str) -> dict:
    """解析 ``mutmut results`` 输出，返回计数 dict。

    覆盖以下格式（2.x / 3.x 通用）::

        Killed 🎉 (10)
        Survived 🙁 (2)
        Timeout ⏰ (1)
        No tests (0)
        Suspicious (1)        # 归入 survived（行为不确定，保守计为未杀死）
        Skipped (3)           # 不计入分母
        Error (1)             # 归入 timeout（运行异常，等同未杀死）

    返回 dict 含 ``killed`` / ``survived`` / ``timeout`` / ``no_tests`` 四个键。
    """
    counts = {"killed": 0, "survived": 0, "timeout": 0, "no_tests": 0}

    for line in output.splitlines():
        m = _STATUS_RE.match(line)
        if not m:
            continue
        status = m.group("status").lower().replace("-", "_").replace(" ", "_")
        count = int(m.group("count"))

        if status == "killed":
            counts["killed"] += count
        elif status == "survived":
            counts["survived"] += count
        elif status == "timeout":
            counts["timeout"] += count
        elif status == "no_tests":
            counts["no_tests"] += count

    # 兼容 mutmut 2.x/3.x 的 "Suspicious" / "Error" 等次要状态：
    # 行为不确定或运行异常的变体，保守归入"未杀死"侧。
    for alias, target in (("suspicious", "survived"), ("error", "timeout")):
        for line in output.splitlines():
            m = re.match(
                rf"^\s*{alias}\b[^\(]*\((?P<count>\d+)\)",
                line,
                re.IGNORECASE,
            )
            if m:
                counts[target] += int(m.group("count"))

    return counts


def compute_kill_rate(counts: dict) -> float:
    """计算加权杀死率：``killed / (killed + survived + timeout)``。

    分母为 0 时返回 0.0（无变体或仅有 no_tests 状态）。
    """
    denom = counts["killed"] + counts["survived"] + counts["timeout"]
    if denom == 0:
        return 0.0
    return counts["killed"] / denom


def main() -> int:
    parser = argparse.ArgumentParser(
        description="变异测试杀死率报告生成器（解析 mutmut results 输出）",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=70,
        help="杀死率阈值（百分比），低于则退出码 1（默认 70）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不写入 history 文件，仅打印结果",
    )
    args = parser.parse_args()

    try:
        output = run_mutmut_results()
    except FileNotFoundError:
        print(
            "[ERROR] mutmut not installed. Run: pip install mutmut",
            file=sys.stderr,
        )
        return 2
    except subprocess.TimeoutExpired:
        print("[ERROR] mutmut results timed out", file=sys.stderr)
        return 2

    counts = parse_results(output)
    kill_rate = compute_kill_rate(counts)
    kill_rate_pct = kill_rate * 100

    record = {
        "date": datetime.now(UTC).isoformat(),
        **counts,
        "kill_rate": round(kill_rate, 4),
        "threshold": args.threshold,
    }

    print(
        f"[mutation] killed={counts['killed']} survived={counts['survived']} "
        f"timeout={counts['timeout']} no_tests={counts['no_tests']}"
    )
    print(
        f"[mutation] kill_rate={kill_rate_pct:.2f}% (threshold {args.threshold}%)"
    )

    if not args.dry_run:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[mutation] appended to {HISTORY_FILE}")

    if kill_rate_pct < args.threshold:
        print(
            f"[FAIL] kill_rate {kill_rate_pct:.2f}% < threshold {args.threshold}%",
            file=sys.stderr,
        )
        return 1

    print("[OK] kill_rate meets threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
