#!/usr/bin/env python3
"""阶段 6 双线交叉 & SRE 门禁：路径存在性 + 编排器冒烟测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

REQUIRED_PATHS = [
    ROOT / "docs/guides/DUAL_LINE_SRE_GATE.md",
    ROOT / "k8s/monitoring/runbooks/DISASTER_RECOVERY.md",
    ROOT / "k8s/monitoring/runbooks/CHAOS_GAME_DAY.md",
    ROOT / "tests/test_production_line_orchestrator.py",
    REPO / "成都修茈科技有限公司/MODstore_deploy/modstore_server/production_line_orchestrator.py",
    REPO / "成都修茈科技有限公司/MODstore_deploy/docs/runbooks/disaster-recovery.md",
    REPO / "成都修茈科技有限公司/MODstore_deploy/docs/runbooks/chaos-game-day.md",
    REPO / "成都修茈科技有限公司/MODstore_deploy/chaos/chaos_drill.py",
    REPO / "成都修茈科技有限公司/MODstore_deploy/modstore_server/auto_fix_loop.py",
    REPO / "成都修茈科技有限公司/MODstore_deploy/modstore_server/incident_bus.py",
    REPO / "成都修茈科技有限公司/MODstore_deploy/modstore_server/workflow_scheduler.py",
    REPO / "成都修茈科技有限公司/MODstore_deploy/modstore_server/telemetry_backlog_loop.py",
    ROOT / "mods/_employees/vibe-coding-maintainer/manifest.json",
]


def main() -> int:
    missing = [p for p in REQUIRED_PATHS if not p.is_file()]
    if missing:
        for p in missing:
            print(f"MISSING: {p}", file=sys.stderr)
        return 1

    print(f"OK: {len(REQUIRED_PATHS)} gate artifacts present")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_production_line_orchestrator.py",
            "-q",
            "--tb=short",
            "--noconftest",
        ],
        cwd=ROOT,
    )
    if proc.returncode != 0:
        print("FAIL: production line orchestrator tests", file=sys.stderr)
        return proc.returncode

    print("OK: test_production_line_orchestrator.py (4 tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
