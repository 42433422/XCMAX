"""Read back wallet outcomes using the request journal and authenticated Java wallet."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from modstore_server import llm_client_requests as ledger
from modstore_server.db.llm_chat import LlmCallLog, LlmClientRequest
from modstore_server.llm_billing import UsageMeter, save_success_log
from modstore_server.llm_wallet_client import JavaWalletClient


async def existing_chat_receipt(
    db: Session, user_id: int, key: str | None, original: dict[str, Any], request: Request
) -> dict[str, Any] | None:
    """Read completed or settling requests before resolving mutable model routes."""
    if not key:
        return None
    if not ledger.KEY_PATTERN.fullmatch(key):
        raise HTTPException(422, "模型请求键无效")
    digest = ledger.request_digest(original)
    replay = ledger.completed_receipt(db, user_id, key, digest)
    if replay:
        if replay[0] == "conflict":
            raise HTTPException(409, {"message": "同一请求键内容不同", "state": "conflict"})
        if isinstance(replay[1], dict):
            return replay[1]
        raise HTTPException(409, {"message": "原请求回执待核对", "state": "completed"})
    state = ledger.existing_state(db, user_id, key, digest)
    if state == "conflict":
        raise HTTPException(409, {"message": "同一请求键内容不同", "state": state})
    if state == "completed":
        replay = ledger.completed_receipt(db, user_id, key, digest)
        if not replay or replay[0] != "replay" or not isinstance(replay[1], dict):
            raise HTTPException(409, {"message": "原请求回执待核对", "state": state})
        return replay[1]
    if state == "settling":
        from modstore_server.llm_billing import authorization_header

        receipt = await recover_receipt(
            db, user_id, key, authorization_header(request), operation="chat", request=request
        )
        if receipt is None:
            raise HTTPException(409, {"message": "原请求结算状态待核对", "state": state})
        return receipt
    return None


def complete_receipt(
    db: Session,
    row: LlmClientRequest,
    receipt: dict[str, Any],
    *,
    save_chat=save_success_log,
) -> dict[str, Any]:
    """Publish the usage row and completed receipt in one database transaction."""
    locked = ledger.lock_request(db, row.user_id, row.client_request_id)
    if locked is None:
        raise RuntimeError("billable request missing")
    if locked.state == "completed":
        stored = json.loads(locked.done_json or "{}")
        if isinstance(stored, dict):
            return stored
        raise RuntimeError("invalid stored billing receipt")
    if locked.state != "settling":
        raise RuntimeError("billable request not settling")
    receipt = dict(receipt)
    usage = receipt["usage"]
    if receipt["operation"] == "chat":
        receipt["conversation_id"] = save_chat(
            db,
            user_id=locked.user_id,
            provider=receipt["provider"],
            model=receipt["model"],
            messages=receipt.pop("_history"),
            content=receipt["content"],
            usage=UsageMeter(**usage),
            charge=Decimal(str(receipt["charge_amount"])),
            hold_no=receipt["hold_no"],
            conversation_id=receipt["conversation_id"],
            commit=False,
        )
    else:
        db.add(
            LlmCallLog(
                user_id=locked.user_id,
                provider=receipt["provider"],
                model=receipt["model"],
                hold_no=receipt["hold_no"],
                status="success",
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                estimated=False,
                charge_amount=Decimal(str(receipt["charge_amount"])),
            )
        )
    ledger.finish(db, locked, receipt)
    return receipt


async def recover_receipt(
    db: Session,
    user_id: int,
    client_request_id: str,
    authorization: str,
    *,
    operation: str | None = None,
    request: Request | None = None,
) -> dict[str, Any] | None:
    row = (
        db.query(LlmClientRequest)
        .filter_by(user_id=user_id, client_request_id=client_request_id, state="settling")
        .one_or_none()
    )
    if row is None or not row.done_json:
        return None
    saved = json.loads(row.done_json)
    receipt = saved.get("pending_settlement") if isinstance(saved, dict) else None
    if not isinstance(receipt, dict) or receipt.get("operation") not in {
        "chat",
        "image_generation",
        "responses",
    }:
        return None
    if operation is not None and receipt["operation"] != operation:
        return None
    pat_user_id = getattr(request.state, "llm_pat_user_id", None) if request is not None else None
    is_pat = pat_user_id is not None
    if is_pat and pat_user_id != user_id:
        return None
    # A persisted terminal BYOK receipt has no platform wallet to read back.
    # Recover the original receipt, never repeat the provider request.
    if (
        receipt["operation"] in {"chat", "responses"}
        and receipt.get("key_source") == "user_override"
    ):
        try:
            amount = Decimal(str(receipt.get("charge_amount")))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if receipt.get("billed") is not False or not amount.is_finite() or amount != 0:
            return None
        if is_pat:
            JavaWalletClient(request=request).validate_pat(authorization)
        return complete_receipt(db, row, receipt)
    wallet = JavaWalletClient(request=request) if is_pat else JavaWalletClient()
    if is_pat:
        hold = await wallet.read_hold(
            authorization, receipt["hold_no"], request_id=receipt["request_id"]
        )
    else:
        hold = await wallet.read_hold(authorization, receipt["hold_no"])
    if hold is None or hold.get("status") != "settled":
        return None
    if any(
        hold.get(field) != receipt.get(field)
        for field in ("hold_no", "request_id", "provider", "model")
    ):
        return None
    try:
        settled = Decimal(str(hold.get("settled_amount")))
        if not settled.is_finite() or settled != Decimal(str(receipt["charge_amount"])):
            return None
    except InvalidOperation:
        return None
    return complete_receipt(db, row, receipt)
