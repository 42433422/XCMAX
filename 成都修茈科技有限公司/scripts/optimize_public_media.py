#!/usr/bin/env python3
"""为官网引用的真实截图生成 WebP 优化副本（assets/optimized/）。

来源只读 capabilities/assets/evidence/ 的原始证据文件；WebP 仅作为展示性能优化，
原始 PNG 与其 SHA256 仍是证据正本。幂等：WebP 已存在且比源新则跳过。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = SITE_ROOT / "assets" / "optimized"


def collect_media() -> list[Path]:
    files: list[Path] = []
    ps = SITE_ROOT / "site" / "data" / "public-site.json"
    data = json.loads(ps.read_text(encoding="utf-8"))
    hero = (data.get("hero_media") or {}).get("file")
    if hero:
        files.append(SITE_ROOT / hero.lstrip("/"))
    for case in data.get("cases", []):
        for shot in case.get("screenshots", []):
            files.append(SITE_ROOT / shot["public_path"].lstrip("/"))
    for f in data.get("evidence", {}).get("features", []):
        for m in f.get("media", []):
            if m.get("kind") == "screenshot" and m.get("public_path"):
                files.append(SITE_ROOT / m["public_path"].lstrip("/"))
    return sorted({f for f in files if f.exists()})


def main() -> None:
    try:
        from PIL import Image
    except ImportError:
        print("[optimize] FAIL: 需要 Pillow", file=sys.stderr)
        raise SystemExit(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made = skipped = 0
    for src in collect_media():
        dst = OUT_DIR / (src.stem + ".webp")
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            continue
        img = Image.open(src)
        img.save(dst, "WEBP", quality=82, method=6)
        ratio = dst.stat().st_size / max(src.stat().st_size, 1)
        print(f"[optimize] {src.name} → {dst.name}  {src.stat().st_size >> 10}KB → {dst.stat().st_size >> 10}KB ({ratio:.0%})")
        made += 1
    print(f"[optimize] done: {made} generated, {skipped} up-to-date → {OUT_DIR}")


if __name__ == "__main__":
    main()
