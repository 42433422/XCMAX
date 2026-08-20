#!/usr/bin/env python3
# mypy: disable-error-code="assignment, no-any-return"
"""变异测试杀死率报告生成器。

解析 mutmut 输出，计算加权杀死率，记录到
``metrics/mutation-history.jsonl``（追加模式，每行一个 JSON 对象）。

设计取舍
--------
* 版本无关：兼容
  - mutmut 2.x：``Killed (10)`` / ``Survived (2)``
  - mutmut 3.x progress：``🎉 67 🫥 0  ⏰ 0  🤔 0  🙁 23``
  - mutmut 3.x ``results``：``    key: survived``（默认跳过 killed，需 ``--all``）
* 仅用标准库。
* 加权杀死率 = ``killed / (killed + survived + timeout)``；
  ``no_tests`` / ``skipped`` 不计入分母。

退出码
------
* ``0``：杀死率达到阈值。
* ``1``：杀死率低于阈值（CI 门禁失败）。
* ``2``：用法错 / mutmut 未安装 / ``mutmut results`` 超时。

用法::

    python scripts/dev/mutation_kill_report.py
    python scripts/dev/mutation_kill_report.py --threshold 80
    python scripts/dev/mutation_kill_report.py --from-file mutmut-run.log
    python scripts/dev/mutation_kill_report.py --dry-run
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

# mutmut 2.x / 3.x 摘要行：Killed 🎉 (10)
_STATUS_RE = re.compile(
    r"^\s*(?P<status>killed|survived|timeout|no[ _-]tests)\b[^\(]*\((?P<count>\d+)\)",
    re.IGNORECASE,
)

# mutmut 3.x progress：🎉 67 🫥 0  ⏰ 0  🤔 0  🙁 23  🔇 0  🧙 0
_PROGRESS_RE = re.compile(
    r"🎉\s*(?P<killed>\d+).*?"
    r"🫥\s*(?P<no_tests>\d+).*?"
    r"⏰\s*(?P<timeout>\d+).*?"
    r"🤔\s*(?P<suspicious>\d+).*?"
    r"🙁\s*(?P<survived>\d+)",
    re.DOTALL,
)

# mutmut 3.x results：    app.foo.bar__mutmut_1: survived
_RESULT_LINE_RE = re.compile(
    r"^\s*\S+:\s*(?P<status>killed|survived|timeout|suspicious|skipped|no_tests|caught_by_type_check)\s*$",
    re.IGNORECASE,
)


def run_mutmut_results() -> str:
    """运行 ``mutmut results --all true``，返回 stdout（含 killed）。"""
    candidates = [
        ["mutmut", "results", "--all", "true"],
        ["uv", "run", "mutmut", "results", "--all", "true"],
        [sys.executable, "-m", "mutmut", "results", "--all", "true"],
        # 旧调用兜底（仅 survivors）
        ["mutmut", "results"],
        ["uv", "run", "mutmut", "results"],
        [sys.executable, "-m", "mutmut", "results"],
    ]
    for cmd in candidates:
        try:
            result = subprocess.run(
                cmd,
                cwd=FHD_ROOT,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError:
            continue
        output = result.stdout + ("\n" + result.stderr if result.stderr else "")
        if output.strip() or result.returncode == 0:
            return output

    raise FileNotFoundError


def parse_results(output: str) -> dict:
    """解析 mutmut 输出，返回计数 dict。"""
    counts = {"killed": 0, "survived": 0, "timeout": 0, "no_tests": 0}

    # 1) 优先取最后一条 progress 摘要（mutmut run 日志）
    progress_hits = list(_PROGRESS_RE.finditer(output))
    if progress_hits:
        m = progress_hits[-1]
        counts["killed"] = int(m.group("killed"))
        counts["survived"] = int(m.group("survived"))
        counts["timeout"] = int(m.group("timeout"))
        counts["no_tests"] = int(m.group("no_tests"))
        # suspicious 保守并入 survived
        counts["survived"] += int(m.group("suspicious"))
        return counts

    # 2) mutmut 2.x / 旧摘要行
    legacy_found = False
    for line in output.splitlines():
        m = _STATUS_RE.match(line)
        if not m:
            continue
        legacy_found = True
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

    for alias, target in (("suspicious", "survived"), ("error", "timeout")):
        for line in output.splitlines():
            m = re.match(
                rf"^\s*{alias}\b[^\(]*\((?P<count>\d+)\)",
                line,
                re.IGNORECASE,
            )
            if m:
                legacy_found = True
                counts[target] += int(m.group("count"))

    if legacy_found and (counts["killed"] or counts["survived"] or counts["timeout"]):
        return counts

    # 3) mutmut 3.x results 逐条状态
    for line in output.splitlines():
        m = _RESULT_LINE_RE.match(line)
        if not m:
            continue
        status = m.group("status").lower()
        if status == "killed":
            counts["killed"] += 1
        elif status in {"survived", "suspicious"}:
            counts["survived"] += 1
        elif status in {"timeout", "caught_by_type_check"}:
            counts["timeout"] += 1
        elif status in {"no_tests", "skipped"}:
            counts["no_tests"] += 1

    return counts


def compute_kill_rate(counts: dict) -> float:
    """计算加权杀死率：``killed / (killed + survived + timeout)``。"""
    denom = counts["killed"] + counts["survived"] + counts["timeout"]
    if denom == 0:
        return 0.0
    return counts["killed"] / denom


def main() -> int:
    parser = argparse.ArgumentParser(
        description="变异测试杀死率报告生成器（解析 mutmut 输出）",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=70,
        help="杀死率阈值（百分比），低于则退出码 1（默认 70）",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="从文件解析（如 mutmut run 的 tee 日志）；默认调用 mutmut results --all",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不写入 history 文件，仅打印结果",
    )
    args = parser.parse_args()

    try:
        if args.from_file is not None:
            output = args.from_file.read_text(encoding="utf-8", errors="replace")
        else:
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
    except OSError as exc:
        print(f"[ERROR] cannot read --from-file: {exc}", file=sys.stderr)
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
    print(f"[mutation] kill_rate={kill_rate_pct:.2f}% (threshold {args.threshold}%)")

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
