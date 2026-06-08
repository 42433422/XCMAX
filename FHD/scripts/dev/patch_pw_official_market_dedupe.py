#!/usr/bin/env python3
"""P-W 去重：官网 + AI 市场 Tab（去掉重复 AI 市场入口与重复软件下载）。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

OLD_ENTRY = '''_PW_MARKET_ENTRY_PAGES: Tuple[Tuple[str, str], ...] = (
    ("AI 市场", "/market/ai-store"),
    ("软件下载", "/market/workbench/download"),
)'''

NEW_ENTRY = '''_PW_MARKET_ENTRY_PAGES: Tuple[Tuple[str, str], ...] = (
    ("软件下载", "/market/workbench/download"),
)'''

OLD_PS = '''_PS_PUBLIC_PAGES: Tuple[Tuple[str, str], ...] = (
    ("市场关于", "/market/about"),
    ("会员方案", "/market/plans"),
    ("登录页", "/market/login"),
    ("注册页", "/market/register"),
    ("软件下载", "/market/workbench/download"),
    ("模板中心", "/market/templates"),
)'''

NEW_PS = '''_PS_PUBLIC_PAGES: Tuple[Tuple[str, str], ...] = (
    ("市场关于", "/market/about"),
    ("会员方案", "/market/plans"),
    ("登录页", "/market/login"),
    ("注册页", "/market/register"),
)'''

if __name__ == "__main__":
    text = TARGET.read_text(encoding="utf-8")
    changed = False
    if OLD_ENTRY in text:
        text = text.replace(OLD_ENTRY, NEW_ENTRY, 1)
        changed = True
    elif NEW_ENTRY in text:
        pass
    else:
        raise SystemExit("_PW_MARKET_ENTRY_PAGES block not found")

    if OLD_PS in text:
        text = text.replace(OLD_PS, NEW_PS, 1)
        changed = True
    elif NEW_PS in text:
        pass
    else:
        raise SystemExit("_PS_PUBLIC_PAGES block not found")

    if changed:
        TARGET.write_text(text, encoding="utf-8")
        print("patched P-W official+market dedupe", TARGET)
    else:
        print("already deduped", TARGET)
