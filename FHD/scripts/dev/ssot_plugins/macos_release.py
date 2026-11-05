#!/usr/bin/env python3
"""macos-release 域 check：MACOS_RELEASE_SSOT.md 结构与状态值合法性。

校验：
  1. 必填节存在（§1 版本 / §6 Gate / §8 实机任务 / §9 runbook）
  2. Gate 状态取值合法（GREEN / YELLOW / RED / UNKNOWN / 待实跑回填）
  3. RED 状态必须附完整证据（复现步骤 + evidence/e2e/ 证据链接 + 修复 PR/commit 引用），
     缺任一项即 DRIFT；对应协议：只修真阻断项，修完重测，禁止直接改状态

用法: python scripts/dev/ssot_plugins/macos_release.py check
退出码: 0=OK 1=DRIFT
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # FHD/
DOC = ROOT / "docs" / "MACOS_RELEASE_SSOT.md"
REQUIRED_SECTIONS = (
    "## 1. 当前版本信息",
    "## 6. Release Gate",
    "## 8. 实机验收任务",
    "## 9. 发版复用 Runbook",
)
LEGAL_STATES = {"GREEN", "YELLOW", "RED", "UNKNOWN", "待实跑回填"}


def _check_doc(doc: Path, sections: tuple[str, ...], label: str) -> int:
    """共享校验核心：windows_release.py 复用同一 Gate 状态证据契约。"""
    if not doc.is_file():
        print(f"缺少 SSOT 文档: {doc}", file=sys.stderr)
        return 1
    text = doc.read_text(encoding="utf-8")
    problems: list[str] = []
    for sec in sections:
        if sec not in text:
            problems.append(f"缺少必填节: {sec}")
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        state = cells[2]
        if state in LEGAL_STATES and state == "RED":
            row = line
            has_repro = "复现" in row
            has_evidence = "evidence/e2e/" in row
            has_fix_ref = bool(re.search(r"#[0-9]+|[0-9a-f]{9,40}", row))
            if not (has_repro and has_evidence and has_fix_ref):
                missing = [
                    name
                    for name, ok in (
                        ("复现步骤", has_repro),
                        ("evidence/e2e/ 证据链接", has_evidence),
                        ("修复 PR/commit 引用", has_fix_ref),
                    )
                    if not ok
                ]
                problems.append(
                    f"line {i}: Gate 状态 RED 证据不全（缺 {'、'.join(missing)}）；"
                    "RED 须记录复现步骤+日志+截图并关联修复 PR/commit，禁止直接改状态"
                )
        if re.fullmatch(r"[A-Z]{4,}", state) and state not in LEGAL_STATES:
            problems.append(
                f"line {i}: 非法 Gate 状态值: {state}（合法: {'/'.join(sorted(LEGAL_STATES))}）"
            )
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        print("修复：见文档头部状态取值与 RED 处理规则", file=sys.stderr)
        return 1
    print(f"{label}: OK（结构与状态值合法）")
    return 0


def check() -> int:
    return _check_doc(DOC, REQUIRED_SECTIONS, "macos-release")


if __name__ == "__main__":
    raise SystemExit(check())
