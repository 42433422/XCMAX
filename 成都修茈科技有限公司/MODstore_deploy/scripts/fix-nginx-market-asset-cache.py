#!/usr/bin/env python3
"""chunk 勿 immutable：避免部署间隙 404 被浏览器长期缓存。"""
from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")

OLD = 'add_header Cache-Control "public, max-age=31536000, immutable" always;'
NEW = 'add_header Cache-Control "public, max-age=86400, must-revalidate" always;'


def main() -> None:
    text = CONF.read_text(encoding="utf-8")
    if OLD not in text:
        if NEW in text:
            print("asset cache already fixed")
            return
        raise SystemExit("immutable asset cache header not found")
    count = text.count(OLD)
    text = text.replace(OLD, NEW)
    CONF.write_text(text, encoding="utf-8")
    print(f"replaced {count} asset Cache-Control headers")


if __name__ == "__main__":
    main()
