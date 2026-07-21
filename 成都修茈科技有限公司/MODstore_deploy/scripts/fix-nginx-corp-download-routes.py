#!/usr/bin/env python3
"""Ensure HTTPS xiu-ci.com.conf serves /download/releases and /visualization.

Production uses the canonical vhost whitelist; without these exact locations,
new download-center subpages fall through to the market SPA.
"""

from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
MARKER = "## CORP_SITE_DOWNLOAD_ROUTES_BEGIN"
ANCHOR = "    ## CORP_SITE_END"
SITE_ROOT = "/root/成都修茈科技有限公司"
BLOCK = f"""
    ## CORP_SITE_DOWNLOAD_ROUTES_BEGIN —— 独立下载中心子路由 / 可视化
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
    if MARKER in text or "location = /download/releases" in text:
        print("corp download routes already present")
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
