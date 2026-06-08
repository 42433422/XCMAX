#!/usr/bin/env python3
"""P-W/P-S 表面巡检改为 1280×720 视口截图（非 full_page）。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py"
)

OLD = "        png = await page.screenshot(full_page=True, type=\"png\")"
NEW = "        png = await page.screenshot(full_page=False, type=\"png\")"

text = TARGET.read_text(encoding="utf-8")
if OLD not in text:
    if NEW in text:
        print("already patched", TARGET)
        raise SystemExit(0)
    raise SystemExit("screenshot line not found")
text = text.replace(OLD, NEW, 1)
TARGET.write_text(text, encoding="utf-8")
print("patched", TARGET)
