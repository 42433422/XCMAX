#!/usr/bin/env python3
"""windows-release：共享交付证据契约，并阻断旧 NSIS 载荷冒充新版安装包。"""

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
    status = _check_doc(DOC, REQUIRED_SECTIONS, "windows-release")
    build = (ROOT / "scripts/package/build-installer.ps1").read_text(encoding="utf-8")
    all_skus = (ROOT / "scripts/package/build-all-skus.ps1").read_text(encoding="utf-8")
    if "SkipUiInstaller" in build + all_skus or "XcagiInstaller.csproj" not in build:
        print("[windows-release] DRIFT: Windows delivery must use the WPF installer")
        return 1
    for name in ("build-windows-installer.sh", "build-windows-electron-only.sh"):
        if 'OUT_DIR="${ROOT}/release/_windows-payload/' not in (ROOT / "scripts/package" / name).read_text():
            print(f"[windows-release] DRIFT: {name} must not write delivery installers")
            return 1
    return status


if __name__ == "__main__":
    raise SystemExit(check())
