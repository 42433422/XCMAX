"""合同生命周期（pipeline meta + 电子签 webhook）。"""

from __future__ import annotations

from typing import Any

from app.utils.operational_errors import OPERATIONAL_ERRORS


def get_contract_block(doc: dict[str, Any] | None) -> dict[str, Any]:
    cl = (doc or {}).get("contract_lifecycle")
    if isinstance(cl, dict):
        return dict(cl)
    return {"status": "draft", "esign_task": {}}


def transition_contract(
    doc: dict[str, Any],
    status: str,
    *,
    source: str = "",
    note: str = "",
) -> dict[str, Any]:
    out = dict(doc or {})
    block = get_contract_block(out)
    block["status"] = str(status or "").strip() or block.get("status", "draft")
    if source:
        block["source"] = source
    if note:
        block["note"] = note
    out["contract_lifecycle"] = block
    return out


def apply_contract_to_crm_meta(doc: dict[str, Any]) -> dict[str, Any]:
    return dict(doc or {})


def start_esign_flow(
    doc: dict[str, Any],
    *,
    party_a: str,
    party_b: str,
    amount_cents: int | None,
) -> dict[str, Any]:
    out = dict(doc or {})
    block = get_contract_block(out)
    block["esign_task"] = {
        "party_a": party_a,
        "party_b": party_b,
        "amount_cents": amount_cents,
        "status": "pending",
    }
    block["status"] = block.get("status") or "esign_pending"
    out["contract_lifecycle"] = block
    return out


def handle_esign_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("signed"):
        return {"success": False, "error": "unsigned"}
    market_user_id = payload.get("market_user_id")
    if market_user_id is None:
        return {"success": False, "error": "missing market_user_id"}
    try:
        from app.services.user_cs_pipeline import load_pipeline, save_pipeline

        uid = int(market_user_id)
        doc = load_pipeline(uid)
        doc = transition_contract(doc, "signed", source="esign_webhook")
        block = get_contract_block(doc)
        task = block.get("esign_task") if isinstance(block.get("esign_task"), dict) else {}
        task = dict(task)
        task["status"] = "signed"
        if payload.get("task_id"):
            task["task_id"] = payload.get("task_id")
        block["esign_task"] = task
        doc["contract_lifecycle"] = block
        doc = apply_contract_to_crm_meta(doc)
        save_pipeline(doc)
    except OPERATIONAL_ERRORS as exc:
        return {"success": False, "error": str(exc)}
    return {"success": True, "data": {"market_user_id": market_user_id}}


def notify_contract_expiry_items(
    items: list[dict[str, Any]] | None,
    *,
    dry_run: bool = False,
    push: bool = False,
) -> dict[str, int]:
    from app.infrastructure.persistence.contract_expiry_notification_repository import (
        get_contract_expiry_notification_repository,
    )
    from app.services.user_cs_intake_notice import _primary_contact_name
    from app.services.user_cs_pipeline import load_pipeline

    notified = pushed = failed = 0
    repo = get_contract_expiry_notification_repository()

    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        uid = int(raw.get("market_user_id") or 0)
        end_date = str(raw.get("end_date") or "").strip()
        username = str(raw.get("username") or "")
        if not uid or not end_date:
            continue
        notified += 1
        if dry_run or not push:
            continue
        if repo.was_recently_notified(market_user_id=uid, end_date=end_date):
            continue
        doc = load_pipeline(uid, username=username)
        contact = _primary_contact_name(doc)
        if not contact:
            repo.insert_notification(
                market_user_id=uid,
                end_date=end_date,
                push_status="failed",
                push_channel="wechat",
                error_message="no contact",
            )
            failed += 1
            continue
        push_status = "failed"
        error_message: str | None = None
        try:
            from app.desktop_automation.service import get_desktop_automation_service

            svc = get_desktop_automation_service()
            result = svc.send_wechat_message(contact, f"合同将于 {end_date} 到期，请及时续签。")
            if result.get("success") and result.get("message_sent"):
                push_status = "success"
                pushed += 1
            else:
                error_message = str(result.get("error") or "push failed")
                failed += 1
        except OPERATIONAL_ERRORS as exc:
            error_message = str(exc)
            failed += 1
        repo.insert_notification(
            market_user_id=uid,
            end_date=end_date,
            push_status=push_status,
            push_channel="wechat",
            error_message=error_message,
        )

    return {"notified": notified, "pushed": pushed, "failed": failed}
