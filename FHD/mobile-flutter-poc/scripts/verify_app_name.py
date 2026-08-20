#!/usr/bin/env python3
"""Verify the Flutter Android/iOS display names against mobile_app.yaml."""

from __future__ import annotations

import plistlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SSOT = REPO / "FHD/config/mobile_app.yaml"


def ssot_name() -> str:
    match = re.search(r'display_name:\s*"([^"]+)"', SSOT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"ERROR: cannot read display_name from {SSOT}")
    return match.group(1)


def android_name() -> str:
    path = REPO / "FHD/mobile-flutter-poc/android/app/src/main/res/values/strings.xml"
    match = re.search(
        r'<string name="app_name">([^<]*)</string>',
        path.read_text(encoding="utf-8"),
    )
    return match.group(1) if match else "<missing>"


def ios_name() -> str:
    path = REPO / "FHD/mobile-flutter-poc/ios/Runner/Info.plist"
    with path.open("rb") as handle:
        payload = plistlib.load(handle)
    return str(payload.get("CFBundleDisplayName") or "<missing>")


def main() -> int:
    expected = ssot_name()
    checks = (("Flutter Android", android_name()), ("Flutter iOS", ios_name()))
    print(f"SSOT display_name = {expected!r}")
    failures = 0
    for label, actual in checks:
        ok = actual == expected
        print(f"  [{'OK ' if ok else 'BAD'}] {label}: {actual!r}")
        failures += 0 if ok else 1
    if failures:
        print(f"\n{failures} target(s) differ from {expected!r}")
        return 1
    print("\nFlutter Android/iOS display names match the SSOT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
