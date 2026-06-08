#!/usr/bin/env python3
"""验收六线事件轨：O7 backlog + O4 incident + status API。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FHD = Path(__file__).resolve().parents[1]
if str(FHD) not in sys.path:
    sys.path.insert(0, str(FHD))

from app.application.six_line_event_app_service import get_six_line_event_app_service


def main() -> int:
    svc = get_six_line_event_app_service()
    o7 = svc.dispatch({"step_id": "O7", "status": "completed", "payload": {"verify": True}})
    if not o7.get("matched"):
        print("FAIL: O7 not matched", o7)
        return 1
    o4 = svc.dispatch(
        {"step_id": "O4", "status": "anomaly", "event_type": "payment.anomaly", "payload": {}}
    )
    if not o4.get("matched") or o4.get("priority") != "P0":
        print("FAIL: O4 payment", o4)
        return 1
    snap = svc.status_snapshot()
    if snap.get("operations_routes", 0) < 10:
        print("FAIL: operations_routes", snap)
        return 1
    backlog = svc.list_backlog_for_digest(limit=10)
    if not any(r.get("step_id") == "O7" for r in backlog):
        print("FAIL: backlog missing O7", backlog)
        return 1
    print("OK six_line_event_rail")
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
