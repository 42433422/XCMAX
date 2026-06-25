#!/usr/bin/env python3
"""Repair _lane_payload loop after bad patch."""
from pathlib import Path
import sys

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/modstore-git/MODstore_deploy/modstore_server/xcmax_admin_api.py")
text = TARGET.read_text(encoding="utf-8")

broken = """        for row in lane_rows:
                continue
            pages.append("""
fixed = """        for row in lane_rows:
            pages.append("""

if broken not in text:
    print("already fixed or pattern missing")
else:
    text = text.replace(broken, fixed, 1)
    TARGET.write_text(text, encoding="utf-8")
    print("fixed loop", TARGET)
