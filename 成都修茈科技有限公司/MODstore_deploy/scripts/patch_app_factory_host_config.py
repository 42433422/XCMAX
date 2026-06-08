#!/usr/bin/env python3
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
p = root / "modstore_server" / "api" / "app_factory.py"
text = p.read_text(encoding="utf-8")
needle = '    "modstore_server.xcmax_admin_api",\n)'
repl = '    "modstore_server.xcmax_admin_api",\n    "modstore_server.api.host_config_routes",\n)'
if "modstore_server.api.host_config_routes" in text:
    print("already has host_config_routes")
elif needle in text:
    p.write_text(text.replace(needle, repl, 1), encoding="utf-8")
    print("patched app_factory.py")
else:
  # alternate closing
    needle2 = '    "modstore_server.xcmax_admin_api",\n)\n'
    if needle2 in text and "host_config" not in text:
        p.write_text(text.replace(needle2, repl + "\n", 1), encoding="utf-8")
        print("patched (alt)")
    else:
        raise SystemExit("pattern not found in app_factory.py")
