#!/usr/bin/env python3
"""One-off: ensure api_mod_ai_scaffold passes industry_id to runner."""

from pathlib import Path

import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
p = root / "modstore_server" / "api" / "authoring.py"
text = p.read_text(encoding="utf-8")
if "industry_id=body.industry_id" in text:
    print("already patched")
    raise SystemExit(0)
needles = [
    (
        "replace=body.replace,\n                provider=body.provider,",
        "replace=body.replace,\n                industry_id=body.industry_id,\n                provider=body.provider,",
    ),
    (
        "replace=body.replace,\n            provider=body.provider,",
        "replace=body.replace,\n            industry_id=body.industry_id,\n            provider=body.provider,",
    ),
]
for needle, repl in needles:
    if needle in text:
        p.write_text(text.replace(needle, repl, 1), encoding="utf-8")
        print("patched")
        raise SystemExit(0)
raise SystemExit("pattern not found")
