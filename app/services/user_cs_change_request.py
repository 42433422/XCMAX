"""交付期产品需求变更 / Bug 工单（存于 Pipeline JSON，对接微信群通知）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.user_cs_pipeline import load_pipeline, save_pipeline

CHANGE_TYPES = frozenset({"product_change", "bug", "feature"})
CHANGE_STATUSES = frozenset({"pending", "acknowledged", "in_progress", "resolved", "rejected"})
SUBMIT_STAGES = frozenset({"signed", "delivering", "delivered"})

_TYPE_LABELS = {
    "product_change": "产品需求变更",
    "bug": "Bug 反馈",
    "feature": "功能修改",
}

_STATUS_LABELS = {
    "pending": "待受理",
    "acknowledged": "已确认",
    "in_progress": "处理中",
    "resolved": "已解决",
    "rejected": "已驳回",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ticket_no(market_user_id: int, ticket_id: str) -> str:
    short = ticket_id.replace("-", "")[:8].upper()
    return f"CR-{int(market_user_id)}-{short}"


def list_change_requests(market_user_id: int, *, username: str = "") -> list[dict[str, Any]]:
    doc = load_pipeline(int(market_user_id), username=username)
    rows = doc.get("change_requests")
    if not isinstance(rows, list):
        return []
    out = [r for r in rows if isinstance(r, dict)]
    out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return out


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
    uid = int(market_user_id)
    ctype = (change_type or "").strip()
    if ctype not in CHANGE_TYPES:
        raise ValueError(f"变更类型无效，可选：{', '.join(sorted(CHANGE_TYPES))}")
    title_s = (title or "").strip()
    if not title_s:
        raise ValueError("请填写变更标题")
    doc = load_pipeline(uid, username=username)
    stage = str(doc.get("stage") or "idle")
    if stage not in SUBMIT_STAGES:
        raise ValueError("当前项目阶段暂不支持提交变更工单（需处于已签、交付中或已交付）")
    ticket_id = str(uuid.uuid4())
    now = _now_iso()
    row: dict[str, Any] = {
        "id": ticket_id,
        "ticket_no": _ticket_no(uid, ticket_id),
        "change_type": ctype,
        "change_type_label": _TYPE_LABELS.get(ctype, ctype),
        "title": title_s[:256],
        "description": (description or "").strip()[:8000],
        "priority": (priority or "normal").strip()[:16] or "normal",
        "status": "pending",
        "status_label": _STATUS_LABELS["pending"],
        "pipeline_stage": stage,
        "source": (source or "enterprise_portal")[:64],
        "created_at": now,
        "updated_at": now,
        "wechat_notified_at": None,
        "admin_note": "",
    }
    rows = doc.get("change_requests")
    if not isinstance(rows, list):
        rows = []
    rows = [r for r in rows if isinstance(r, dict)]
    rows.insert(0, row)
    doc["change_requests"] = rows[:100]
    doc = save_pipeline(doc)
    return row


def update_change_request_status(
    market_user_id: int,
    ticket_id: str,
    *,
    status: str,
    admin_note: str = "",
    username: str = "",
) -> dict[str, Any]:
    uid = int(market_user_id)
    st = (status or "").strip()
    if st not in CHANGE_STATUSES:
        raise ValueError("状态无效")
    doc = load_pipeline(uid, username=username)
    rows = doc.get("change_requests")
    if not isinstance(rows, list):
        raise ValueError("未找到工单")
    found = False
    updated: dict[str, Any] | None = None
    for r in rows:
        if not isinstance(r, dict) or str(r.get("id")) != str(ticket_id):
            continue
        r["status"] = st
        r["status_label"] = _STATUS_LABELS.get(st, st)
        r["updated_at"] = _now_iso()
        if admin_note:
            r["admin_note"] = admin_note.strip()[:2000]
        updated = dict(r)
        found = True
        break
    if not found or not updated:
        raise ValueError("未找到该变更工单")
    doc["change_requests"] = rows
    save_pipeline(doc)
    return updated


def build_change_request_wechat_message(row: dict[str, Any], *, client_name: str = "") -> str:
    who = (client_name or "客户").strip()
    lines = [
        f"【产品变更工单】{row.get('ticket_no') or ''}",
        f"客户：{who}",
        f"类型：{row.get('change_type_label') or row.get('change_type')}",
        f"标题：{row.get('title') or ''}",
    ]
    desc = (row.get("description") or "").strip()
    if desc:
        lines.append(f"说明：{desc[:500]}{'…' if len(desc) > 500 else ''}")
    lines.append("")
    lines.append("请项目组评估影响范围与排期，并在内部客服页更新工单状态。")
    return "\n".join(lines)


def _find_change_request_row(doc: dict[str, Any], ticket_id: str) -> dict[str, Any] | None:
    rows = doc.get("change_requests")
    if not isinstance(rows, list):
        return None
    for r in rows:
        if isinstance(r, dict) and str(r.get("id")) == str(ticket_id):
            return r
    return None


def build_ops_dispatch_task_description(
    row: dict[str, Any],
    *,
    market_user_id: int,
    client_name: str = "",
) -> str:
    who = (client_name or f"用户{market_user_id}").strip()
    parts = [
        f"【变更工单 OPS】{row.get('ticket_no') or ''}",
        f"客户：{who} (market_user_id={market_user_id})",
        f"类型：{row.get('change_type_label') or row.get('change_type')}",
        f"标题：{row.get('title') or ''}",
        f"阶段：{row.get('pipeline_stage') or ''}",
    ]
    desc = (row.get("description") or "").strip()
    if desc:
        parts.append(f"说明：{desc[:1500]}{'…' if len(desc) > 1500 else ''}")
    parts.append("请在内部客服页跟进工单状态；完成后更新为已解决。")
    return "\n".join(parts)


def mark_change_request_ops_dispatched(
    market_user_id: int,
    ticket_id: str,
    *,
    job_id: str = "",
    error: str = "",
    username: str = "",
) -> dict[str, Any]:
    doc = load_pipeline(int(market_user_id), username=username)
    rows = doc.get("change_requests")
    if not isinstance(rows, list):
        raise ValueError("未找到工单")
    for r in rows:
        if not isinstance(r, dict) or str(r.get("id")) != str(ticket_id):
            continue
        now = _now_iso()
        if job_id:
            r["ops_dispatch_job_id"] = str(job_id)[:128]
            r["ops_dispatched_at"] = now
            r.pop("ops_dispatch_error", None)
        else:
            r["ops_dispatch_error"] = (error or "dispatch_failed")[:500]
        r["updated_at"] = now
        save_pipeline(doc)
        return dict(r)
    raise ValueError("未找到该变更工单")


def mark_change_request_wechat_notified(
    market_user_id: int,
    ticket_id: str,
    *,
    username: str = "",
) -> dict[str, Any]:
    doc = load_pipeline(int(market_user_id), username=username)
    rows = doc.get("change_requests")
    if not isinstance(rows, list):
        raise ValueError("未找到工单")
    for r in rows:
        if isinstance(r, dict) and str(r.get("id")) == str(ticket_id):
            r["wechat_notified_at"] = _now_iso()
            r["updated_at"] = r["wechat_notified_at"]
            save_pipeline(doc)
            return dict(r)
    raise ValueError("未找到该变更工单")
