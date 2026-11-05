#!/usr/bin/env python3
"""Ensure HTTPS xiu-ci.com.conf serves the official-site SSOT pages and data.

Production uses /etc/nginx/conf.d/xiu-ci.com.conf (exact HTML whitelist).
2026-09 官网改版新增 verify.html（验证中心）/ pricing.html（完整价格页）与
/site/data/public-site.json（SSOT 聚合数据）；不在白名单时会落到 404。
本脚本以幂等方式把它们的 location 注入 canonical conf（CORP_SITE_PAGES 标记块）。
"""

from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
MARKER_BEGIN = "## CORP_SITE_PAGES_BEGIN"
MARKER_END = "## CORP_SITE_PAGES_END"
ANCHOR = "    ## CORP_SITE_END"
BLOCK = """
    ## CORP_SITE_PAGES_BEGIN —— 官网 SSOT 改版页面与数据（禁止 SPA 回退成 index.html）
    location = /verify.html {
        root /root/成都修茈科技有限公司;
        try_files $uri =404;
        add_header Cache-Control "no-cache";
    }
    location = /pricing.html {
        root /root/成都修茈科技有限公司;
        try_files $uri =404;
        add_header Cache-Control "no-cache";
    }
    location ^~ /site/data/ {
        root /root/成都修茈科技有限公司;
        try_files $uri =404;
        add_header Cache-Control "no-cache";
    }
    location ^~ /data/ {
        root /root/成都修茈科技有限公司;
        try_files $uri =404;
        add_header Cache-Control "no-cache";
    }
    ## CORP_SITE_PAGES_END
"""


def main() -> None:
    if not CONF.is_file():
        print(f"skip: {CONF} missing")
        return
    text = CONF.read_text(encoding="utf-8")
    if MARKER_BEGIN in text:
        # 幂等更新：替换整个标记块（页面清单演进时同步）
        start = text.index(MARKER_BEGIN)
        end = text.index(MARKER_END, start) + len(MARKER_END)
        new_block = BLOCK.rstrip("\n")
        text = text[:start] + new_block.lstrip("\n") + text[end:]
        print("corp pages location updated")
    else:
        idx = text.find("server_name xiu-ci.com;")
        if idx < 0:
            raise SystemExit("server_name xiu-ci.com not found in canonical conf")
        end = text.find(ANCHOR, idx)
        if end < 0:
            raise SystemExit("CORP_SITE_END anchor not found after xiu-ci.com server")
        text = text[:end] + BLOCK + text[end:]
        print("corp pages location inserted")
    CONF.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
