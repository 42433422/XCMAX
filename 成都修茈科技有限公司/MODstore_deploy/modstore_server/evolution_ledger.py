# 成都修茈科技有限公司/MODstore_deploy/modstore_server/evolution_ledger.py
"""演化决策 ledger：append-only JSONL。

每个演化事件（signal_detected / proposal_generated / issue_opened / ... / pack_listed）
都写一行。owner 用 audit_evolution.py 查询。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

LEDGER_FILENAME = "evolution_decisions.jsonl"
_LEDGER_LOCK = threading.Lock()


def _ledger_path() -> Path:
    env_val = os.environ.get("MODSTORE_EVOLUTION_LEDGER_PATH", "")
    if env_val:
        return Path(env_val)
    from modstore_server.evolution_signal_collector import _repo_root

    return (
        Path(_repo_root())
        / "成都修茈科技有限公司"
        / "MODstore_deploy"
        / "modstore_server"
        / "data"
        / LEDGER_FILENAME
    )


def append_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """追加一个事件到 ledger。返回写入的完整记录（含 event_id / timestamp）。"""
    record: Dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
    }
    record.update(event)
    record.setdefault("owner_audit", {"audited": False, "audited_at": None, "verdict": None})

    path = _ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _LEDGER_LOCK:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    return record


def list_events(
    *,
    event_type: Optional[str] = None,
    final_status: Optional[str] = None,
    since_days: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """读 ledger 并按条件过滤。"""
    path = _ledger_path()
    if not path.is_file():
        return []
    cutoff: Optional[datetime] = None
    if since_days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)

    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event_type and evt.get("event_type") != event_type:
                continue
            if final_status and evt.get("final_status") != final_status:
                continue
            if cutoff:
                ts_str = evt.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
            out.append(evt)
    return out


def mark_audited(event_id: str, verdict: str) -> bool:
    """标记某个事件已审计。重写 ledger 文件以更新对应行。"""
    path = _ledger_path()
    if not path.is_file():
        return False
    found = False
    lines_out: List[str] = []
    with _LEDGER_LOCK:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    lines_out.append(line.rstrip("\n"))
                    continue
                if evt.get("event_id") == event_id:
                    evt["owner_audit"] = {
                        "audited": True,
                        "audited_at": datetime.now(UTC).isoformat(),
                        "verdict": verdict,
                    }
                    lines_out.append(json.dumps(evt, ensure_ascii=False, sort_keys=True))
                    found = True
                else:
                    lines_out.append(line.rstrip("\n"))
        if found:
            with path.open("w", encoding="utf-8") as f:
                for ln in lines_out:
                    f.write(ln + "\n")
    return found
