"""本机 duty graph 状态 append API。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

router = APIRouter(tags=["admin-duty-graph"])

_STATUS_PATH = Path("data/local_duty_graph_status.jsonl")


@router.post("/duty-graph/local-status", response_model=None)
def append_local_duty_graph_status(body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
    record = dict(body or {})
    record.setdefault("ts", datetime.now(UTC).isoformat())
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _STATUS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"success": True, "path": str(_STATUS_PATH)}
