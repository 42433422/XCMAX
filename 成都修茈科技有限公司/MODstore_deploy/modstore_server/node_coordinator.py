"""Cluster coordination for Mac/CVM/K8s MODstore workers.

The coordinator uses Redis when available so multiple nodes can share
heartbeats and incident claim locks. Without Redis it falls back to local files,
which still keeps single-node development behavior stable.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from modstore_server.operational_errors import RECOVERABLE_ERRORS

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows 无 flock
    fcntl = None

NODES_KEY = "xcmax:cluster:nodes"
CLAIM_PREFIX = "xcmax:cluster:incident_claim:"
DEFAULT_STALE_SECONDS = 300
# 同节点不同 PID / 僵死派发：超过该秒数可抢夺未完成 claim（默认 3 分钟）
DEFAULT_CLAIM_STEAL_AFTER = 180
# claim 租约：默认与 Para 默认等待 1800s 对齐，活任务只能通过续约保持所有权
DEFAULT_CLAIM_LEASE_SECONDS = 1800
# 派发期间自动续约间隔（秒）
DEFAULT_CLAIM_RENEW_SECONDS = 300

# 进程实例标识：区分同一 PID 被复用前后的不同进程，避免误认旧 claim 为本人
_PROCESS_INSTANCE = uuid.uuid4().hex

# fencing 单调计数（进程内）+ 事件锁 + 本进程持有表
_FENCING_LOCK = threading.Lock()
_LAST_FENCING = 0
_EVENT_LOCKS = [threading.Lock() for _ in range(256)]
_HELD_LOCK = threading.Lock()
_HELD: Dict[int, Dict[str, Any]] = {}

# Redis 侧比较后写入 / 删除 / 续约，保证跨节点只有一个有效 owner
_CAS_SET_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
if not cur or cur == ARGV[1] then
  redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
  return 1
end
return 0
"""

_CAS_DELETE_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 1 end
local ok, obj = pcall(cjson.decode, cur)
if not ok or type(obj) ~= 'table' then return 0 end
if ARGV[1] ~= '' then
  if obj['token'] == ARGV[1] then
    redis.call('DEL', KEYS[1])
    return 1
  end
  return 0
end
if obj['token'] == nil and obj['node_id'] == ARGV[2] and tostring(obj['pid']) == ARGV[3] then
  redis.call('DEL', KEYS[1])
  return 1
