#!/usr/bin/env python3
"""离线报告：画布上 node_type=eskill 但 config 缺少 skill_id 的节点（阶段 5 回填前摸底）。

用法（在项目根 MODstore_deploy）::
    python scripts/backfill_report_eskill_nodes.py

不落库、不改数据；仅打印计数与样例行。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modstore_server.models import WorkflowNode, get_engine, get_session_factory  # noqa: E402


def main() -> None:
    get_engine()
    sf = get_session_factory()
    bad: list = []
    rows: list = []
    with sf() as db:
        rows = db.query(WorkflowNode).filter(WorkflowNode.node_type == "eskill").all()
        for n in rows:
            try:
                cfg = json.loads(n.config or "{}")
            except json.JSONDecodeError:
                bad.append((n.id, n.workflow_id, "invalid_json"))
                continue
            sid = str(cfg.get("skill_id") or cfg.get("eskill_id") or "").strip()
            if sid.isdigit():
                continue
            bad.append((n.id, n.workflow_id, cfg))

    print(f"eskill nodes total={len(rows)}, missing_numeric_skill_id={len(bad)}")
    for item in bad[:40]:
        print(item)


if __name__ == "__main__":
    main()
