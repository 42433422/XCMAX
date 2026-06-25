"""Cluster coordination for Mac/CVM/K8s MODstore workers.

The coordinator uses Redis when available so multiple nodes can share
heartbeats and incident claim locks. Without Redis it falls back to local files,
which still keeps single-node development behavior stable.
"""

from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

NODES_KEY = "xcmax:cluster:nodes"
CLAIM_PREFIX = "xcmax:cluster:incident_claim:"
DEFAULT_STALE_SECONDS = 300


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _node_id() -> str:
    return (
        os.environ.get("MODSTORE_NODE_ID")
        or os.environ.get("HOSTNAME")
        or socket.gethostname()
        or "local-node"
    ).strip()


def _node_role() -> str:
    return (os.environ.get("MODSTORE_NODE_ROLE") or "mac-dev").strip()


def _node_priority() -> int:
    try:
        return int(os.environ.get("MODSTORE_NODE_PRIORITY", "50"))
    except ValueError:
        return 50


def _redis_url() -> str:
    return (
        os.environ.get("MODSTORE_CLUSTER_REDIS_URL")
        or os.environ.get("MODSTORE_VECTOR_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or ""
    ).strip()


def _redis_client():
    url = _redis_url()
    if not url:
        return None
    try:
        import redis

        return redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=5.0,
            retry_on_timeout=True,
        )
    except Exception:
        return None


def _heartbeat_payload(*, job_count: Optional[int] = None) -> Dict[str, Any]:
    now = time.time()
    return {
        "heartbeat_at": now,
        "heartbeat_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "job_count": job_count,
        "node_id": _node_id(),
        "pid": os.getpid(),
        "priority": _node_priority(),
        "role": _node_role(),
        "schema_version": 1,
    }


def write_node_heartbeat(*, job_count: Optional[int] = None) -> Dict[str, Any]:
    payload = _heartbeat_payload(job_count=job_count)
    r = _redis_client()
    if r is not None:
        try:
            r.hset(NODES_KEY, payload["node_id"], json.dumps(payload, ensure_ascii=False))
            r.expire(NODES_KEY, max(DEFAULT_STALE_SECONDS * 3, 900))
            return {**payload, "backend": "redis", "leader": elect_leader().get("node_id")}
        except Exception:
            pass
    directory = _runtime_dir() / "cluster_nodes"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['node_id']}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {**payload, "backend": "file", "leader": elect_leader().get("node_id")}


def _read_nodes_from_redis() -> List[Dict[str, Any]]:
    r = _redis_client()
    if r is None:
        return []
    try:
        rows = r.hgetall(NODES_KEY)
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for raw in rows.values():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                out.append(data)
        except Exception:
            continue
    return out


def _read_nodes_from_file() -> List[Dict[str, Any]]:
    directory = _runtime_dir() / "cluster_nodes"
    if not directory.exists():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                out.append(data)
        except Exception:
            continue
    return out


def cluster_status(*, stale_seconds: int = DEFAULT_STALE_SECONDS) -> Dict[str, Any]:
    now = time.time()
    nodes = _read_nodes_from_redis() or _read_nodes_from_file()
    active: List[Dict[str, Any]] = []
    stale: List[Dict[str, Any]] = []
    for node in nodes:
        age = max(0.0, now - float(node.get("heartbeat_at") or 0.0))
        row = {**node, "age_seconds": round(age, 3)}
        if age <= max(1, int(stale_seconds or DEFAULT_STALE_SECONDS)):
            active.append(row)
        else:
            stale.append(row)
    active.sort(key=lambda item: (int(item.get("priority") or 50), str(item.get("node_id") or "")))
    leader = active[0] if active else None
    return {
        "active_nodes": active,
        "backend": "redis" if _read_nodes_from_redis() else "file",
        "failover_target_seconds": max(1, int(stale_seconds or DEFAULT_STALE_SECONDS)),
        "leader": leader,
        "node_id": _node_id(),
        "ok": True,
        "stale_nodes": stale,
    }


def elect_leader() -> Dict[str, Any]:
    status = cluster_status()
    leader = status.get("leader")
    return leader if isinstance(leader, dict) else {}


def is_leader() -> bool:
    leader = elect_leader()
    return str(leader.get("node_id") or "") == _node_id()


def claim_incident_for_node(event_id: int, *, ttl_seconds: int = 900) -> Dict[str, Any]:
    """Best-effort cross-node incident claim lock."""

    key = f"{CLAIM_PREFIX}{int(event_id)}"
    node_id = _node_id()
    r = _redis_client()
    if r is not None:
        try:
            ok = bool(r.set(key, node_id, nx=True, ex=max(60, int(ttl_seconds or 900))))
            owner = r.get(key)
            return {
                "backend": "redis",
                "claimed": ok or owner == node_id,
                "event_id": int(event_id),
                "node_id": node_id,
                "owner": owner,
            }
        except Exception:
            pass
    claim_dir = _runtime_dir() / "cluster_claims"
    claim_dir.mkdir(parents=True, exist_ok=True)
    claim_path = claim_dir / f"incident-{int(event_id)}.json"
    if claim_path.exists():
        try:
            owner = json.loads(claim_path.read_text(encoding="utf-8")).get("node_id")
        except Exception:
            owner = ""
        return {
            "backend": "file",
            "claimed": owner == node_id,
            "event_id": int(event_id),
            "node_id": node_id,
            "owner": owner,
        }
    claim_path.write_text(
        json.dumps({"claimed_at": time.time(), "event_id": int(event_id), "node_id": node_id})
        + "\n",
        encoding="utf-8",
    )
    return {
        "backend": "file",
        "claimed": True,
        "event_id": int(event_id),
        "node_id": node_id,
        "owner": node_id,
    }


__all__ = [
    "claim_incident_for_node",
    "cluster_status",
    "elect_leader",
    "is_leader",
    "write_node_heartbeat",
]
