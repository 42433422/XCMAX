"""合同生命周期状态机 + 电子签对接。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

CONTRACT_STATUSES = (
    "draft",
    "sent",
    "signing",
    "effective",
    "expired",
    "terminated",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_contract_block(doc: dict[str, Any]) -> dict[str, Any]:
    block = doc.get("contract_lifecycle")
    if not isinstance(block, dict):
        block = {"status": "draft", "history": []}
    block.setdefault("status", "draft")
    block.setdefault("history", [])
    return block


def transition_contract(
    doc: dict[str, Any],
    new_status: str,
    *,
    source: str = "api",
    note: str = "",
    esign_ref: str = "",
) -> dict[str, Any]:
    status = (new_status or "").strip()
    if status not in CONTRACT_STATUSES:
        raise ValueError(f"无效合同状态: {status}")
    doc = dict(doc)
    block = get_contract_block(doc)
    old = str(block.get("status") or "draft")
    if old == status:
        return doc
    now = _now_iso()
    block["status"] = status
    block["updated_at"] = now
    if esign_ref:
        block["esign_ref"] = esign_ref
    history = list(block.get("history") or [])
    history.append(
        {
            "from": old,
            "to": status,
            "at": now,
            "source": source,
            "note": (note or "")[:500],
        }
    )
    block["history"] = history[-40:]
    doc["contract_lifecycle"] = block
    if status == "effective":
        doc["contract_signed_at"] = now
    return doc


def apply_contract_to_crm_meta(doc: dict[str, Any]) -> dict[str, Any]:
    """将 contract_lifecycle 写入 CRM opportunity meta（若已入库）。"""
    opp_id = int(doc.get("crm_opportunity_id") or 0)
    if opp_id <= 0:
        return doc
    try:
        from app.services.user_cs_crm_store import _connect, ensure_crm_schema

        block = get_contract_block(doc)
        ensure_crm_schema()
        with _connect() as conn:
            row = conn.execute(
                "SELECT meta_json FROM cs_crm_opportunities WHERE id = ?", (opp_id,)
            ).fetchone()
            meta = {}
            if row and row["meta_json"]:
                try:
                    meta = json.loads(row["meta_json"])
                except json.JSONDecodeError:
                    meta = {}
            meta["contract_status"] = block.get("status")
            meta["contract_lifecycle"] = block
            conn.execute(
                "UPDATE cs_crm_opportunities SET meta_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), _now_iso(), opp_id),
            )
            conn.commit()
    except Exception:
        logger.exception("apply_contract_to_crm_meta failed opp=%s", opp_id)
    return doc


def start_esign_flow(
    doc: dict[str, Any], *, party_a: str, party_b: str, amount_cents: int | None
) -> dict[str, Any]:
    from app.services.esign_adapter import get_esign_adapter

    adapter = get_esign_adapter()
    block = get_contract_block(doc)
    payload = {
        "party_a": party_a,
        "party_b": party_b,
        "amount_cents": amount_cents,
        "market_user_id": doc.get("market_user_id"),
        "crm_opportunity_id": doc.get("crm_opportunity_id"),
    }
    result = adapter.create_sign_task(payload)
    doc = transition_contract(
        doc,
        "signing",
        source="esign",
        note="电子签任务已创建",
        esign_ref=str(result.get("task_id") or ""),
    )
    block = get_contract_block(doc)
    block["esign_provider"] = result.get("provider")
    block["esign_task"] = result
    doc["contract_lifecycle"] = block
    return doc


def handle_esign_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.esign_adapter import get_esign_adapter
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    adapter = get_esign_adapter()
    parsed = adapter.parse_webhook(payload)
    uid = int(parsed.get("market_user_id") or 0)
    if uid <= 0:
        return {"ok": False, "error": "missing market_user_id"}
    doc = load_pipeline(uid)
    if parsed.get("signed"):
        doc = transition_contract(doc, "effective", source="esign_webhook", note="客户已签署")
        stage = str(doc.get("stage") or "idle")
        if stage == "contract_pending":
            from app.services.user_cs_pipeline import set_pipeline_stage

            doc = set_pipeline_stage(uid, "signed", source="esign_webhook", note="contract_signed")
        else:
            doc = apply_contract_to_crm_meta(doc)
            doc = save_pipeline(doc)
    return {"ok": True, "pipeline": doc}


def _parse_contract_end_date(doc: dict[str, Any]) -> datetime | None:
    fields = doc.get("contract_fields") if isinstance(doc.get("contract_fields"), dict) else {}
    block = get_contract_block(doc)
    raw = (
        fields.get("end_date")
        or fields.get("contract_end_date")
        or block.get("end_date")
        or block.get("contract_end_date")
        or ""
    )
    raw = str(raw).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def scan_contract_expiry(*, days_ahead: int = 30) -> dict[str, Any]:
    """扫描 pipeline 中即将到期合同。"""
    from app.services.user_cs_pipeline import iter_pipeline_market_user_ids, load_pipeline

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=max(1, int(days_ahead)))
    due: list[dict[str, Any]] = []
    for uid in iter_pipeline_market_user_ids():
        doc = load_pipeline(uid)
        end = _parse_contract_end_date(doc)
        if not end:
            continue
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if now <= end <= horizon:
            due.append(
                {
                    "market_user_id": uid,
                    "username": doc.get("username"),
                    "end_date": end.date().isoformat(),
                    "stage": doc.get("stage"),
                    "crm_opportunity_id": doc.get("crm_opportunity_id"),
                }
            )
    return {
        "scanned_at": _now_iso(),
        "days_ahead": int(days_ahead),
        "count": len(due),
        "items": due,
    }


def notify_contract_expiry_items(
    items: list[dict[str, Any]], *, dry_run: bool = True
) -> dict[str, Any]:
    """对即将到期合同写入 pipeline 提醒标记；可选 dry_run。"""
    from app.services.user_cs_pipeline import load_pipeline, save_pipeline

    sent = 0
    for row in items:
        uid = int(row.get("market_user_id") or 0)
        if uid <= 0:
            continue
        doc = load_pipeline(uid, username=str(row.get("username") or ""))
        doc = dict(doc)
        doc["contract_expiry_notice_at"] = _now_iso()
        doc["contract_expiry_end_date"] = row.get("end_date")
        if not dry_run:
            save_pipeline(doc, strict_crm=False)
        sent += 1
    return {"notified": sent, "dry_run": dry_run}
