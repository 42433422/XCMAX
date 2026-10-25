"""Bounded, secret-safe data sources used by diagnostic terminal commands."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from modstore_server.diagnostic_terminal_core import (
    MAX_LIMIT,
    MAX_LOG_BYTES,
    PROBLEM_STATES,
    item,
    matches,
    safe_text,
)
from modstore_server.models import IncidentEvent, OutboxDeadLetter, User
from modstore_server.standard_delivery_api import build_standard_delivery_rows


def incident_detail(row: IncidentEvent) -> tuple[str, str]:
    try:
        payload = json.loads(str(row.payload_json or "{}"))
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    detail = next(
        (
            payload.get(key)
            for key in ("summary", "error", "message", "reason", "detail", "status")
            if payload.get(key)
        ),
        "",
    )
    severity = str(payload.get("severity") or payload.get("level") or "").casefold()
    event_text = f"{row.event_type} {detail}".casefold()
    if severity in {"critical", "fatal"}:
        normalized = "critical"
    elif severity in {"high", "error"} or any(x in event_text for x in ("failed", "error")):
        normalized = "error"
    elif severity in {"medium", "warning", "warn"} or "incident" in event_text:
        normalized = "warning"
    else:
        normalized = "info"
    return safe_text(detail), normalized


def incident_items(
    db: Session,
    query: str,
    limit: int,
    *,
    problems_only: bool = False,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    query_builder = db.query(IncidentEvent)
    if since is not None:
        query_builder = query_builder.filter(IncidentEvent.created_at >= since)
    rows = query_builder.order_by(IncidentEvent.id.desc()).limit(min(MAX_LIMIT, limit * 5)).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        detail, severity = incident_detail(row)
        if problems_only and severity == "info":
            continue
        if not matches(query, row.event_type, row.source, detail, row.id):
            continue
        items.append(
            item(
                "incident",
                severity,
                str(row.event_type or "system.event"),
                detail,
                source=str(row.source or "incident_events"),
                reference=f"incident:{row.id}",
                timestamp=row.created_at,
            )
        )
        if len(items) >= limit:
            break
    return items


def dlq_items(db: Session, query: str, limit: int) -> list[dict[str, Any]]:
    rows = (
        db.query(OutboxDeadLetter)
        .filter(OutboxDeadLetter.resolved_at.is_(None))
        .order_by(OutboxDeadLetter.id.desc())
        .limit(min(MAX_LIMIT, limit * 3))
        .all()
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        if not matches(query, row.event_name, row.event_id, row.last_error, row.producer):
            continue
        items.append(
            item(
                "dlq",
                "error",
                f"DLQ · {row.event_name}",
                row.last_error or f"投递失败 {row.attempts} 次",
                source=str(row.producer or "event_outbox_dlq"),
                reference=f"dlq:{row.id}",
                timestamp=row.moved_at,
            )
        )
        if len(items) >= limit:
            break
    return items


def scheduler_snapshot(provider: Callable[[], dict[str, Any]] | None) -> dict[str, Any]:
    if provider is not None:
        return provider()
    from modstore_server.api.scheduler_runtime_api import scheduler_runtime

    return scheduler_runtime()


def scheduler_items(snapshot: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    jobs = [row for row in snapshot.get("jobs") or [] if isinstance(row, dict)]
    jobs.sort(
        key=lambda row: (
            str(row.get("state") or "") == "healthy",
            str(row.get("job_id") or ""),
        )
    )
    items: list[dict[str, Any]] = []
    for row in jobs:
        if not matches(
            query,
            row.get("job_id"),
            row.get("state"),
            row.get("last_status"),
            row.get("last_error_code"),
            row.get("last_error"),
        ):
            continue
        state = str(row.get("state") or "unknown").casefold()
        severity = (
            "error" if state in PROBLEM_STATES else ("warning" if state == "deferred" else "info")
        )
        detail = (
            row.get("last_error_code") or row.get("last_error") or row.get("last_status") or state
        )
        items.append(
            item(
                "scheduler",
                severity,
                str(row.get("job_id") or "unknown-job"),
                detail,
                source="scheduler_runtime",
                reference=f"job:{row.get('job_id') or ''}",
                timestamp=row.get("last_finished_at") or row.get("last_started_at") or "",
                data={
                    "state": state,
                    "consecutive_failures": int(row.get("consecutive_failures") or 0),
                    "last_status": str(row.get("last_status") or ""),
                },
            )
        )
        if len(items) >= limit:
            break
    return items


def delivery_items(
    db: Session, query: str, limit: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = build_standard_delivery_rows(db)
    summary = {
        "purchased_accounts": len(rows),
        "pending_install": sum(row["status"] == "pending_install" for row in rows),
        "pending_first_login": sum(row["status"] == "pending_first_login" for row in rows),
        "completed": sum(row["status"] == "completed" for row in rows),
    }
    items: list[dict[str, Any]] = []
    for row in rows:
        account = row.get("account") or {}
        plan = row.get("plan") or {}
        if not matches(
            query,
            row.get("delivery_no"),
            row.get("status"),
            account.get("id"),
            account.get("username"),
            account.get("email"),
            plan.get("id"),
            plan.get("title"),
        ):
            continue
        status = str(row.get("status") or "")
        items.append(
            item(
                "delivery",
                "info" if status == "completed" else "warning",
                f"{account.get('username') or account.get('id')} · {plan.get('title') or plan.get('id')}",
                row.get("status_label"),
                source="active_permanent_user_plan",
                reference=str(row.get("delivery_no") or ""),
                timestamp=row.get("completed_at") or row.get("started_at") or "",
                data={
                    "status": status,
                    "account": account,
                    "plan": plan,
                    "install": row.get("install") or {},
                    "first_login": row.get("first_login") or {},
                },
            )
        )
        if len(items) >= limit:
            break
    return items, summary


def controlled_log_paths() -> list[Path]:
    configured = [
        os.environ.get("OPS_NGINX_ERROR_LOG", "").strip(),
        os.environ.get("MODSTORE_APP_ERROR_LOG", "").strip(),
    ]
    if not configured[0]:
        configured[0] = "/var/log/nginx/error.log"
    return list(dict.fromkeys(Path(raw) for raw in configured if raw))


def file_log_items(query: str, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in controlled_log_paths():
        try:
            with path.open("rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - MAX_LOG_BYTES))
                lines = handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            safe = safe_text(line)
            if not matches(query, safe):
                continue
            lowered = safe.casefold()
            severity = (
                "error"
                if any(x in lowered for x in ("error", "fatal", "critical"))
                else ("warning" if "warn" in lowered else "info")
            )
            items.append(
                item(
                    "log",
                    severity,
                    path.name,
                    safe,
                    source=f"controlled_log:{path.name}",
                )
            )
            if len(items) >= limit:
                return items
    return items


def find_accounts(db: Session, query: str, limit: int) -> list[dict[str, Any]]:
    needle = query.casefold()
    rows = (
        db.query(User)
        .filter(
            or_(
                func.lower(User.username).contains(needle),
                func.lower(func.coalesce(User.email, "")).contains(needle),
                func.coalesce(User.phone, "").contains(query),
            )
        )
        .order_by(User.id.asc())
        .limit(limit)
        .all()
    )
    return [
        item(
            "account",
            "info",
            str(row.username or row.id),
            f"{row.email or '无邮箱'} · {row.account_state or 'unknown'}",
            source="users",
            reference=f"user:{row.id}",
            data={
                "id": int(row.id),
                "username": str(row.username or ""),
                "email": str(row.email or ""),
                "account_state": str(row.account_state or ""),
                "is_enterprise": bool(row.is_enterprise),
            },
        )
        for row in rows
    ]


def route_items(
    route_catalog: Sequence[dict[str, Any]], query: str, limit: int
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for route in route_catalog:
        methods = ",".join(sorted(str(method) for method in route.get("methods") or []))
        if not matches(query, route.get("path"), route.get("name"), methods):
            continue
        items.append(
            item(
                "route",
                "info",
                f"{methods or 'ANY'} {route.get('path') or ''}",
                route.get("name") or "",
                source="runtime_route_table",
                reference=str(route.get("path") or ""),
            )
        )
        if len(items) >= limit:
            break
    return items


__all__ = [
    "controlled_log_paths",
    "delivery_items",
    "dlq_items",
    "file_log_items",
    "find_accounts",
    "incident_items",
    "route_items",
    "scheduler_items",
    "scheduler_snapshot",
]
