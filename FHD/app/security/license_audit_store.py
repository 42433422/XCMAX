"""Audit-log persistence for the LAN license store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.security.license_store import AuditEntry


def _store() -> Any:
    from app.security import license_store

    return license_store


def write_audit(
    *,
    action: str,
    target: str = "",
    actor: str = "",
    ip: str = "",
    detail: str = "",
) -> None:
    _store().ensure_schema()
    with _store()._connect() as conn:
        conn.execute(
            "INSERT INTO lan_audit_log (ts, actor, action, target, ip, detail)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (_store()._now(), actor or "", action, target or "", ip or "", detail or ""),
        )


def list_audit(limit: int = 200) -> list[AuditEntry]:
    _store().ensure_schema()
    with _store()._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lan_audit_log ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [_store()._row_to_audit(r) for r in rows]
