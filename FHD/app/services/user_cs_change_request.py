"""内部客服变更工单（JSON 侧存储）。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.user_cs_pipeline import _pipeline_roots

logger = logging.getLogger(__name__)

_CHANGE_TYPES: dict[str, str] = {
    "product_change": "产品变更",
    "bug_fix": "问题修复",
    "feature_request": "功能需求",
    "ops_support": "运维支持",
}

_STATUS_LABELS: dict[str, str] = {
    "pending": "待处理",
    "in_progress": "处理中",
    "resolved": "已解决",
    "closed": "已关闭",
    "rejected": "已驳回",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for pr in _pipeline_roots():
        root = pr.parent / "user_cs_change_requests"
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        root.mkdir(parents=True, exist_ok=True)
        roots.append(root)
    return roots


def _store_file(market_user_id: int) -> Path:
    return _store_roots()[0] / f"{int(market_user_id)}.json"


def _load_rows(market_user_id: int) -> list[dict[str, Any]]:
    path = _store_file(market_user_id)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = raw.get("requests") if isinstance(raw, dict) else raw
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _save_rows(market_user_id: int, rows: list[dict[str, Any]]) -> None:
    path = _store_file(market_user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"requests": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def _decorate(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    ct = str(out.get("change_type") or "")
    out["change_type_label"] = _CHANGE_TYPES.get(ct, ct or "变更")
    st = str(out.get("status") or "pending")
    out["status_label"] = _STATUS_LABELS.get(st, st)
    return out


def list_change_requests(market_user_id: int, *, username: str = "") -> list[dict[str, Any]]:
    _ = username
    return [_decorate(r) for r in _load_rows(int(market_user_id))]


def create_change_request(
    market_user_id: int,
    *,
    change_type: str,
    title: str,
    description: str = "",
    priority: str = "normal",
    username: str = "",
    source: str = "enterprise_portal",
) -> dict[str, Any]:
    ct = str(change_type or "").strip()
    if ct not in _CHANGE_TYPES:
        raise ValueError(f"未知变更类型: {ct}")
    if not str(title or "").strip():
        raise ValueError("标题不能为空")
    uid = int(market_user_id)
    rows = _load_rows(uid)
    ticket_id = uuid.uuid4().hex[:12]
    row = {
        "id": ticket_id,
        "ticket_no": f"CR-{uid}-{len(rows) + 1:04d}",
        "market_user_id": uid,
        "username": str(username or "").strip(),
        "change_type": ct,
        "title": str(title).strip()[:256],
        "description": str(description or "").strip()[:8000],
        "priority": str(priority or "normal"),
        "source": str(source or ""),
        "status": "pending",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    rows.insert(0, row)
    _save_rows(uid, rows)
    return _decorate(row)


def _find_row(rows: list[dict[str, Any]], ticket_id: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("id")) == str(ticket_id):
            return row
    return None


def update_change_request_status(
    market_user_id: int,
    ticket_id: str,
    *,
    status: str,
    admin_note: str = "",
    username: str = "",
) -> dict[str, Any]:
    _ = username
    st = str(status or "").strip()
    if st not in _STATUS_LABELS:
        raise ValueError(f"未知状态: {st}")
    uid = int(market_user_id)
    rows = _load_rows(uid)
    row = _find_row(rows, ticket_id)
    if not row:
        raise ValueError("未找到该变更工单")
    row["status"] = st
    row["updated_at"] = _now_iso()
    if admin_note.strip():
        row["admin_note"] = admin_note.strip()[:2000]
    _save_rows(uid, rows)
    return _decorate(row)


def mark_change_request_ops_dispatched(
    market_user_id: int,
    ticket_id: str,
    *,
    job_id: str = "",
    error: str = "",
    username: str = "",
) -> dict[str, Any]:
    _ = username
    uid = int(market_user_id)
    rows = _load_rows(uid)
    row = _find_row(rows, ticket_id)
    if not row:
        raise ValueError("未找到该变更工单")
    now = _now_iso()
    if error:
        row["ops_dispatch_error"] = error[:500]
    else:
        row["ops_dispatch_job_id"] = str(job_id or "").strip()
        row["ops_dispatched_at"] = now
        row.pop("ops_dispatch_error", None)
    row["updated_at"] = now
    _save_rows(uid, rows)
    return _decorate(row)


def mark_change_request_wechat_notified(
    market_user_id: int,
    ticket_id: str,
    *,
    username: str = "",
) -> dict[str, Any]:
    _ = username
    uid = int(market_user_id)
    rows = _load_rows(uid)
    row = _find_row(rows, ticket_id)
    if not row:
        raise ValueError("未找到该变更工单")
    row["wechat_notified_at"] = _now_iso()
    _save_rows(uid, rows)
    return _decorate(row)


def build_ops_dispatch_task_description(
    row: dict[str, Any],
    *,
    market_user_id: int,
    client_name: str = "",
) -> str:
    title = str(row.get("title") or "变更工单")
    desc = str(row.get("description") or "").strip()
    client = client_name or str(row.get("username") or "")
    lines = [
        f"[客服变更工单] {title}",
        f"客户: {client} (market_user_id={market_user_id})",
        f"类型: {row.get('change_type_label') or row.get('change_type')}",
        f"工单: {row.get('ticket_no') or row.get('id')}",
    ]
    if desc:
        lines.append(f"说明: {desc[:500]}")
    return "\n".join(lines)


def build_change_request_wechat_message(row: dict[str, Any], *, client_name: str = "") -> str:
    client = client_name or str(row.get("username") or "客户")
    status = row.get("status_label") or row.get("status") or ""
    return (
        f"【变更工单更新】{client}\n"
        f"标题：{row.get('title') or ''}\n"
        f"状态：{status}\n"
        f"单号：{row.get('ticket_no') or row.get('id') or ''}"
    )
