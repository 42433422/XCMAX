#!/usr/bin/env python3
"""生成 iOS 占位 AppIcon（1024×1024 单尺寸，对标 Xcode 14+ single-size app icon）。

⚠️ 这是 **占位** 图标，仅为让 App 通过图标校验 / 在 CI 中产出有效 bundle。
   正式发版前请用真实品牌图标替换 `AppIcon-1024.png`（保持 1024×1024、无 alpha、无圆角，
   圆角由 iOS 自动遮罩）。

用法（本机有 Pillow 即可，无需 Xcode）：
    python3 FHD/mobile-ios/scripts/gen_placeholder_appicon.py
"""
from __future__ import annotations

import pathlib

from PIL import Image, ImageDraw, ImageFont

OUT = (
    pathlib.Path(__file__).resolve().parents[1]
    / "XCAGIMobile/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png"
)

SIZE = 1024
TOP = (79, 70, 229)   # indigo  #4F46E5
BOT = (6, 182, 212)   # cyan    #06B6D4

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ("/System/Library/Fonts/Helvetica.ttc", 1),
    ("/System/Library/Fonts/SFNS.ttf", 0),
    ("/Library/Fonts/Arial.ttf", 0),
]
CJK_CANDIDATES = [
    ("/System/Library/Fonts/PingFang.ttc", 0),
    ("/System/Library/Fonts/STHeiti Medium.ttc", 0),
]


def _load(cands, px):
    for path, idx in cands:
        if pathlib.Path(path).is_file():
            try:
                return ImageFont.truetype(path, px, index=idx)
            except Exception:
                continue
    return None


def main() -> None:
    img = Image.new("RGB", (SIZE, SIZE), TOP)
    px = img.load()
    # 对角渐变（左上 indigo → 右下 cyan）
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * (SIZE - 1))
            px[x, y] = (
                int(TOP[0] + (BOT[0] - TOP[0]) * t),
                int(TOP[1] + (BOT[1] - TOP[1]) * t),
                int(TOP[2] + (BOT[2] - TOP[2]) * t),
            )

    draw = ImageDraw.Draw(img)
    wordmark = _load(FONT_CANDIDATES, 420)
    if wordmark is not None:
        box = draw.textbbox((0, 0), "XC", font=wordmark)
        w, h = box[2] - box[0], box[3] - box[1]
        draw.text(
            ((SIZE - w) / 2 - box[0], SIZE * 0.30 - box[1]),
            "XC", font=wordmark, fill=(255, 255, 255),
        )
    cjk = _load(CJK_CANDIDATES, 150)
    if cjk is not None:
        box = draw.textbbox((0, 0), "修茈", font=cjk)
        w = box[2] - box[0]
        draw.text(
            ((SIZE - w) / 2 - box[0], SIZE * 0.66),
            "修茈", font=cjk, fill=(255, 255, 255),
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