end
return 0
"""

_RENEW_SCRIPT = """
local cur = redis.call('GET', KEYS[1])
if not cur then return 0 end
local ok, obj = pcall(cjson.decode, cur)
if not ok or type(obj) ~= 'table' then return -1 end
if obj['token'] ~= ARGV[1] then return 0 end
local fencing = tonumber(obj['fencing'] or 1) + 1
obj['fencing'] = fencing
obj['claimed_at'] = tonumber(ARGV[2])
obj['expires_at'] = tonumber(ARGV[3])
obj['lease_expires_at'] = tonumber(ARGV[3])
redis.call('SET', KEYS[1], cjson.encode(obj), 'EX', ARGV[4])
return fencing
"""


def _now() -> float:
    return time.time()


def _event_lock(event_id: int) -> threading.Lock:
    return _EVENT_LOCKS[int(event_id) % len(_EVENT_LOCKS)]


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
        except RECOVERABLE_ERRORS:
            return {"node_id": text}
    return {"node_id": text}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _next_fencing(*, after: int = 0) -> int:
    """单调递增 fencing token：墙钟毫秒 + 进程内计数 + 被抢 claim 的旧值兜底。"""
    global _LAST_FENCING
    with _FENCING_LOCK:
        candidate = max(int(_now() * 1000), int(after) + 1, _LAST_FENCING + 1)
        _LAST_FENCING = candidate
        return candidate


def _claim_lease_seconds(ttl_seconds: Optional[int] = None) -> int:
    """claim 租约长度；默认 1800s 与 Para 默认等待一致，避免 181s 过早抢占。"""
    if ttl_seconds is not None:
        return max(60, int(ttl_seconds))
    raw = (os.environ.get("MODSTORE_INCIDENT_CLAIM_LEASE_SECONDS") or "").strip()
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return DEFAULT_CLAIM_LEASE_SECONDS


def _lease_expires_at(owner: Dict[str, Any]) -> float:
    for key in ("lease_expires_at", "expires_at"):
        value = _as_float(owner.get(key))
        if value > 0:
            return value
    return 0.0


def _claim_payload(
    *,
    event_id: int,
    ttl_seconds: Optional[int],
    attempt: int,
    fencing_after: int = 0,
) -> Dict[str, Any]:
    now = _now()
    ttl = _claim_lease_seconds(ttl_seconds)
    return {
        "attempt": max(1, int(attempt)),
        "claimed_at": now,
        "event_id": int(event_id),
        "expires_at": now + ttl,
        "fencing": _next_fencing(after=fencing_after),
        "lease_expires_at": now + ttl,
        "node_id": _node_id(),
        "pid": os.getpid(),
        "process_instance": _PROCESS_INSTANCE,
        "schema_version": 3,
        "token": uuid.uuid4().hex,
    }


def _owner_is_self(owner: Dict[str, Any]) -> bool:
    """是否是本进程当前实例持有的 claim。

    旧 claim 没有 ``process_instance``：仅 pid 相同无法区分「本人」与「pid 复用」，
    保守按本人处理（宁可多等一个租约，也不产生第二个写拥有者）。
    """
    if str(owner.get("node_id") or "") != _node_id():
        return False
    if _as_int(owner.get("pid")) != os.getpid():
        return False
    instance = str(owner.get("process_instance") or "")
    return not instance or instance == _PROCESS_INSTANCE


def _can_steal_claim(owner: Dict[str, Any]) -> bool:
    """仅在租约失效（或旧 claim 明显僵死）时允许抢占，活任务绝不按 181s 软超时抢占。"""
    owner_node = str(owner.get("node_id") or "").strip()
    if not owner_node:
        return True
    if _owner_is_self(owner):
        return False
    owner_pid = _as_int(owner.get("pid"))
    now = _now()
    claimed_at = _as_float(owner.get("claimed_at"))
    age = now - claimed_at if claimed_at > 0 else 10**9
    lease = _lease_expires_at(owner)
    same_node = owner_node == _node_id()
    if lease > 0:
        if lease > now:
            return False
        if same_node and owner_pid and _pid_alive(owner_pid):
            # 租约刚过期但进程还活着：再等软超时，避免抖动误抢
            return age >= _claim_steal_after_seconds()
        return True
    if same_node and owner_pid and not _pid_alive(owner_pid):
        return True
    # 无租约旧 claim：活进程须等满租约，避免过早抢占
    return age >= max(_claim_steal_after_seconds(), _claim_lease_seconds())


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
    except RECOVERABLE_ERRORS:
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
            return {
                **payload,
                "backend": "redis",
                "leader": elect_leader().get("node_id"),
            }
        except RECOVERABLE_ERRORS:
            pass
    directory = _runtime_dir() / "cluster_nodes"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['node_id']}.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {**payload, "backend": "file", "leader": elect_leader().get("node_id")}


def _read_nodes_from_redis() -> List[Dict[str, Any]]:
    r = _redis_client()
    if r is None:
        return []
    try:
        rows = r.hgetall(NODES_KEY)
    except RECOVERABLE_ERRORS:
        return []
    out: List[Dict[str, Any]] = []
    for raw in rows.values():
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                out.append(data)
        except RECOVERABLE_ERRORS:
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
        except RECOVERABLE_ERRORS:
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
    active.sort(
        key=lambda item: (
            int(item.get("priority") or 50),
            str(item.get("node_id") or ""),
        )
    )
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


def _claims_dir() -> Path:
    return _runtime_dir() / "cluster_claims"


def _claim_path(event_id: int) -> Path:
    return _claims_dir() / f"incident-{int(event_id)}.json"


def _claim_key(event_id: int) -> str:
    return f"{CLAIM_PREFIX}{int(event_id)}"


@contextmanager
def _claim_file_lock(path: Path) -> Iterator[None]:
    """跨进程互斥：flock 侧车文件；同进程并发已由 ``_event_lock`` 兜住。"""
    if fcntl is None:
        yield
        return
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _read_claim_file(path: Path) -> tuple[bool, Dict[str, Any], bool]:
    """返回 ``(是否存在, owner, 是否损坏)``；损坏 claim 无有效归属，可安全重建。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, {}, False
    if not text.strip():
        return True, {}, True
    try:
        data = json.loads(text)
    except RECOVERABLE_ERRORS:
        return True, {}, True
    if not isinstance(data, dict):
        return True, {}, True
    return True, data, False


