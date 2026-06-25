#!/usr/bin/env python3
from pathlib import Path
import sys

TARGET = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/modstore-git/MODstore_deploy/modstore_server/xcmax_admin_api.py")
text = TARGET.read_text(encoding="utf-8")
old = """                for row in report.get("results") if isinstance(report.get("results"), list) else []
                if row.get("lane") == lane"""
new = """                for row in (report.get("results") if isinstance(report.get("results"), list) else [])
                if row.get("lane") == lane"""
if old not in text:
    raise SystemExit("pattern missing")
TARGET.write_text(text.replace(old, new, 1), encoding="utf-8")
print("fixed", TARGET)
