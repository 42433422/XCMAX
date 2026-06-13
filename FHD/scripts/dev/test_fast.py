#!/usr/bin/env python3
"""后端「快车道」测试 —— 排除已知红文件，给出可复现的本地绿色信号。

用于在重构（绞杀者式路由收口等）后快速验证「未引入新回归」，无需等待全量套件
（本分支 CI 与本地全量均红：含幽灵测试/环境耦合/API 漂移，见
docs/architecture/REFACTOR_DECOMPOSITION_PLAN.md §6）。

隔离名单 ``tests/quarantine_known_red.txt`` 是**债务燃尽清单**（显式可见、非隐藏跳过）：
修复一个文件就从名单删一行，快车道覆盖面随之扩大。

用法::

    python scripts/dev/test_fast.py                  # 跑快车道
    python scripts/dev/test_fast.py -k some_test     # 透传任意 pytest 参数
    python scripts/dev/test_fast.py --count          # 只统计将排除/纳入的文件数

环境：与 CI 对齐自动设置 XCAGI_SKIP_LEGACY_COMPAT_ROUTES=1、INTENT_BENCHMARK_RUN=1。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QUARANTINE = REPO_ROOT / "tests" / "quarantine_known_red.txt"


def load_quarantine() -> list[str]:
    if not QUARANTINE.is_file():
        return []
    out: list[str] = []
    for raw in QUARANTINE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def main(argv: list[str]) -> int:
    ignores = load_quarantine()

    if "--count" in argv:
        print(f"[test-fast] 隔离名单文件数（排除）：{len(ignores)}")
        return 0

    env = dict(os.environ)
    env.setdefault("XCAGI_SKIP_LEGACY_COMPAT_ROUTES", "1")
    env.setdefault("INTENT_BENCHMARK_RUN", "1")

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/",
        *[f"--ignore={p}" for p in ignores],
        "-p",
        "no:cacheprovider",
        "-q",
        *argv,
    ]
    print(f"[test-fast] 排除 {len(ignores)} 个已知红文件（见 {QUARANTINE.relative_to(REPO_ROOT)}）")
    return subprocess.run(cmd, cwd=REPO_ROOT, env=env).returncode


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
