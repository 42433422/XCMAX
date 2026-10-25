"""Cluster coordination for Mac/CVM/K8s MODstore workers.

Node heartbeats use Redis or local files. Incident ownership always uses the
application SQL database; a failed claim never falls back to another authority.
Cluster workers must share that database (PostgreSQL for multi-node deployments).
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from modstore_server.models import IncidentClaim, get_session_factory
from modstore_server.operational_errors import RECOVERABLE_ERRORS

NODES_KEY = "xcmax:cluster:nodes"
DEFAULT_STALE_SECONDS = 300
_CURRENT_CLAIM: ContextVar[dict[str, Any] | None] = ContextVar(
    "incident_claim", default=None
)


class IncidentClaimLost(RuntimeError):
    """No side effect or final projection may proceed without the current owner."""


def _runtime_dir() -> Path:
    return Path(
        os.environ.get("MODSTORE_RUNTIME_DIR")
        or Path.home() / ".xcmax" / "modstore-daily"
    )


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
            r.hset(
                NODES_KEY, payload["node_id"], json.dumps(payload, ensure_ascii=False)
            )
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


def _database_time(session) -> datetime:
    value = session.execute(select(func.current_timestamp())).scalar_one()
    if not isinstance(value, datetime):
        raise RuntimeError("database clock unavailable")
    return value.replace(tzinfo=None)


def claim_incident_for_node(event_id: int, *, ttl_seconds: int = 900) -> Dict[str, Any]:
    """Atomically issue a fresh token; even two calls in one PID are competitors."""
    event_id, ttl = int(event_id), max(30, int(ttl_seconds))
    token = uuid.uuid4().hex
    try:
        with get_session_factory()() as session:
            now = _database_time(session)
            if session.get(IncidentClaim, event_id) is None:
                try:
                    with session.begin_nested():
                        session.add(IncidentClaim(event_id=event_id, lease_until=now))
                        session.flush()
                except IntegrityError:
                    pass  # Another process inserted the row; only the CAS below can own it.
            won = (
                session.query(IncidentClaim)
                .filter(
                    IncidentClaim.event_id == event_id,
                    or_(
                        IncidentClaim.owner_token == "",
                        IncidentClaim.lease_until <= now,
                    ),
                )
                .update(
                    {
                        "owner_token": token,
                        "generation": IncidentClaim.generation + 1,
                        "lease_until": now + timedelta(seconds=ttl),
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            row = session.get(IncidentClaim, event_id, populate_existing=True)
            if row is None:
                raise IncidentClaimLost("claim row unavailable")
            return {
                "backend": "sql",
                "event_id": event_id,
                "claimed": bool(won),
                "owner_token": token if won else "",
                "generation": row.generation,
                "dispatch_state": row.dispatch_state,
                "ttl_seconds": ttl,
            }
    except RECOVERABLE_ERRORS as exc:
        return {
            "backend": "sql",
            "event_id": event_id,
            "claimed": False,
            "error": f"claim unavailable: {type(exc).__name__}",
        }


def current_claim() -> dict[str, Any] | None:
    return _CURRENT_CLAIM.get()


def assert_incident_claim(event_id: int, *, session=None) -> dict[str, Any]:
    """Fence this transaction with the current token and live lease.

    When a caller supplies its write session, the guarded UPDATE locks ownership
    until that same transaction commits; checking in a different transaction is
    insufficient to fence a subsequent projection write.
    """
    claim = current_claim()
    if not claim or claim["event_id"] != int(event_id) or claim.get("lost"):
        raise IncidentClaimLost(f"incident {event_id}: current claim required")

    def check(db):
        now = _database_time(db)
        won = (
            db.query(IncidentClaim)
            .filter(
                IncidentClaim.event_id == int(event_id),
                IncidentClaim.owner_token == claim["owner_token"],
                IncidentClaim.generation == claim["generation"],
                IncidentClaim.lease_until > now,
            )
            .update(
                {"lease_until": IncidentClaim.lease_until}, synchronize_session=False
            )
        )
        if not won:
            claim["lost"] = True
            raise IncidentClaimLost(
                f"incident {event_id}: ownership expired or superseded"
            )

    try:
        if session is not None:
            check(session)
        else:
            with get_session_factory()() as db:
                check(db)
                db.commit()
    except IncidentClaimLost:
        raise
    except RECOVERABLE_ERRORS as exc:
        claim["lost"] = True
        raise IncidentClaimLost(
            f"incident {event_id}: ownership store unavailable"
        ) from exc
    return claim


def renew_incident_claim(
    event_id: int, owner_token: str, *, ttl_seconds: int = 900
) -> bool:
    try:
        with get_session_factory()() as db:
            now = _database_time(db)
            won = (
                db.query(IncidentClaim)
                .filter(
                    IncidentClaim.event_id == int(event_id),
                    IncidentClaim.owner_token == owner_token,
                    IncidentClaim.lease_until > now,
                )
                .update(
                    {"lease_until": now + timedelta(seconds=max(30, int(ttl_seconds)))},
                    synchronize_session=False,
                )
            )
            db.commit()
            return bool(won)
    except RECOVERABLE_ERRORS:
        return False


def release_incident_claim(event_id: int, *, owner_token: str = "") -> Dict[str, Any]:
    claim = current_claim()
    token = owner_token or (
        claim["owner_token"] if claim and claim["event_id"] == int(event_id) else ""
    )
    if not token:
        return {"backend": "sql", "event_id": int(event_id), "released": False}
    try:
        with get_session_factory()() as db:
            won = (
                db.query(IncidentClaim)
                .filter(
                    IncidentClaim.event_id == int(event_id),
                    IncidentClaim.owner_token == token,
                )
                .update({"owner_token": ""}, synchronize_session=False)
            )
            db.commit()
            return {"backend": "sql", "event_id": int(event_id), "released": bool(won)}
    except RECOVERABLE_ERRORS as exc:
        return {
            "backend": "sql",
            "event_id": int(event_id),
            "released": False,
            "error": type(exc).__name__,
        }


@contextmanager
def incident_claim_scope(event_id: int, *, ttl_seconds: int = 900):
    """Renew a token for this dispatch; only explicit nested scopes are reentrant."""
    existing = current_claim()
    if existing and existing["event_id"] == int(event_id):
        yield assert_incident_claim(event_id)
        return
    claim = claim_incident_for_node(event_id, ttl_seconds=ttl_seconds)
    if not claim.get("claimed"):
        raise IncidentClaimLost(
            f"incident {event_id}: already owned or SQL unavailable"
        )
    marker = _CURRENT_CLAIM.set(claim)
    stop = threading.Event()

    def keep_alive():
        while not stop.wait(max(1, claim["ttl_seconds"] / 3)):
            if not renew_incident_claim(
                event_id, claim["owner_token"], ttl_seconds=claim["ttl_seconds"]
            ):
                claim["lost"] = True
                return

    renewal = threading.Thread(
        target=keep_alive, name=f"incident-lease-{event_id}", daemon=True
    )
    renewal.start()
    try:
        yield claim
    finally:
        stop.set()
        renewal.join(timeout=1)
        release_incident_claim(event_id, owner_token=claim["owner_token"])
        _CURRENT_CLAIM.reset(marker)


__all__ = [
    "claim_incident_for_node",
    "release_incident_claim",
    "renew_incident_claim",
    "incident_claim_scope",
    "assert_incident_claim",
    "current_claim",
    "IncidentClaimLost",
    "cluster_status",
    "elect_leader",
    "is_leader",
    "write_node_heartbeat",
]
