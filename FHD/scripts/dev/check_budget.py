#!/usr/bin/env python3
"""门禁 3：预算限制检查。

读取 --budget-file 指定的 JSON 文件（含 tokens_used / tokens_limit / time_used_minutes / time_limit_minutes），
超任一限 → 退出码 1。
全部通过 → 退出码 0。

Usage:
    python check_budget.py --budget-file budget.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget-file", required=True, help="JSON file with budget metrics")
    args = parser.parse_args()

    budget_path = Path(args.budget_file)
    if not budget_path.is_file():
        print(f"ERROR: budget file not found: {budget_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(budget_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid budget JSON: {e}", file=sys.stderr)
        return 2

    tokens_used = float(data.get("tokens_used") or 0)
    tokens_limit = float(data.get("tokens_limit") or 100000)
    time_used = float(data.get("time_used_minutes") or 0)
    time_limit = float(data.get("time_limit_minutes") or 30)

    if tokens_used > tokens_limit:
        print(
            f"ERROR: tokens {tokens_used} exceeds limit {tokens_limit}",
            file=sys.stderr,
        )
        return 1
    if time_used > time_limit:
        print(
            f"ERROR: time {time_used}min exceeds limit {time_limit}min",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: budget within limits (tokens={tokens_used}/{tokens_limit}, time={time_used}/{time_limit}min)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
