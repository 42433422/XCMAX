#!/usr/bin/env python3
"""Ensure HTTPS xiu-ci.com.conf serves breakpoint/goals pages + public board assets.

Canonical conf already has /download、/download/releases、/visualization.
This script only manages the newer board routes and never re-inserts those.
"""

from __future__ import annotations

import re
from pathlib import Path

CONF = Path("/etc/nginx/conf.d/xiu-ci.com.conf")
MARKER = "## CORP_SITE_DOWNLOAD_ROUTES_BEGIN"
END_MARKER = "## CORP_SITE_DOWNLOAD_ROUTES_END"
SITE_ROOT = "/root/成都修茈科技有限公司"

BLOCK = f"""    ## CORP_SITE_DOWNLOAD_ROUTES_BEGIN —— 断点清单 / 工作目标 / 公开看板
    location = /download/breakpoints {{
        include /etc/nginx/snippets/security-headers.conf;
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
        include /etc/nginx/snippets/security-headers.conf;
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
    ## CORP_SITE_DOWNLOAD_ROUTES_END
"""


def _strip_route_blocks(text: str) -> str:
    while MARKER in text:
        start = text.find(MARKER)
        line_start = text.rfind("\n", 0, start) + 1
        end = text.find(END_MARKER, start)
        if end < 0:
            raise SystemExit("broken DOWNLOAD_ROUTES block without END marker")
        end_line = text.find("\n", end)
        end = len(text) if end_line < 0 else end_line + 1
        text = text[:line_start] + text[end:]
    return text


def _strip_orphan_board_locations(text: str) -> str:
    patterns = [
        r"\n\s*location = /download/breakpoints\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download/breakpoints/\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download-breakpoints\.html\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download/goals\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download/goals/\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download-goals\.html\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download-action-board\.json\s*\{[\s\S]*?\n\s*\}\n",
        r"\n\s*location = /download-action-board\.js\s*\{[\s\S]*?\n\s*\}\n",
    ]
    for pat in patterns:
        text = re.sub(pat, "\n", text)
    return text


def main() -> None:
    if not CONF.is_file():
        print(f"skip: {CONF} missing")
        return
    text = CONF.read_text(encoding="utf-8")
    text = _strip_route_blocks(text)
    text = _strip_orphan_board_locations(text)

    # Prefer inserting right after the canonical download-releases.html redirect.
    needle = "location = /download-releases.html"
    idx = text.find(needle)
    if idx >= 0:
        brace = text.find("}", idx)
        if brace < 0:
            raise SystemExit("cannot find closing brace for download-releases.html")
        insert_at = brace + 1
        CONF.write_text(text[:insert_at] + "\n\n" + BLOCK + text[insert_at:], encoding="utf-8")
        print("installed board routes after /download-releases.html")
        return

    # Fallback: after /download exact location
    needle = "location = /download {"
    idx = text.find(needle)
    if idx >= 0:
        brace = text.find("}", idx)
        if brace < 0:
            raise SystemExit("cannot find closing brace for /download")
        insert_at = brace + 1
        CONF.write_text(text[:insert_at] + "\n\n" + BLOCK + text[insert_at:], encoding="utf-8")
        print("installed board routes after /download")
        return

    raise SystemExit("no insertion point near /download routes")


if __name__ == "__main__":
    main()
