#!/usr/bin/env python3
"""P-W 对齐侧栏入口：聊/做/说分镜 + 客服/沙箱；去掉无入口 about。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

MARKER = "_PW_WB_MODE_PAGES"

WB_PAGES = '''
_PW_WB_MODE_PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("工作台·聊", "/market/workbench/home", "direct"),
    ("工作台·做", "/market/workbench/home", "make"),
    ("工作台·说", "/market/workbench/home", "voice"),
)

_PW_SIDEBAR_PAGES: Tuple[Tuple[str, str], ...] = (
    ("AI 客服", "/market/customer-service"),
    ("沙箱测试", "/market/sandbox"),
)
'''

BUILD_LOOP = '''
    for name, path, mode in _PW_WB_MODE_PAGES:
        out.append(
            SurfaceTarget(
                "P-W",
                "网站 P-W",
                name,
                path,
                "desktop",
                prepare=f"wb_mode:{mode}",
            )
        )

    for name, path in _PW_SIDEBAR_PAGES:
        out.append(SurfaceTarget("P-W", "网站 P-W", name, path, "desktop"))

'''

APPLY_BRANCH = '''    if prepare.startswith("wb_mode:"):
        mode = prepare.split(":", 1)[1]
        labels = {"direct": "聊", "make": "做", "voice": "说"}
        label = labels.get(mode, "")
        if label:
            btn = page.locator(".wb-sidebar-modes button.wb-sidebar-mode-btn").filter(has_text=label)
            await btn.first.click(timeout=min(timeout_ms, 20_000))
            await page.wait_for_timeout(800)
        return
'''

if __name__ == "__main__":
    text = TARGET.read_text(encoding="utf-8")
    changed = False

    if MARKER not in text:
        anchor = "_PW_MARKET_ADMIN_PAGES:"
        if anchor not in text:
            raise SystemExit("_PW_MARKET_ADMIN_PAGES not found")
        idx = text.find(anchor)
        end = text.find("\n\n", text.find(")\n", idx))
        if end < 0:
            end = text.find("\n_PS_PUBLIC", idx)
        text = text[:end] + WB_PAGES + text[end:]
        changed = True

    text2 = text.replace('    ("市场关于", "/market/about"),\n', "")
    if text2 != text:
        text = text2
        changed = True

    if "for name, path, mode in _PW_WB_MODE_PAGES:" not in text:
        needle = "    for name, path in _PW_MARKET_ADMIN_PAGES:"
        if needle not in text:
            raise SystemExit("admin pages loop not found")
        text = text.replace(needle, BUILD_LOOP + needle, 1)
        changed = True

    if 'prepare.startswith("wb_mode:")' not in text:
        anchor = '    if prepare.startswith("ai_store_tab:"):'
        if anchor not in text:
            raise SystemExit("ai_store_tab branch not found")
        text = text.replace(anchor, APPLY_BRANCH + anchor, 1)
        changed = True

    if changed:
        TARGET.write_text(text, encoding="utf-8")
        print("patched wb modes + sidebar pages", TARGET)
    else:
        print("already patched", TARGET)
