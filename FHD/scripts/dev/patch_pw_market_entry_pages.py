#!/usr/bin/env python3
"""P-W 增加 AI 市场 + 软件下载 两页（官网导航入口）。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py"
)

OLD = '''    ("Excel转AI", "/excel-to-ai.html"),
)

_PS_PUBLIC_PAGES'''

NEW = '''    ("Excel转AI", "/excel-to-ai.html"),
)

_PW_MARKET_ENTRY_PAGES: Tuple[Tuple[str, str], ...] = (
    ("AI 市场", "/market/ai-store"),
    ("软件下载", "/market/workbench/download"),
)

_PS_PUBLIC_PAGES'''

text = TARGET.read_text(encoding="utf-8")
if "_PW_MARKET_ENTRY_PAGES" in text:
    print("already patched", TARGET)
    raise SystemExit(0)
if OLD not in text:
    raise SystemExit("anchor not found")
text = text.replace(OLD, NEW, 1)

LOOP_OLD = '''    for name, path in _STATIC_PW_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PS_PUBLIC_PAGES:'''

LOOP_NEW = '''    for name, path in _STATIC_PW_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PW_MARKET_ENTRY_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

    for name, path in _PS_PUBLIC_PAGES:'''

if LOOP_OLD not in text:
    raise SystemExit("loop anchor not found")
text = text.replace(LOOP_OLD, LOOP_NEW, 1)
TARGET.write_text(text, encoding="utf-8")
print("patched", TARGET)
