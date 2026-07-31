#!/usr/bin/env python3
"""从 emp-wf-radial-graph.js 同步机器可读时间轨图 → FHD/config/time_rail_workflow_graph.json。"""

from __future__ import annotations

import argparse
import hashlib
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


def _build_payload() -> dict:
    if not JS_SRC.is_file():
        raise FileNotFoundError(f"missing {JS_SRC}")
    if not EXTRACT_MJS.is_file():
        raise FileNotFoundError(f"missing {EXTRACT_MJS}")
    proc = subprocess.run(
        ["node", str(EXTRACT_MJS), str(JS_SRC)],
        check=True,
        capture_output=True,
        text=True,
    )
    doc = json.loads(proc.stdout)
    doc["source"] = "docs/xcagi-dashboard/emp-wf-radial-graph.js"
    doc["schema"] = "time_rail_workflow_graph/v1"
    return doc


def _canonical_text(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_existing(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def write_outputs(doc: dict) -> tuple[str, int, int]:
    payload = _canonical_text(doc)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(payload, encoding="utf-8")
    DASHBOARD_COPY.write_text(payload, encoding="utf-8")
    return payload, len(doc.get("nodes") or []), len(doc.get("edges") or [])


def check_outputs(doc: dict) -> int:
    expected = _canonical_text(doc)
    fp = _fingerprint(expected)
    mismatches: list[str] = []
    for path in (OUT_JSON, DASHBOARD_COPY):
        current = _read_existing(path)
        if not current:
            mismatches.append(f"{path} missing")
            continue
        if _fingerprint(current) != fp:
            mismatches.append(f"{path} drift")
    if mismatches:
        print("ERROR: time rail graph out of sync:", ", ".join(mismatches), file=sys.stderr)
        print("Run: python3 FHD/scripts/dev/sync_time_rail_workflow_graph.py", file=sys.stderr)
        return 1
    print(f"[ok] time rail graph in sync ({len(doc.get('nodes') or [])} nodes)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync time rail workflow graph JSON from dashboard JS")
    parser.add_argument("--check", action="store_true", help="Verify JSON matches JS without writing")
    args = parser.parse_args()
    try:
        doc = _build_payload()
    except (FileNotFoundError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if args.check:
        return check_outputs(doc)
    _, nodes, edges = write_outputs(doc)
    print(f"[ok] wrote {OUT_JSON} ({nodes} nodes, {edges} edges)")
    print(f"[ok] mirrored {DASHBOARD_COPY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
