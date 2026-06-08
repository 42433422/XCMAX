#!/usr/bin/env python3
"""Patch MODstore daily_digest_surface_audit _wait_page_ready for CJK fonts."""
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py"
)

NEW = '''async def _wait_page_ready(page: Any, *, timeout_ms: int) -> None:
    """等待 SPA/静态页渲染与中文字体就绪，避免截图文字丢失。"""
    font_urls = (
        "https://fonts.googleapis.cn/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap",
        "https://fonts.loli.net/css2?family=Noto+Sans+SC:wght@400;500;700&display=swap",
        "https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;700&display=swap",
    )
    for href in font_urls:
        try:
            await page.evaluate(
                """(href) => {
                  if (document.querySelector('link[data-xcagi-audit-font]')) return;
                  const link = document.createElement('link');
                  link.rel = 'stylesheet';
                  link.href = href;
                  link.setAttribute('data-xcagi-audit-font', '1');
                  document.head.appendChild(link);
                }""",
                href,
            )
            break
        except Exception:
            continue
    try:
        await page.add_style_tag(
            content=(
                '*{font-family:"Noto Sans SC","WenQuanYi Micro Hei","WenQuanYi Zen Hei",'
                '"PingFang SC","Microsoft YaHei","SimHei",sans-serif!important}'
            )
        )
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 30_000))
    except Exception:
        pass
    try:
        await page.evaluate(
            """async () => {
              if (document.fonts && document.fonts.ready) await document.fonts.ready;
              for (let i = 0; i < 40; i++) {
                if (document.fonts && document.fonts.check('16px "Noto Sans SC"')) return true;
                await new Promise(r => setTimeout(r, 250));
              }
              return false;
            }"""
        )
    except Exception:
        pass
    await page.wait_for_timeout(2000)
'''

text = TARGET.read_text(encoding="utf-8")
text2, n = re.subn(
    r"async def _wait_page_ready\(page: Any, \*, timeout_ms: int\) -> None:.*?(?=\nasync def _apply_page_prepare)",
    NEW + "\n\n\n",
    text,
    count=1,
    flags=re.S,
)
if n != 1:
    raise SystemExit(f"patch failed n={n}")
TARGET.write_text(text2, encoding="utf-8")
print("patched", TARGET)
