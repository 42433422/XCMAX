#!/usr/bin/env python3
"""自维护循环 ledger 读取工具。

读取 MODstore 自维护循环的执行历史记录,帮助诊断循环成功率、失败原因等。

用法::
    python scripts/dev/loop_ledger_reader.py              # 显示最近 10 条记录
    python scripts/dev/loop_ledger_reader.py --tail 20    # 显示最近 20 条
    python scripts/dev/loop_ledger_reader.py --status     # 统计状态分布
    python scripts/dev/loop_ledger_reader.py --failures   # 只显示失败记录
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def find_ledger_path() -> Path:
    """查找 ledger 文件路径(与 loop_runner 中的 ledger_path() 保持一致)。"""
    import os
    
    raw = os.environ.get("MODSTORE_SELF_MAINTENANCE_LEDGER")
    if raw:
        return Path(raw)
    
    # DEFAULT_RUNTIME_DIR = ~/.xcmax/modstore-daily
    runtime_dir = Path.home() / ".xcmax" / "modstore-daily"
    ledger_name = "self_maintenance_loop_runs.jsonl"
    return runtime_dir / ledger_name


def read_ledger(limit: int = 100) -> List[Dict[str, Any]]:
    """读取 ledger 文件最后 N 条记录。"""
    path = find_ledger_path()
    if not path.is_file():
        return []
    
    records = []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        for line in lines[-limit:]:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    
    return records


def format_record(rec: Dict[str, Any]) -> str:
    """格式化单条记录。"""
    ts = rec.get("timestamp", "?")
    status = rec.get("status", "?")
    phase = rec.get("phase", "?")
    run_id = rec.get("run_id", "?")[:8] if rec.get("run_id") else "?"
    triggered_by = rec.get("triggered_by", "?")
    
    # 简化时间戳
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        ts_short = dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        ts_short = ts
    
    # 失败记录额外显示错误信息
    error_info = ""
    if status == "failed" and rec.get("error"):
        error_info = f" | error: {rec['error'][:100]}"
    
    return f"[{ts_short}] {phase} | {status} | run:{run_id} | by:{triggered_by}{error_info}"


def cmd_tail(args: argparse.Namespace) -> int:
    """显示最近 N 条记录。"""
    records = read_ledger(limit=args.n)
    if not records:
        print(f"(无记录,ledger 文件: {find_ledger_path()})")
        return 0
    
    print(f"最近 {len(records)} 条记录 (ledger: {find_ledger_path()}):\n")
    for rec in records:
        print(format_record(rec))
    
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """统计状态分布。"""
    records = read_ledger(limit=1000)  # 读更多做统计
    if not records:
        print(f"(无记录,ledger 文件: {find_ledger_path()})")
        return 0
    
    status_counter: Counter = Counter()
    phase_counter: Counter = Counter()
    
    for rec in records:
        status_counter[rec.get("status", "unknown")] += 1
        phase_counter[rec.get("phase", "unknown")] += 1
    
    print(f"自维护循环状态统计 (最近 {len(records)} 条记录):\n")
    print("状态分布:")
    for status, count in status_counter.most_common():
        pct = count / len(records) * 100
        print(f"  {status:20s} {count:4d} ({pct:5.1f}%)")
    
    print("\n阶段分布:")
    for phase, count in phase_counter.most_common():
        pct = count / len(records) * 100
        print(f"  {phase:20s} {count:4d} ({pct:5.1f}%)")
    
    # 成功率计算(只看最终状态记录)
    final_records = [r for r in records if r.get("phase") in ("final", "complete")]
    if final_records:
        success_count = sum(1 for r in final_records if r.get("status") == "completed")
        sum(1 for r in final_records if r.get("status") == "failed")
        total = len(final_records)
        success_rate = success_count / total * 100 if total > 0 else 0
        print(f"\n循环成功率: {success_count}/{total} ({success_rate:.1f}%)")
    
    return 0


def cmd_failures(args: argparse.Namespace) -> int:
    """只显示失败记录。"""
    records = read_ledger(limit=args.n)
    failures = [r for r in records if r.get("status") == "failed"]
    
    if not failures:
        print("(无失败记录)")
        return 0
    
    print(f"最近 {len(failures)} 条失败记录:\n")
    for rec in failures:
        print(format_record(rec))
        # 显示详细的错误栈
        if rec.get("error"):
            print(f"  错误: {rec['error']}")
        if rec.get("steps"):
            print(f"  步骤数: {len(rec['steps'])}")
            for i, step in enumerate(rec["steps"][-3:], 1):  # 只显示最后 3 步
                print(f"    {i}. {step.get('step', '?')}: {step.get('status', '?')}")
        print()
    
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--tail", type=int, help="显示最近 N 条记录(默认 10)")
    parser.add_argument("--status", action="store_true", help="统计状态分布")
    parser.add_argument("--failures", action="store_true", help="只显示失败记录")
    parser.add_argument("-n", type=int, default=10, help="记录数量(默认 10)")
    
    args = parser.parse_args(argv)
    
    if args.status:
        return cmd_status(args)
    elif args.failures:
        return cmd_failures(args)
    else:
        return cmd_tail(args)


if __name__ == "__main__":
    sys.exit(main())