def _atomic_create_file(path: Path, text: str) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        return True
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def _atomic_replace_file(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.replace(str(tmp), str(path))
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _claim_json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


def _held_record(event_id: int) -> Optional[Dict[str, Any]]:
    """本进程仍存活的持有记录；持有线程已退出则视为泄漏并清理。"""
    with _HELD_LOCK:
        record = _HELD.get(int(event_id))
        if not record:
            return None
        ref = record.get("thread_ref")
        if ref is not None and ref() is None:
            _HELD.pop(int(event_id), None)
            return None
        return dict(record)


def _remember_held(event_id: int, *, claim: Dict[str, Any], backend: str, attempt: int) -> None:
    with _HELD_LOCK:
        _HELD[int(event_id)] = {
            "attempt": int(attempt),
            "backend": backend,
            "claim": dict(claim),
            "owner": _node_id(),
            "thread": threading.get_ident(),
            "thread_ref": weakref.ref(threading.current_thread()),
            "token": str(claim.get("token") or ""),
        }


def _forget_held(event_id: int, token: str = "") -> None:
    with _HELD_LOCK:
        record = _HELD.get(int(event_id))
        if not record:
            return
        if token and str(record.get("token") or "") != token:
            return
        _HELD.pop(int(event_id), None)


def _claim_result(
    *,
    backend: str,
    event_id: int,
    claimed: bool,
    payload: Optional[Dict[str, Any]] = None,
    owner: Optional[Dict[str, Any]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    source = payload or owner or {}
    out: Dict[str, Any] = {
        "attempt": _as_int(source.get("attempt")),
        "backend": backend,
        "claimed": bool(claimed),
        "certain": True,
        "event_id": int(event_id),
        "fencing": _as_int(source.get("fencing")),
        "node_id": _node_id(),
        "owner": owner if owner is not None else payload,
        "pid": _as_int(source.get("pid")),
        "token": str(source.get("token") or ""),
    }
    out.update(extra)
    return out


def _claim_redis(
    client: Any,
    event_id: int,
    *,
    ttl: int,
    attempt: Optional[int],
) -> Dict[str, Any]:
    key = _claim_key(event_id)
    try:
        raw = client.get(key)
    except RECOVERABLE_ERRORS as exc:
        return _claim_result(
            backend="redis",
            event_id=event_id,
            claimed=False,
            error=str(exc)[:200],
            reason="redis_error",
            certain=False,
        )
    owner = _parse_claim_owner(raw)
    if owner and not _can_steal_claim(owner):
        return _claim_result(
            backend="redis",
            event_id=event_id,
            claimed=False,
            owner=owner,
            reason="owned_by_other",
        )
    next_attempt = attempt if attempt is not None else _as_int(owner.get("attempt")) + 1
    payload = _claim_payload(
        event_id=event_id,
        ttl_seconds=ttl,
        attempt=max(1, next_attempt),
        fencing_after=_as_int(owner.get("fencing")),
    )
    expected = raw if isinstance(raw, str) else ("" if raw is None else str(raw))
    try:
        won = int(client.eval(_CAS_SET_SCRIPT, 1, key, expected, _claim_json(payload), ttl) or 0)
    except RECOVERABLE_ERRORS as exc:
        return _claim_result(
            backend="redis",
            event_id=event_id,
            claimed=False,
            owner=owner or None,
            error=str(exc)[:200],
            reason="redis_error",
            certain=False,
        )
    if not won:
        try:
            current = _parse_claim_owner(client.get(key))
        except RECOVERABLE_ERRORS:
            current = {}
        return _claim_result(
            backend="redis",
            event_id=event_id,
            claimed=False,
            owner=current or None,
            reason="cas_conflict",
        )
    _remember_held(event_id, claim=payload, backend="redis", attempt=payload["attempt"])
    return _claim_result(
        backend="redis",
        event_id=event_id,
        claimed=True,
        payload=payload,
        reason="stolen" if owner else "acquired",
        stolen_from=owner or None,
    )


def _claim_file(
    event_id: int,
    *,
    ttl: int,
    attempt: Optional[int],
) -> Dict[str, Any]:
    path = _claim_path(event_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _claim_file_lock(path):
            exists, owner, corrupt = _read_claim_file(path)
            if exists and not corrupt:
                same_process = _owner_is_self(owner)
                if not same_process and not _can_steal_claim(owner):
                    return _claim_result(
                        backend="file",
                        event_id=event_id,
                        claimed=False,
                        owner=owner,
                        reason="owned_by_other",
                    )
                next_attempt = (
                    attempt if attempt is not None else _as_int(owner.get("attempt")) + 1
                )
                payload = _claim_payload(
                    event_id=event_id,
                    ttl_seconds=ttl,
                    attempt=max(1, next_attempt),
                    fencing_after=_as_int(owner.get("fencing")),
                )
                _atomic_replace_file(path, _claim_json(payload))
                _remember_held(event_id, claim=payload, backend="file", attempt=payload["attempt"])
                return _claim_result(
                    backend="file",
                    event_id=event_id,
                    claimed=True,
                    payload=payload,
                    reason="reclaimed_self" if same_process else "stolen",
                    stolen_from=None if same_process else owner,
                )
            payload = _claim_payload(
                event_id=event_id,
                ttl_seconds=ttl,
                attempt=max(1, attempt or 1),
                fencing_after=_as_int(owner.get("fencing")),
            )
            text = _claim_json(payload)
            if exists:
                _atomic_replace_file(path, text)
            elif not _atomic_create_file(path, text):
                _, winner, winner_corrupt = _read_claim_file(path)
                if winner_corrupt or not winner:
                    return _claim_result(
                        backend="file",
                        event_id=event_id,
                        claimed=False,
                        reason="claim_unreadable",
                        certain=False,
                    )
                return _claim_result(
                    backend="file",
                    event_id=event_id,
                    claimed=False,
                    owner=winner,
                    reason="cas_conflict",
                )
            _remember_held(event_id, claim=payload, backend="file", attempt=payload["attempt"])
            return _claim_result(
                backend="file",
                event_id=event_id,
                claimed=True,
                payload=payload,
                reason="acquired",
            )
    except OSError as exc:
        return _claim_result(
            backend="file",
            event_id=event_id,
            claimed=False,
            error=str(exc)[:200],
            reason="file_unavailable",
            certain=False,
        )


def claim_incident_for_node(
    event_id: int,
    *,
    ttl_seconds: Optional[int] = None,
    attempt: Optional[int] = None,
) -> Dict[str, Any]:
    """原子领取事件派发权，按 ``attempt``/``token`` 唯一标识 owner。

    返回字段约定：
    - ``claimed``：是否由本进程本次调用获得所有权；
    - ``certain``：``False`` 表示存储层故障/状态不可判定，调用方必须停止派单；
    - ``token``/``fencing``/``attempt``：本次领取的身份，续约与释放必须带上。

    同一 event 在本进程内只允许一个持有者；同 PID 第二个并发 claim 会被拒绝。
    """
    event_id = int(event_id)
    ttl = _claim_lease_seconds(ttl_seconds)
    with _event_lock(event_id):
        held = _held_record(event_id)
        if held:
            return _claim_result(
                backend=str(held.get("backend") or "file"),
                event_id=event_id,
                claimed=False,
                owner=held.get("claim"),
                reason="in_process_owner",
            )
        url = _redis_url()
        client = _redis_client()
        if url and client is None:
            return _claim_result(
                backend="unavailable",
                event_id=event_id,
                claimed=False,
                reason="redis_unavailable",
                certain=False,
            )
        if client is not None:
            return _claim_redis(client, event_id, ttl=ttl, attempt=attempt)
        return _claim_file(event_id, ttl=ttl, attempt=attempt)


def renew_incident_claim(
    event_id: int,
    *,
    ttl_seconds: Optional[int] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """续约本人持有的 claim；返回 ``renewed`` 与递增后的 ``fencing``。

    续约失败（``lost``）说明所有权已被他人接管，调用方必须停止使用该 claim 写入。
    """
    event_id = int(event_id)
    ttl = _claim_lease_seconds(ttl_seconds)
    with _event_lock(event_id):
        held = _held_record(event_id)
        held_token = str((held or {}).get("token") or "")
        token = str(token or held_token)
        if not token:
            return {
                "backend": "unknown",
                "certain": False,
                "event_id": event_id,
                "reason": "no_token",
                "renewed": False,
            }
        url = _redis_url()
        client = _redis_client()
        if url and client is None:
            return {
                "backend": "unavailable",
                "certain": False,
                "event_id": event_id,
                "reason": "redis_unavailable",
                "renewed": False,
            }
        if client is not None:
            now = _now()
            expires = now + ttl
            try:
                out = int(
                    client.eval(_RENEW_SCRIPT, 1, _claim_key(event_id), token, now, expires, ttl) or 0
                )
            except RECOVERABLE_ERRORS as exc:
                return {
                    "backend": "redis",
                    "certain": False,
                    "error": str(exc)[:200],
                    "event_id": event_id,
                    "reason": "redis_error",
                    "renewed": False,
                }
            if out < 0:
                return {
                    "backend": "redis",
                    "certain": False,
                    "event_id": event_id,
                    "reason": "claim_unreadable",
                    "renewed": False,
                }
            if out == 0:
                _forget_held(event_id, token)
                return {
                    "backend": "redis",
                    "certain": True,
                    "event_id": event_id,
                    "reason": "lost",
                    "renewed": False,
                }
            if held:
                claim = dict(held.get("claim") or {})
                claim.update({"claimed_at": now, "expires_at": expires, "fencing": out,
                              "lease_expires_at": expires})
                _remember_held(event_id, claim=claim, backend="redis", attempt=claim.get("attempt", 0))
            return {
                "backend": "redis",
                "certain": True,
                "event_id": event_id,
                "expires_at": expires,
                "fencing": out,
                "renewed": True,
            }
        path = _claim_path(event_id)
        try:
            with _claim_file_lock(path):
                exists, owner, corrupt = _read_claim_file(path)
                if not exists:
                    _forget_held(event_id, token)
                    return {
                        "backend": "file",
                        "certain": True,
                        "event_id": event_id,
                        "reason": "lost",
                        "renewed": False,
                    }
                if corrupt:
                    return {
                        "backend": "file",
                        "certain": False,
                        "event_id": event_id,
                        "reason": "claim_unreadable",
                        "renewed": False,
                    }
                if str(owner.get("token") or "") != token:
                    _forget_held(event_id, token)
                    return {
                        "backend": "file",
                        "certain": True,
                        "event_id": event_id,
                        "owner": owner,
                        "reason": "lost",
                        "renewed": False,
                    }
                now = _now()
                expires = now + ttl
                renewed = {
                    **owner,
                    "claimed_at": now,
                    "expires_at": expires,
                    "fencing": _next_fencing(after=_as_int(owner.get("fencing"))),
                    "lease_expires_at": expires,
                }
                _atomic_replace_file(path, _claim_json(renewed))
                _remember_held(
                    event_id,
                    claim=renewed,
                    backend="file",
                    attempt=_as_int(renewed.get("attempt")),
                )
                return {
                    "backend": "file",
                    "certain": True,
                    "event_id": event_id,
                    "expires_at": expires,
                    "fencing": renewed["fencing"],
                    "renewed": True,
                }
        except OSError as exc:
            return {
                "backend": "file",
                "certain": False,
                "error": str(exc)[:200],
                "event_id": event_id,
                "reason": "file_unavailable",
                "renewed": False,
            }


def release_incident_claim(event_id: int, *, token: Optional[str] = None) -> Dict[str, Any]:
    """按 token 精确释放本人持有；他人的 claim 一律不释放。"""
    event_id = int(event_id)
    with _event_lock(event_id):
        held = _held_record(event_id)
        held_token = str((held or {}).get("token") or "")
        token = str(token or held_token)
        url = _redis_url()
        client = _redis_client()
        if url and client is None:
            return {
                "backend": "unavailable",
                "certain": False,
                "event_id": event_id,
                "released": False,
                "reason": "redis_unavailable",
            }
        if client is not None:
            try:
                out = int(
                    client.eval(
                        _CAS_DELETE_SCRIPT,
                        1,
                        _claim_key(event_id),
                        token,
                        _node_id(),
                        str(os.getpid()),
                    )
                    or 0
                )
            except RECOVERABLE_ERRORS as exc:
                return {
                    "backend": "redis",
                    "certain": False,
                    "error": str(exc)[:200],
                    "event_id": event_id,
                    "released": False,
                }
            _forget_held(event_id, token)
            return {
                "backend": "redis",
                "certain": True,
                "event_id": event_id,
                "released": bool(out),
            }
        path = _claim_path(event_id)
        try:
            with _claim_file_lock(path):
                exists, owner, corrupt = _read_claim_file(path)
                if not exists:
                    _forget_held(event_id, token)
                    return {
                        "backend": "file",
                        "certain": True,
                        "event_id": event_id,
                        "missing": True,
                        "released": True,
                    }
                if corrupt:
                    path.unlink()
                    _forget_held(event_id, token)
                    return {
                        "backend": "file",
                        "certain": True,
                        "event_id": event_id,
                        "released": True,
                        "repaired": True,
                    }
                matches = (
                    str(owner.get("token") or "") == token
                    if token
                    else (
                        str(owner.get("node_id") or "") == _node_id()
                        and _as_int(owner.get("pid")) == os.getpid()
                    )
                )
                if not matches:
                    return {
                        "backend": "file",
                        "certain": True,
                        "event_id": event_id,
                        "owner": owner,
                        "released": False,
                    }
                path.unlink()
                _forget_held(event_id, token)
                return {
                    "backend": "file",
                    "certain": True,
                    "event_id": event_id,
                    "released": True,
                }
        except FileNotFoundError:
            _forget_held(event_id, token)
            return {
                "backend": "file",
                "certain": True,
                "event_id": event_id,
                "missing": True,
                "released": True,
            }
        except OSError as exc:
            return {
                "backend": "file",
                "certain": False,
                "error": str(exc)[:200],
                "event_id": event_id,
                "released": False,
            }


__all__ = [
    "claim_incident_for_node",
    "renew_incident_claim",
    "release_incident_claim",
    "cluster_status",
    "elect_leader",
    "is_leader",
    "write_node_heartbeat",
]
