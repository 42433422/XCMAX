"""Dynamic allow-list and access-request persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from app.security.license_store import AccessRequest, AllowedClient


def _store() -> Any:
    from app.security import license_store

    return license_store


def is_ip_explicitly_allowed(ip: str) -> bool:
    _store().ensure_schema()
    norm = str(ip or "").strip()
    if not norm:
        return False
    with _store()._connect() as conn:
        row = conn.execute(
            "SELECT COUNT(1) AS n FROM lan_allowed_clients WHERE ip=? AND revoked_at IS NULL",
            (norm,),
        ).fetchone()
    return int(row["n"] or 0) > 0


def touch_allowed_client(ip: str) -> None:
    _store().ensure_schema()
    norm = str(ip or "").strip()
    if not norm:
        return
    with _store()._connect() as conn:
        conn.execute(
            "UPDATE lan_allowed_clients SET last_seen_at=? WHERE ip=? AND revoked_at IS NULL",
            (_store()._now(), norm),
        )


def list_allowed_clients(active_only: bool = True, limit: int = 200) -> list[AllowedClient]:
    _store().ensure_schema()
    sql = "SELECT * FROM lan_allowed_clients"
    params: tuple = ()
    if active_only:
        sql += " WHERE revoked_at IS NULL"
    sql += " ORDER BY approved_at DESC, id DESC LIMIT ?"
    params = params + (int(limit),)
    with _store()._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_store()._row_to_allowed_client(r) for r in rows]


def revoke_allowed_client(client_id: int, *, actor: str = "", ip: str = "") -> bool:
    _store().ensure_schema()
    now = _store()._now()
    with _store()._connect() as conn:
        cur = conn.execute(
            "UPDATE lan_allowed_clients SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (now, int(client_id)),
        )
        ok = bool(cur.rowcount > 0)
    if ok:
        _store().write_audit(
            action="allowlist.revoke",
            target=f"allow:{client_id}",
            actor=actor,
            ip=ip,
        )
    return ok


def get_latest_access_request_by_ip(ip: str) -> AccessRequest | None:
    _store().ensure_schema()
    norm = str(ip or "").strip()
    if not norm:
        return None
    with _store()._connect() as conn:
        row = conn.execute(
            "SELECT * FROM lan_access_requests WHERE ip=? ORDER BY id DESC LIMIT 1",
            (norm,),
        ).fetchone()
    return _store()._row_to_access_request(row) if row else None


def create_access_request(
    *,
    ip: str,
    device_label: str = "",
    note: str = "",
    user_agent: str = "",
) -> AccessRequest:
    _store().ensure_schema()
    norm_ip = str(ip or "").strip()
    if not norm_ip:
        raise ValueError("ip must not be empty")
    label = str(device_label or "").strip()[:200]
    detail = str(note or "").strip()[:500]
    ua = str(user_agent or "").strip()[:512]
    now = _store()._now()
    with _store()._connect() as conn:
        existing = conn.execute(
            "SELECT * FROM lan_access_requests WHERE ip=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (norm_ip,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE lan_access_requests"
                " SET device_label=?, note=?, user_agent=?, requested_at=?"
                " WHERE id=?",
                (label, detail, ua, now, int(existing["id"])),
            )
            row = conn.execute(
                "SELECT * FROM lan_access_requests WHERE id=?",
                (int(existing["id"]),),
            ).fetchone()
            return cast("AccessRequest", _store()._row_to_access_request(row))

        cur = conn.execute(
            "INSERT INTO lan_access_requests"
            " (ip, device_label, note, user_agent, requested_at, status)"
            " VALUES (?, ?, ?, ?, ?, 'pending')",
            (norm_ip, label, detail, ua, now),
        )
        row = conn.execute(
            "SELECT * FROM lan_access_requests WHERE id=?",
            (int(cur.lastrowid or 0),),
        ).fetchone()
    return cast("AccessRequest", _store()._row_to_access_request(row))


def list_access_requests(
    *,
    status: str | None = None,
    limit: int = 200,
) -> list[AccessRequest]:
    _store().ensure_schema()
    sql = "SELECT * FROM lan_access_requests"
    params: tuple = ()
    norm_status = str(status or "").strip().lower()
    if norm_status and norm_status != "all":
        sql += " WHERE status=?"
        params = (norm_status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = params + (int(limit),)
    with _store()._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_store()._row_to_access_request(r) for r in rows]


def approve_access_request(
    request_id: int,
    *,
    actor: str = "",
    review_note: str = "",
) -> AccessRequest | None:
    _store().ensure_schema()
    now = _store()._now()
    note = str(review_note or "").strip()[:500]
    with _store()._connect() as conn:
        row = conn.execute(
            "SELECT * FROM lan_access_requests WHERE id=?",
            (int(request_id),),
        ).fetchone()
        if not row:
            return None

        record = _store()._row_to_access_request(row)
        conn.execute(
            "UPDATE lan_access_requests"
            " SET status='approved', reviewed_at=?, reviewed_by=?, review_note=?"
            " WHERE id=?",
            (now, actor or "", note, int(request_id)),
        )
        existing_allow = conn.execute(
            "SELECT id FROM lan_allowed_clients WHERE ip=? LIMIT 1",
            (record.ip,),
        ).fetchone()
        if existing_allow:
            conn.execute(
                "UPDATE lan_allowed_clients"
                " SET label=?, note=?, approved_at=?, approved_by=?, request_id=?, revoked_at=NULL"
                " WHERE id=?",
                (
                    record.device_label,
                    note or record.note,
                    now,
                    actor or "",
                    int(request_id),
                    int(existing_allow["id"]),
                ),
            )
        else:
            conn.execute(
                "INSERT INTO lan_allowed_clients"
                " (ip, label, note, approved_at, approved_by, request_id)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.ip,
                    record.device_label,
                    note or record.note,
                    now,
                    actor or "",
                    int(request_id),
                ),
            )
        updated = conn.execute(
            "SELECT * FROM lan_access_requests WHERE id=?",
            (int(request_id),),
        ).fetchone()
    _store().write_audit(
        action="allowlist.approve",
        target=f"request:{request_id}",
        actor=actor,
        ip=record.ip,
        detail=note or record.device_label,
    )
    return _store()._row_to_access_request(updated) if updated else None


def reject_access_request(
    request_id: int,
    *,
    actor: str = "",
    review_note: str = "",
) -> AccessRequest | None:
    _store().ensure_schema()
    now = _store()._now()
    note = str(review_note or "").strip()[:500]
    with _store()._connect() as conn:
        row = conn.execute(
            "SELECT * FROM lan_access_requests WHERE id=?",
            (int(request_id),),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE lan_access_requests"
            " SET status='rejected', reviewed_at=?, reviewed_by=?, review_note=?"
            " WHERE id=?",
            (now, actor or "", note, int(request_id)),
        )
        updated = conn.execute(
            "SELECT * FROM lan_access_requests WHERE id=?",
            (int(request_id),),
        ).fetchone()
    record = _store()._row_to_access_request(updated) if updated else None
    if record:
        _store().write_audit(
            action="allowlist.reject",
            target=f"request:{request_id}",
            actor=actor,
            ip=record.ip,
            detail=note or record.device_label,
        )
    return record
