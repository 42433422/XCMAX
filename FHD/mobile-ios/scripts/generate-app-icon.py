#!/usr/bin/env python3
"""Generate the iOS AppIcon from the checked-in xiu-ci brand logo."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LOGO = ROOT / "Brand" / "xiu-ci-logo.png"
APPICON_DIR = ROOT / "XCAGIMobile" / "Resources" / "Assets.xcassets" / "AppIcon.appiconset"
ICON_PATH = APPICON_DIR / "AppIcon-1024.png"
CONTENTS_PATH = APPICON_DIR / "Contents.json"


def run(command: list[str]) -> str:
    result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.stdout


def main() -> None:
    if not SOURCE_LOGO.exists():
        raise SystemExit(f"Missing source logo: {SOURCE_LOGO}")
    if shutil.which("sips") is None:
        raise SystemExit("sips is required to generate the iOS AppIcon on macOS")

    APPICON_DIR.mkdir(parents=True, exist_ok=True)
    run(["sips", "-z", "1024", "1024", str(SOURCE_LOGO), "--out", str(ICON_PATH)])

    meta = run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", "-g", "hasAlpha", str(ICON_PATH)])
    if "pixelWidth: 1024" not in meta or "pixelHeight: 1024" not in meta:
        raise SystemExit(f"Generated icon has invalid dimensions:\n{meta}")
    if "hasAlpha: yes" in meta:
        raise SystemExit("Generated icon must not include alpha for App Store upload")

    CONTENTS_PATH.write_text(
        json.dumps(
            {
                "images": [
                    {
                        "filename": ICON_PATH.name,
                        "idiom": "universal",
                        "platform": "ios",
                        "size": "1024x1024",
                    }
                ],
                "info": {"author": "xcode", "version": 1},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Generated {ICON_PATH} from {SOURCE_LOGO}")


if __name__ == "__main__":
    main()
