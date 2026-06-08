#!/usr/bin/env python3
"""Fix /api/workbench/voice/ nginx WebSocket block on xiu-ci.com."""
from __future__ import annotations

from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")

GOOD = """    # 工作台语音 S2S WebSocket（^~ 优先匹配，须在正则 location 之前）
    location ^~ /api/workbench/voice/ {
        proxy_pass http://127.0.0.1:9999;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_intercept_errors off;
        proxy_connect_timeout 10s;
        proxy_send_timeout 3600s;
        proxy_read_timeout 86400s;
    }

"""


def main() -> None:
    text = CONF.read_text(encoding="utf-8")
    start = text.find("    # 工作台语音 S2S WebSocket")
    end = text.find("    # ASR 语音识别 WebSocket", start if start >= 0 else 0)
    if start >= 0 and end > start:
        text = text[:start] + GOOD + text[end:]
        CONF.write_text(text, encoding="utf-8")
        print("replaced broken workbench voice block")
        return
    needle = "    # ASR 语音识别 WebSocket（^~ 优先匹配）"
    if needle not in text:
        raise SystemExit("ASR marker not found")
    text = text.replace(needle, GOOD + needle, 1)
    CONF.write_text(text, encoding="utf-8")
    print("inserted workbench voice block")


if __name__ == "__main__":
    main()
