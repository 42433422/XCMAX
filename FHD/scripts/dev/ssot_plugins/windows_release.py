#!/usr/bin/env python3
"""windows-release 域 check：WINDOWS_RELEASE_SSOT.md 结构与状态值合法性。

与 macos_release.py 共享同一校验核心（必填节 + Gate 状态值 + RED 证据契约），
Windows 文档节标题不同，仅传参差异。

用法: python scripts/dev/ssot_plugins/windows_release.py check
退出码: 0=OK 1=DRIFT
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from macos_release import _check_doc

ROOT = Path(__file__).resolve().parents[3]  # FHD/
DOC = ROOT / "docs" / "WINDOWS_RELEASE_SSOT.md"
REQUIRED_SECTIONS = (
    "## 1. 当前版本信息",
    "## 3. Release Gate 定义",
    "## 4. Release Gate 状态",
    "## 6. 实机验收任务",
    "## 8. 发版复用 Runbook",
)


def check() -> int:
    return _check_doc(DOC, REQUIRED_SECTIONS, "windows-release")


if __name__ == "__main__":
    raise SystemExit(check())
