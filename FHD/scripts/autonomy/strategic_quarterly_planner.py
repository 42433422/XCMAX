#!/usr/bin/env python3
"""战略季度规划 CLI——把「这个季度做哪三个功能」变成可审计产物。

用法：
  python scripts/autonomy/strategic_quarterly_planner.py \\
    --goal "本季度把自治做成可规划 AGI 工程" \\
    --critique "优先收入闭环" \\
    --heuristic
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 允许直接 python scripts/autonomy/strategic_quarterly_planner.py
_FHD = Path(__file__).resolve().parents[2]
if str(_FHD) not in sys.path:
    sys.path.insert(0, str(_FHD))


def main() -> int:
    p = argparse.ArgumentParser(description="LLM/启发式季度战略规划")
    p.add_argument("--goal", default="", help="战略目标")
    p.add_argument("--critique", default="", help="反思修正意见")
    p.add_argument("--quarter", default="", help="如 2026-Q3")
    p.add_argument(
        "--heuristic",
        action="store_true",
        help="强制启发式（不调用 LLM，适合 CI）",
    )
    p.add_argument("--no-persist", action="store_true", help="不写入 JSONL")
    args = p.parse_args()

    if args.heuristic:
        from app.application.autonomy.strategic_plan_app_service import (
            build_quarterly_plan_sync,
        )

        plan = build_quarterly_plan_sync(
            args.goal or None,
            critique=args.critique or None,
            quarter=args.quarter or None,
            persist=not args.no_persist,
        )
    else:
        from app.application.autonomy.strategic_plan_app_service import build_quarterly_plan

        plan = asyncio.run(
            build_quarterly_plan(
                args.goal or None,
                critique=args.critique or None,
                quarter=args.quarter or None,
                use_llm=True,
                persist=not args.no_persist,
            )
        )

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    features = plan.get("features") or []
    if len(features) != 3:
        print(f"[warn] expected 3 features, got {len(features)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
