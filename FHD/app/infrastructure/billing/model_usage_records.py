"""Public model/tool usage record and refund workflows."""

from __future__ import annotations

import uuid
from typing import Any, cast

from app.infrastructure.billing import model_usage as _model_usage


def _facade() -> Any:
    return _model_usage


def record_model_usage(
    *,
    run_id: str = "",
    user_id: str = "",
    provider_id: str = "",
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cost_units: int = 0,
    billing_status: str = "",
    billing_source: str = "",
    source: str = "",
    usage_key: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one model usage record for audit and future wallet debit reconciliation."""
    total = _facade()._coerce_int(total_tokens)
    prompt = _facade()._coerce_int(prompt_tokens)
    completion = _facade()._coerce_int(completion_tokens)
    if total <= 0:
        total = prompt + completion
    cost = _facade()._coerce_int(cost_units) or _facade().estimate_llm_cost_units(
        prompt_tokens=prompt, completion_tokens=completion, total_tokens=total
    )
    key = str(usage_key or "").strip()
    usage_id = f"usage_{uuid.uuid4().hex}"
    now = _facade()._utc_iso()
    default_billing_status = "metered" if cost else "unmetered"
    entry = {
        "usage_id": usage_id,
        "usage_key": key or usage_id,
        "entry_type": "model_call",
        "run_id": str(run_id or ""),
        "user_id": str(user_id or ""),
        "provider_id": str(provider_id or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_units": max(cost, 0),
        "billing_status": str(billing_status or default_billing_status),
        "billing_source": str(billing_source or "model_usage_ledger"),
        "source": str(source or ""),
        "metadata": _facade()._safe_metadata(metadata or {}),
        "wallet_backend": _facade().model_usage_wallet_backend(),
        "created_at": now,
    }
    return cast(dict[str, Any], _facade()._record_usage_entry(entry))


def record_tool_usage(
    *,
    run_id: str = "",
    user_id: str = "",
    tool_id: str = "",
    action: str = "",
    call_id: str = "",
    permission: str = "",
    status: str = "",
    cost_units: int = 0,
    billing_status: str = "",
    billing_source: str = "",
    source: str = "",
    usage_key: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one tool/employee usage record and apply the configured AI wallet backend."""
    tool = str(tool_id or "").strip()
    normalized_action = str(action or "").strip()
    usage_id = f"usage_{uuid.uuid4().hex}"
    key = str(usage_key or "").strip()
    cost = max(_facade()._coerce_int(cost_units), 0)
    model_name = f"{tool}.{normalized_action}".strip(".")
    default_billing_status = "metered" if cost else "unmetered"
    entry = {
        "usage_id": usage_id,
        "usage_key": key or usage_id,
        "entry_type": "tool_call",
        "run_id": str(run_id or ""),
        "user_id": str(user_id or ""),
        "provider_id": "tool",
        "provider": "tool",
        "model": model_name,
        "tool_id": tool,
        "action": normalized_action,
        "call_id": str(call_id or ""),
        "permission": str(permission or ""),
        "tool_status": str(status or ""),
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_units": cost,
        "billing_status": str(billing_status or default_billing_status),
        "billing_source": str(billing_source or "tool_usage_ledger"),
        "source": str(source or ""),
        "metadata": _facade()._safe_metadata(metadata or {}),
        "wallet_backend": _facade().model_usage_wallet_backend(),
        "created_at": _facade()._utc_iso(),
    }
    return cast(dict[str, Any], _facade()._record_usage_entry(entry))


def refund_tool_usage(
    *, usage_key: str = "", usage_id: str = "", refund_key: str = "", reason: str = ""
) -> dict[str, Any]:
    """Refund once, atomically with a local wallet or via stable market keys."""
    mu = _facade()
    wanted_key, wanted_id = str(usage_key or "").strip(), str(usage_id or "").strip()
    with mu._usage_db() as db:
        row = db.execute(
            "SELECT usage_key FROM entries WHERE usage_key = ? OR usage_id = ? LIMIT 1",
            (wanted_key, wanted_id or None),
        ).fetchone()
    if row is None:
        return {
            "success": False,
            "refund_status": "usage_not_found",
            "usage_key": wanted_key,
            "usage_id": wanted_id,
        }
    key = row[0]
    with mu._usage_key_lock(key):
        with mu._usage_db(write=True) as db:
            target, state = mu._read_entry(db, key)
            if state != "complete":
                return {**target, "refund_status": "debit_pending"}
            existing = target.get("refund") or {}
            if existing and existing.get("status") != "refund_pending":
                return dict(target)
            previous = dict(target)
            uid = mu._wallet_user_id(target.get("user_id") or "")
            cost = mu._coerce_int(target.get("cost_units"))
            debit = target.get("wallet_debit") or {}
            refund = dict(existing) or {
                "refund_key": str(
                    refund_key or wanted_key or wanted_id or f"refund_{uuid.uuid4().hex}"
                ),
                "reason": str(reason or ""),
                "cost_units": max(cost, 0),
                "created_at": mu._utc_iso(),
                "user_id": uid,
            }
            market = False
            if cost <= 0 or target.get("billing_status") in {
                "insufficient_balance",
                "market_debit_failed",
            }:
                refund["status"] = "not_charged"
            elif (
                debit.get("status") == "debited"
                and target.get("billing_source") == "local_model_wallet"
            ):
                wallet = mu._read_wallet(db, uid) or {"user_id": uid, "balance_units": 0}
                before = mu._coerce_int(wallet.get("balance_units"))
                wallet.update(balance_units=before + cost, updated_at=mu._utc_iso())
                mu._save_wallet(db, uid, wallet)
                refund.update(
                    status="refunded",
                    balance_before_units=before,
                    balance_after_units=before + cost,
                )
            elif debit.get("status") == "audit_only":
                refund["status"] = "audit_only"
            elif target.get("billing_source") == "market_wallet":
                market = True
                refund["status"] = "refund_pending"
            else:
                refund["status"] = "not_required"
            target.update(
                refund=refund, refund_status=refund["status"], refunded_at=refund["created_at"]
            )
            mu._save_entry(db, target, previous=previous, storage_key=key)
        if market:
            status, result = mu._apply_market_wallet_refund(
                user_id=uid,
                hold_no=str(debit.get("hold_no") or ""),
                amount_yuan=debit.get("amount_yuan") or mu._market_amount_for_cost_units(cost),
                refund_key=refund["refund_key"],
                reason=refund["reason"],
                request=target.get("market_request")
                or {"market_base_url": debit.get("market_base_url") or mu._market_base_url()},
            )
            with mu._usage_db(write=True) as db:
                target, _ = mu._read_entry(db, key)
                if target["refund"]["status"] != "refund_pending":
                    return dict(target)
                previous = dict(target)
                refund = {**target["refund"], **result, "status": status}
                target.update(refund=refund, refund_status=status)
                mu._save_entry(db, target, previous=previous, storage_key=key)
        return dict(target)
