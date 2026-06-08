#!/usr/bin/env python3
"""从 P-W 巡检移除「模板中心」（侧栏无入口，非官网+AI市场面）。"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)

OLD = '    ("模板中心", "/market/templates"),\n'
NEW = ''


if __name__ == "__main__":
    text = TARGET.read_text(encoding="utf-8")
    if OLD not in text:
        if "模板中心" not in text:
            print("already removed", TARGET)
        else:
            raise SystemExit("templates line pattern changed")
        sys.exit(0)
    text = text.replace(OLD, NEW, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("removed 模板中心 from P-W targets", TARGET)
