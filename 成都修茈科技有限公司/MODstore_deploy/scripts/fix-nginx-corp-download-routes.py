#!/usr/bin/env python3
"""Ensure HTTPS xiu-ci.com.conf serves download center subpages and public board assets."""

from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
MARKER = "## CORP_SITE_DOWNLOAD_ROUTES_BEGIN"
END_MARKER = "## CORP_SITE_DOWNLOAD_ROUTES_END"
ANCHOR = "    ## CORP_SITE_END"
SITE_ROOT = "/root/成都修茈科技有限公司"

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
    location = /download/breakpoints {{
        root {SITE_ROOT};
        try_files /download-breakpoints.html =404;
        add_header Cache-Control "no-cache";
    }}
    location = /download/breakpoints/ {{
        return 301 /download/breakpoints;
    }}
    location = /download-breakpoints.html {{
        return 301 /download/breakpoints;
    }}
    location = /download/goals {{
        root {SITE_ROOT};
        try_files /download-goals.html =404;
        add_header Cache-Control "no-cache";
    }}
    location = /download/goals/ {{
        return 301 /download/goals;
    }}
    location = /download-goals.html {{
        return 301 /download/goals;
    }}
    location = /download-action-board.json {{
        root {SITE_ROOT};
        try_files /download-action-board.json =404;
        default_type application/json;
        add_header Cache-Control "no-cache";
    }}
    location = /download-action-board.js {{
        root {SITE_ROOT};
        try_files /download-action-board.js =404;
        default_type application/javascript;
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


def main() -> None:
    if not CONF.is_file():
        print(f"skip: {CONF} missing")
        return
    text = CONF.read_text(encoding="utf-8")
    if MARKER in text and END_MARKER in text:
        start = text.find(MARKER)
        line_start = text.rfind("\n", 0, start) + 1
        end = text.find(END_MARKER)
        end_line = text.find("\n", end)
        end = len(text) if end_line < 0 else end_line + 1
        text = text[:line_start] + BLOCK.lstrip("\n") + text[end:]
        CONF.write_text(text, encoding="utf-8")
        print("replaced CORP_SITE_DOWNLOAD_ROUTES block")
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
