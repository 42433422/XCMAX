#!/usr/bin/env python3
"""index.html 仅用 no-cache，避免旧 index + immutable 长期缓存导致 chunk 404。"""
from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")

OLD = 'add_header Cache-Control "no-store, max-age=31536000, immutable, proxy-revalidate" always;'
NEW = 'add_header Cache-Control "no-cache, no-store, must-revalidate" always;'


def main() -> None:
    text = CONF.read_text(encoding="utf-8")
    if NEW in text:
        print("index cache already fixed")
        return
    if OLD not in text:
        raise SystemExit("market index.html cache block not found")
    CONF.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")
    print("updated index.html Cache-Control")


if __name__ == "__main__":
    main()
