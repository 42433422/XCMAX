#!/usr/bin/env python3
"""Ensure HTTPS xiu-ci.com.conf serves /download/releases、/visualization、公开看板 JSON。

Production uses the canonical vhost whitelist; without these exact locations,
new download-center subpages / JSON fall through to the market SPA.
"""

from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
MARKER = "## CORP_SITE_DOWNLOAD_ROUTES_BEGIN"
ANCHOR = "    ## CORP_SITE_END"
SITE_ROOT = "/root/成都修茈科技有限公司"
ACTION_BOARD_MARKER = "location = /download-action-board.json"
BLOCK = f"""
    ## CORP_SITE_DOWNLOAD_ROUTES_BEGIN —— 独立下载中心子路由 / 可视化 / 公开看板
    location = /download/releases {{
        root {SITE_ROOT};
        try_files /download-releases.html =404;
        add_header Cache-Control "no-cache";
    }}
    location = /download/releases/ {{
        return 301 /download/releases;
    }}
    location = /download-releases.html {{
        return 301 /download/releases;
    }}
    location = /download-action-board.json {{
        root {SITE_ROOT};
        try_files /download-action-board.json =404;
        default_type application/json;
        add_header Cache-Control "no-cache";
    }}
    location = /visualization {{
        root {SITE_ROOT};
        try_files /visualization.html =404;
        add_header Cache-Control "no-cache";
    }}
    location = /visualization/ {{
        return 301 /visualization;
    }}
    location = /visualization.html {{
        return 301 /visualization;
    }}
    ## CORP_SITE_DOWNLOAD_ROUTES_END
"""

ACTION_BOARD_SNIPPET = f"""
    location = /download-action-board.json {{
        root {SITE_ROOT};
        try_files /download-action-board.json =404;
        default_type application/json;
        add_header Cache-Control "no-cache";
    }}
"""


def main() -> None:
    if not CONF.is_file():
        print(f"skip: {CONF} missing")
        return
    text = CONF.read_text(encoding="utf-8")
    if ACTION_BOARD_MARKER in text:
        print("corp download routes already include action-board json")
        return

    if MARKER in text or "location = /download/releases" in text:
        # 旧块已在：在 DOWNLOAD_ROUTES_END 前插入 action-board location
        end_mark = "## CORP_SITE_DOWNLOAD_ROUTES_END"
        if end_mark in text:
            text = text.replace(end_mark, ACTION_BOARD_SNIPPET + "    " + end_mark, 1)
            CONF.write_text(text, encoding="utf-8")
            print("inserted download-action-board.json into existing CORP_SITE_DOWNLOAD_ROUTES")
            return
        # 无 END 标记时，插在 /download/releases 块后
        needle = "location = /download-releases.html"
        idx = text.find(needle)
        if idx < 0:
            raise SystemExit("download routes present but cannot find insert point")
        brace = text.find("}", idx)
        if brace < 0:
            raise SystemExit("cannot find closing brace for download-releases.html")
        insert_at = brace + 1
        CONF.write_text(text[:insert_at] + "\n" + ACTION_BOARD_SNIPPET + text[insert_at:], encoding="utf-8")
        print("inserted download-action-board.json after download-releases.html location")
        return

    idx = text.find("server_name xiu-ci.com;")
    if idx < 0:
        raise SystemExit("server_name xiu-ci.com not found")
    end = text.find(ANCHOR, idx)
    if end < 0:
        raise SystemExit("CORP_SITE_END anchor not found")
    CONF.write_text(text[:end] + BLOCK + "\n" + text[end:], encoding="utf-8")
    print("inserted CORP_SITE_DOWNLOAD_ROUTES into xiu-ci.com.conf")


if __name__ == "__main__":
    main()
