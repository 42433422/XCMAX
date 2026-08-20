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
    """Mark a tool usage entry as refunded/compensated and restore local wallet units."""
    wanted_key = str(usage_key or "").strip()
    wanted_id = str(usage_id or "").strip()
    key = str(refund_key or wanted_key or wanted_id or f"refund_{uuid.uuid4().hex}").strip()
    now = _facade()._utc_iso()
    with _facade()._ledger_lock:
        state = _facade()._load_usage_state()
        entries: list[dict[str, Any]] = state.setdefault("entries", [])
        target: dict[str, Any] | None = None
        for entry in entries:
            if wanted_key and str(entry.get("usage_key") or "") == wanted_key:
                target = entry
                break
            if wanted_id and str(entry.get("usage_id") or "") == wanted_id:
                target = entry
                break
        if target is None:
            return {
                "success": False,
                "refund_status": "usage_not_found",
                "usage_key": wanted_key,
                "usage_id": wanted_id,
            }
        existing_refund = target.get("refund") if isinstance(target.get("refund"), dict) else {}
        if existing_refund:
            return dict(target)
        cost_units = _facade()._coerce_int(target.get("cost_units"))
        wallet_debit = (
            target.get("wallet_debit") if isinstance(target.get("wallet_debit"), dict) else {}
        )
        billing_source = str(target.get("billing_source") or "")
        uid = _facade()._wallet_user_id(str(target.get("user_id") or ""))
        refund = {
            "refund_key": key,
            "reason": str(reason or ""),
            "cost_units": max(cost_units, 0),
            "created_at": now,
        }
        not_charged = cost_units <= 0 or str(target.get("billing_status") or "") in {
            "insufficient_balance",
            "market_debit_failed",
        }
        if not_charged:
            refund.update({"status": "not_charged", "user_id": uid})
        if not isinstance(wallet_debit, dict):
            wallet_debit = {}
        if not_charged:
            pass
        elif (
            str(wallet_debit.get("status") or "") == "debited"
            and billing_source == "local_model_wallet"
        ):
            wallets: dict[str, Any] = state.setdefault("wallets", {})
            wallet = _facade()._wallet_snapshot(wallets, uid) or {
                "user_id": uid,
                "balance_units": 0,
            }
            balance_before = _facade()._coerce_int(wallet.get("balance_units"))
            balance_after = balance_before + cost_units
            wallet_row = dict(wallet)
            wallet_row["user_id"] = uid
            wallet_row["balance_units"] = balance_after
            wallet_row["updated_at"] = now
            wallets[uid] = wallet_row
            refund.update(
                {
                    "status": "refunded",
                    "user_id": uid,
                    "balance_before_units": balance_before,
                    "balance_after_units": balance_after,
                }
            )
        elif str(wallet_debit.get("status") or "") == "audit_only":
            refund.update({"status": "audit_only", "user_id": uid})
        elif billing_source == "market_wallet":
            amount_yuan = wallet_debit.get(
                "amount_yuan"
            ) or _facade()._market_amount_for_cost_units(cost_units)
            (refund_status, market_refund) = _facade()._apply_market_wallet_refund(
                user_id=uid,
                hold_no=str(wallet_debit.get("hold_no") or ""),
                amount_yuan=amount_yuan,
                refund_key=key,
                reason=reason,
            )
            refund.update(market_refund)
            refund["status"] = refund_status
        else:
            refund.update({"status": "not_required", "user_id": uid})
        target["refund"] = refund
        target["refund_status"] = refund.get("status")
        target["refunded_at"] = now
        state["summary"] = _facade()._usage_summary(entries)
        _facade()._atomic_write(_facade().model_usage_ledger_path(), state)
        return dict(target)
