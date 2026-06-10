#!/usr/bin/env python3
"""从 emp-wf-radial-graph.js 同步机器可读时间轨图 → FHD/config/time_rail_workflow_graph.json。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FHD_ROOT = SCRIPT_DIR.parent.parent
JS_SRC = FHD_ROOT.parent / "docs" / "xcagi-dashboard" / "emp-wf-radial-graph.js"
EXTRACT_MJS = SCRIPT_DIR / "extract_time_rail_graph.mjs"
OUT_JSON = FHD_ROOT / "config" / "time_rail_workflow_graph.json"
DASHBOARD_COPY = FHD_ROOT.parent / "docs" / "xcagi-dashboard" / "time_rail_workflow_graph.json"


def main() -> int:
    if not JS_SRC.is_file():
        print(f"ERROR: missing {JS_SRC}", file=sys.stderr)
        return 1
    if not EXTRACT_MJS.is_file():
        print(f"ERROR: missing {EXTRACT_MJS}", file=sys.stderr)
        return 1

    proc = subprocess.run(
        ["node", str(EXTRACT_MJS), str(JS_SRC)],
        check=True,
        capture_output=True,
        text=True,
    )
    doc = json.loads(proc.stdout)
    doc["source"] = "docs/xcagi-dashboard/emp-wf-radial-graph.js"
    doc["schema"] = "time_rail_workflow_graph/v1"

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    OUT_JSON.write_text(payload, encoding="utf-8")
    DASHBOARD_COPY.write_text(payload, encoding="utf-8")

    print(f"[ok] wrote {OUT_JSON} ({len(doc.get('nodes') or [])} nodes, {len(doc.get('edges') or [])} edges)")
    print(f"[ok] mirrored {DASHBOARD_COPY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
