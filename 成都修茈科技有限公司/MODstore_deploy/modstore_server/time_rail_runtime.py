"""时间轨节点 runtime 快照持久化（last_run / ok / guard_active 辅助）。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_lock = Lock()


def _runtime_path() -> Path:
    raw = (os.environ.get("MODSTORE_TIME_RAIL_RUNTIME_JSON") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    try:
        from modstore_server.models_db import default_db_path

        return default_db_path().parent / "time_rail_node_runtime.json"
    except Exception:
        return Path(__file__).resolve().parent.parent / "data" / "time_rail_node_runtime.json"


def _load_store() -> Dict[str, Any]:
    path = _runtime_path()
    if not path.is_file():
        return {"version": 1, "nodes": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("nodes"), dict):
            return doc
    except Exception:
        logger.exception("time_rail_runtime: load failed path=%s", path)
    return {"version": 1, "nodes": {}}


def _save_store(doc: Dict[str, Any]) -> None:
    path = _runtime_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def record_node_run(
    node_id: str,
    *,
    ok: Optional[bool],
    source: str = "",
    meta: Optional[Dict[str, Any]] = None,
    proof_status: Optional[str] = None,
) -> Dict[str, Any]:
    """日更 job 完成时写入节点快照。"""
    nid = (node_id or "").strip()
    if not nid:
        return {"ok": False, "reason": "empty node_id"}

    now = datetime.now(timezone.utc).isoformat()
    row = {
        "last_run": now,
        "ok": bool(ok) if ok is not None else None,
        "source": (source or "").strip(),
        "meta": dict(meta or {}),
        "updated_at": now,
    }
    if proof_status:
        row["proof_status"] = str(proof_status)
    with _lock:
        doc = _load_store()
        nodes = doc.setdefault("nodes", {})
        if isinstance(nodes, dict):
            nodes[nid] = row
        doc["updated_at"] = now
        _save_store(doc)
    return {"ok": True, "node_id": nid, "record": row}


def get_node_record(node_id: str) -> Optional[Dict[str, Any]]:
    nid = (node_id or "").strip()
    if not nid:
        return None
    doc = _load_store()
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), dict) else {}
    row = nodes.get(nid) if isinstance(nodes, dict) else None
    return dict(row) if isinstance(row, dict) else None


def all_node_records() -> Dict[str, Dict[str, Any]]:
    doc = _load_store()
    nodes = doc.get("nodes") if isinstance(doc.get("nodes"), dict) else {}
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in nodes.items():
        if isinstance(v, dict):
            out[str(k)] = dict(v)
    return out


__all__ = ["record_node_run", "get_node_record", "all_node_records", "_runtime_path"]
