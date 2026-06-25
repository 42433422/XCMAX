#!/usr/bin/env python3
"""手机 App 显示名一致性守卫。

单一真相源:FHD/config/mobile_app.yaml 的 enterprise.display_name。
本脚本读 SSOT,逐一核对各派生位置(安卓/iOS/鸿蒙 entry/鸿蒙 AppScope)是否一致。
不一致 → 非零退出(CI/pre-commit 可阻断)。
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SSOT = REPO / "FHD/config/mobile_app.yaml"


def ssot_name() -> str:
    txt = SSOT.read_text(encoding="utf-8")
    m = re.search(r'display_name:\s*"([^"]+)"', txt)
    if not m:
        sys.exit(f"ERROR: 读不到 SSOT display_name: {SSOT}")
    return m.group(1)


def android(p: Path) -> str:
    m = re.search(r'<string name="app_name">([^<]*)</string>', p.read_text(encoding="utf-8"))
    return m.group(1) if m else "<缺失>"


def ios(p: Path) -> str:
    # 企业版 target XCAGIMobile 在文件中先于个人版,取第一处 APP_DISPLAY_NAME 设置即可
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("APP_DISPLAY_NAME:"):
            return s.split(":", 1)[1].strip().strip('"')
    return "<缺失>"


def harmony(p: Path) -> str:
    data = json.loads(p.read_text(encoding="utf-8"))
    for s in data.get("string", []):
        if s.get("name") == "app_name":
            return s.get("value", "<空>")
    return "<缺失>"


CHECKS = [
    ("安卓", "FHD/mobile-android/app/src/main/res/values/strings.xml", android),
    ("iOS", "FHD/mobile-ios/project.yml", ios),
    ("鸿蒙 entry", "FHD/mobile-harmony/entry/src/main/resources/base/element/string.json", harmony),
    ("鸿蒙 AppScope", "FHD/mobile-harmony/AppScope/resources/base/element/string.json", harmony),
]


def main() -> int:
    want = ssot_name()
    print(f"SSOT display_name = {want!r}")
    bad = 0
    for label, rel, fn in CHECKS:
        got = fn(REPO / rel)
        ok = got == want
        print(f"  [{'OK ' if ok else 'BAD'}] {label}: {got!r}")
        bad += 0 if ok else 1
    if bad:
        print(f"\n❌ {bad} 处与 SSOT 不一致,请同步成 {want!r}")
        return 1
    print("\n✅ 三端显示名全部与 SSOT 一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
