#!/usr/bin/env python3
"""Fix surface-audit page/image routes syntax + sort P-W rows by PNG filename."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/modstore-git/MODstore_deploy/modstore_server/xcmax_admin_api.py"
)

HELPER = '''

def _sort_surface_rows(rows: list) -> list:
    def _key(row: dict) -> str:
        return Path(str((row or {}).get("screenshot_saved") or "")).name

    return sorted([r for r in rows if isinstance(r, dict)], key=_key)
'''

text = TARGET.read_text(encoding="utf-8")

text = text.replace(
    '    }@router.get("/admin/surface-audit/image")',
    '    }\n\n\n@router.get("/admin/surface-audit/image")',
    1,
)

if "_sort_surface_rows" not in text:
    anchor = '@router.get("/admin/surface-audit/lane", response_model=None)'
    text = text.replace(anchor, HELPER.strip() + "\n\n\n" + anchor, 1)

text = text.replace(
    "rows = [r for r in raw_rows if isinstance(r, dict) and r.get(\"lane\") == lane]",
    "rows = _sort_surface_rows([r for r in raw_rows if isinstance(r, dict) and r.get(\"lane\") == lane])",
)

# _lane_payload: sort lane pages before attach b64
old_loop = "        for row in report.get(\"results\") if isinstance(report.get(\"results\"), list) else []:\n            if row.get(\"lane\") != lane:"
new_loop = "        lane_rows = _sort_surface_rows(\n            [\n                row\n                for row in report.get(\"results\") if isinstance(report.get(\"results\"), list) else []\n                if row.get(\"lane\") == lane\n            ]\n        )\n        for row in lane_rows:"
if old_loop in text and "lane_rows = _sort_surface_rows" not in text:
    text = text.replace(old_loop, new_loop, 1)

TARGET.write_text(text, encoding="utf-8")
print("patched", TARGET)

# reorder manifest P-W rows by png name (stable with P-App untouched)
for root in (
    Path("/root/成都修茈科技有限公司/MODstore_deploy/playwright-report/digest-surfaces"),
    Path("/root/modstore-git/MODstore_deploy/playwright-report/digest-surfaces"),
):
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    manifest_path = root / day / "manifest.json"
    if not manifest_path.is_file():
        continue
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = data.get("results") if isinstance(data.get("results"), list) else []
    pw = [r for r in rows if r.get("lane") == "P-W"]
    other = [r for r in rows if r.get("lane") != "P-W"]
    pw.sort(key=lambda r: Path(str(r.get("screenshot_saved") or "")).name)
    data["results"] = pw + other
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print("manifest sorted", manifest_path, "P-W", len(pw))
    break
