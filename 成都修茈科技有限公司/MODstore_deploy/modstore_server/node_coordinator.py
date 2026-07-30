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
# 同节点不同 PID / 僵死派发：超过该秒数可抢夺未完成 claim（默认 3 分钟）
DEFAULT_CLAIM_STEAL_AFTER = 180


def _runtime_dir() -> Path:
    return Path(os.environ.get("MODSTORE_RUNTIME_DIR") or Path.home() / ".xcmax" / "modstore-daily")


def _node_id() -> str:
    return (
        os.environ.get("MODSTORE_NODE_ID")
        or os.environ.get("HOSTNAME")
        or socket.gethostname()
        or "local-node"
    ).strip()


def _claim_steal_after_seconds() -> int:
    raw = (os.environ.get("MODSTORE_INCIDENT_CLAIM_STEAL_AFTER") or "").strip()
    if not raw:
        return DEFAULT_CLAIM_STEAL_AFTER
    try:
        return max(30, int(raw))
    except ValueError:
        return DEFAULT_CLAIM_STEAL_AFTER


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 进程存在但无权限发信号，视为仍存活
        return True
    except OSError:
        return False
    return True


def _parse_claim_owner(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {"node_id": text}
        except Exception:
            return {"node_id": text}
    return {"node_id": text}


def _claim_payload(*, event_id: int, ttl_seconds: int) -> Dict[str, Any]:
    now = time.time()
    return {
        "claimed_at": now,
        "event_id": int(event_id),
        "expires_at": now + max(60, int(ttl_seconds or 900)),
        "node_id": _node_id(),
        "pid": os.getpid(),
        "schema_version": 2,
    }


def _can_steal_claim(owner: Dict[str, Any]) -> bool:
    """Allow reclaim when owner process is dead or claim soft-TTL elapsed."""
    owner_node = str(owner.get("node_id") or "").strip()
    if not owner_node:
        return True
    try:
        owner_pid = int(owner.get("pid") or 0)
    except (TypeError, ValueError):
        owner_pid = 0
    try:
        claimed_at = float(owner.get("claimed_at") or 0)
    except (TypeError, ValueError):
        claimed_at = 0.0
    age = time.time() - claimed_at if claimed_at > 0 else 10**9
    steal_after = _claim_steal_after_seconds()
    if owner_node == _node_id():
        if owner_pid and owner_pid == os.getpid():
            return False
        if owner_pid and not _pid_alive(owner_pid):
            return True
        return age >= steal_after
    # 跨节点：仅软超时后抢（避免双活误杀）；无 claimed_at 的旧字符串 claim 也可抢
    return age >= steal_after


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
    """Best-effort cross-node incident claim lock.

    Claim value is JSON ``{node_id, pid, claimed_at}`` so same-host uvicorn
    workers do not all treat one hostname lock as owned by every PID. Stale or
    dead-owner claims can be stolen after soft TTL.
    """

    key = f"{CLAIM_PREFIX}{int(event_id)}"
    node_id = _node_id()
    ttl = max(60, int(ttl_seconds or 900))
    payload = _claim_payload(event_id=event_id, ttl_seconds=ttl)
    payload_json = json.dumps(payload, ensure_ascii=False)
    r = _redis_client()
    if r is not None:
        try:
            ok = bool(r.set(key, payload_json, nx=True, ex=ttl))
            if ok:
                return {
                    "backend": "redis",
                    "claimed": True,
                    "event_id": int(event_id),
                    "node_id": node_id,
                    "owner": payload,
                    "pid": payload["pid"],
                }
            owner = _parse_claim_owner(r.get(key))
            same_owner = (
                str(owner.get("node_id") or "") == node_id
                and int(owner.get("pid") or 0) == os.getpid()
            )
            if same_owner:
                return {
                    "backend": "redis",
                    "claimed": True,
                    "event_id": int(event_id),
                    "node_id": node_id,
                    "owner": owner,
                    "pid": os.getpid(),
                }
            if _can_steal_claim(owner):
                # 无 CAS：best-effort overwrite；双抢时靠后续 dispatched_count 去重
                r.set(key, payload_json, ex=ttl)
                return {
                    "backend": "redis",
                    "claimed": True,
                    "event_id": int(event_id),
                    "node_id": node_id,
                    "owner": payload,
                    "pid": payload["pid"],
                    "stolen_from": owner,
                }
            return {
                "backend": "redis",
                "claimed": False,
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
            owner = _parse_claim_owner(claim_path.read_text(encoding="utf-8"))
        except Exception:
            owner = {}
        same_owner = (
            str(owner.get("node_id") or "") == node_id and int(owner.get("pid") or 0) == os.getpid()
        )
        if same_owner:
            return {
                "backend": "file",
                "claimed": True,
                "event_id": int(event_id),
                "node_id": node_id,
                "owner": owner,
                "pid": os.getpid(),
            }
        if not _can_steal_claim(owner):
            return {
                "backend": "file",
                "claimed": False,
                "event_id": int(event_id),
                "node_id": node_id,
                "owner": owner,
            }
    claim_path.write_text(payload_json + "\n", encoding="utf-8")
    return {
        "backend": "file",
        "claimed": True,
        "event_id": int(event_id),
        "node_id": node_id,
        "owner": payload,
        "pid": payload["pid"],
    }


def release_incident_claim(event_id: int) -> Dict[str, Any]:
    """Release claim when held by this process (best-effort)."""

    key = f"{CLAIM_PREFIX}{int(event_id)}"
    node_id = _node_id()
    pid = os.getpid()
    r = _redis_client()
    if r is not None:
        try:
            owner = _parse_claim_owner(r.get(key))
            if (
                str(owner.get("node_id") or "") == node_id
                and int(owner.get("pid") or 0) in {0, pid}
            ) or not owner:
                r.delete(key)
                return {"backend": "redis", "released": True, "event_id": int(event_id)}
            return {
                "backend": "redis",
                "released": False,
                "event_id": int(event_id),
                "owner": owner,
            }
        except Exception as exc:
            return {
                "backend": "redis",
                "released": False,
                "event_id": int(event_id),
                "error": str(exc)[:200],
            }
    claim_path = _runtime_dir() / "cluster_claims" / f"incident-{int(event_id)}.json"
    if claim_path.exists():
        try:
            owner = _parse_claim_owner(claim_path.read_text(encoding="utf-8"))
        except Exception:
            owner = {}
        if (
            str(owner.get("node_id") or "") == node_id and int(owner.get("pid") or 0) in {0, pid}
        ) or not owner:
            try:
                claim_path.unlink()
            except OSError:
                pass
            return {"backend": "file", "released": True, "event_id": int(event_id)}
        return {
            "backend": "file",
            "released": False,
            "event_id": int(event_id),
            "owner": owner,
        }
    return {"backend": "file", "released": True, "event_id": int(event_id), "missing": True}


__all__ = [
    "claim_incident_for_node",
    "release_incident_claim",
    "cluster_status",
    "elect_leader",
    "is_leader",
    "write_node_heartbeat",
]
