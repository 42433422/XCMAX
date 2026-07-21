#!/usr/bin/env python3
"""Ensure HTTPS xiu-ci.com.conf serves /partials/* as files, not SPA index.html.

Production uses /etc/nginx/conf.d/xiu-ci.com.conf (not nginx-xiu-ci-root.conf).
Corp pages are an exact HTML whitelist; without this location, /partials/header.html
falls through to the market SPA and returns the homepage document.
"""

from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
MARKER_BEGIN = "## CORP_SITE_PARTIALS_BEGIN"
ANCHOR = "    ## CORP_SITE_END"
BLOCK = """
    ## CORP_SITE_PARTIALS_BEGIN —— 官网共享导航/页脚（禁止 SPA 回退成 index.html）
    location ^~ /partials/ {
        root /root/成都修茈科技有限公司;
        try_files $uri =404;
        add_header Cache-Control "no-cache";
    }
    ## CORP_SITE_PARTIALS_END
"""


def main() -> None:
    if not CONF.is_file():
        print(f"skip: {CONF} missing")
        return
    text = CONF.read_text(encoding="utf-8")
    if MARKER_BEGIN in text:
        print("corp partials location already present")
        return
    idx = text.find("server_name xiu-ci.com;")
    if idx < 0:
        raise SystemExit("server_name xiu-ci.com not found in canonical conf")
    end = text.find(ANCHOR, idx)
    if end < 0:
        raise SystemExit("CORP_SITE_END anchor not found after xiu-ci.com server")
    CONF.write_text(text[:end] + BLOCK + "\n" + text[end:], encoding="utf-8")
    print("inserted CORP_SITE_PARTIALS block into xiu-ci.com.conf")


if __name__ == "__main__":
    main()
