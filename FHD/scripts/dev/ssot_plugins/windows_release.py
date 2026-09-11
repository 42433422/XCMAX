#!/usr/bin/env python3
"""windows-release 域 check：WINDOWS_RELEASE_SSOT.md 结构与状态值合法性。

校验：
  1. 必填节存在（§1 版本 / §4 Gate 状态 / §6 实机任务 / §8 runbook）
  2. Gate 状态取值合法（GREEN / YELLOW / RED / UNKNOWN / 待实跑回填）
  3. RED 状态必须引用阻断项编号（B#，见文档 §5），否则视为未定位的 DRIFT

用法: python scripts/dev/ssot_plugins/windows_release.py check
退出码: 0=OK 1=DRIFT
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # FHD/
DOC = ROOT / "docs" / "WINDOWS_RELEASE_SSOT.md"
REQUIRED_SECTIONS = ("## 1. 当前版本信息", "## 4. Release Gate", "## 6. 实机验收任务", "## 8. 发版复用 Runbook")
LEGAL_STATES = {"GREEN", "YELLOW", "RED", "UNKNOWN", "待实跑回填"}


def check() -> int:
    if not DOC.is_file():
        print(f"缺少 SSOT 文档: {DOC}", file=sys.stderr)
        return 1
    text = DOC.read_text(encoding="utf-8")
    problems: list[str] = []
    for sec in REQUIRED_SECTIONS:
        if sec not in text:
            problems.append(f"缺少必填节: {sec}")
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        state = cells[2]
        if state in LEGAL_STATES and state == "RED" and not re.search(r"B\d+", line):
            problems.append(f"line {i}: Gate 状态 RED 未引用阻断项编号（B#，须链接 §5 精确定位）")
        if re.fullmatch(r"[A-Z]{4,}", state) and state not in LEGAL_STATES:
            problems.append(f"line {i}: 非法 Gate 状态值: {state}（合法: {'/'.join(sorted(LEGAL_STATES))}）")
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print("修复：见文档头部状态取值与 RED 处理规则", file=sys.stderr)
        return 1
    print("windows-release: OK（结构与状态值合法）")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
