from __future__ import annotations

import json
import math
import os
import threading
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

DEFAULT_LLM_TOKENS_PER_COST_UNIT = 1000
_ledger_lock = threading.Lock()


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def llm_tokens_per_cost_unit() -> int:
    configured = _coerce_int(os.environ.get("FHD_LLM_TOKENS_PER_COST_UNIT"))
    return configured if configured > 0 else DEFAULT_LLM_TOKENS_PER_COST_UNIT


def estimate_llm_cost_units(
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> int:
    total = _coerce_int(total_tokens)
    if total <= 0:
        total = _coerce_int(prompt_tokens) + _coerce_int(completion_tokens)
    if total <= 0:
        return 0
    return max(1, int(math.ceil(total / llm_tokens_per_cost_unit())))


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def model_usage_ledger_path() -> Path:
    custom = (os.environ.get("MODEL_USAGE_LEDGER_PATH") or "").strip()
    if custom:
        return Path(custom)
    return _repo_root() / "data" / "model_usage_ledger.json"


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _empty_usage_state() -> dict[str, Any]:
    return {"entries": [], "wallets": {}, "summary": {"entry_count": 0, "cost_units_total": 0}}


def _load_usage_state() -> dict[str, Any]:
    path = model_usage_ledger_path()
    if not path.is_file():
        return _empty_usage_state()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return _empty_usage_state()
    if not isinstance(data, dict):
        return _empty_usage_state()
    entries = data.get("entries")
    if not isinstance(entries, list):
        entries = []
    data["entries"] = [entry for entry in entries if isinstance(entry, dict)]
    wallets = data.get("wallets")
    data["wallets"] = wallets if isinstance(wallets, dict) else {}
    data["summary"] = _usage_summary(data["entries"])
    return data


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    body = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    os.replace(tmp, path)


def _safe_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return dict(value)
    except TypeError:
        return {str(key): str(item) for key, item in value.items()}


def _usage_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    model_entries = [
        entry for entry in entries if str(entry.get("entry_type") or "model_call") == "model_call"
    ]
    tool_entries = [entry for entry in entries if str(entry.get("entry_type") or "") == "tool_call"]
    refunded_entries = [
        entry
        for entry in entries
        if isinstance(entry.get("refund"), dict)
        and str(entry.get("refund", {}).get("status") or "") == "refunded"
    ]
    return {
        "entry_count": len(entries),
        "cost_units_total": sum(_coerce_int(entry.get("cost_units")) for entry in entries),
        "token_total": sum(_coerce_int(entry.get("total_tokens")) for entry in entries),
        "model_entry_count": len(model_entries),
        "model_cost_units_total": sum(
            _coerce_int(entry.get("cost_units")) for entry in model_entries
        ),
        "tool_entry_count": len(tool_entries),
        "tool_cost_units_total": sum(
            _coerce_int(entry.get("cost_units")) for entry in tool_entries
        ),
        "refund_entry_count": len(refunded_entries),
        "refund_cost_units_total": sum(
            _coerce_int(entry.get("refund", {}).get("cost_units")) for entry in refunded_entries
        ),
    }


def _wallet_required() -> bool:
    return (os.environ.get("MODEL_USAGE_WALLET_REQUIRED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def model_usage_wallet_backend() -> str:
    raw = (os.environ.get("MODEL_USAGE_WALLET_BACKEND") or "").strip().lower()
    if raw in {"market", "modstore", "xcagi_market", "xiuci"}:
        return "market"
    if raw in {"audit", "none", "off", "disabled"}:
        return "audit"
    return "local"


def _wallet_user_id(user_id: str) -> str:
    return str(user_id or "anonymous").strip() or "anonymous"


def _wallet_snapshot(wallets: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    wallet = wallets.get(_wallet_user_id(user_id))
    return dict(wallet) if isinstance(wallet, dict) else None


def _apply_wallet_debit(
    state: dict[str, Any],
    *,
    user_id: str,
    cost_units: int,
) -> tuple[str, dict[str, Any]]:
    wallets: dict[str, Any] = state.setdefault("wallets", {})
    uid = _wallet_user_id(user_id)
    wallet = _wallet_snapshot(wallets, uid)
    required = _wallet_required()
    if cost_units <= 0:
        return "unmetered", {"status": "not_required", "user_id": uid, "cost_units": 0}
    if wallet is None and not required:
        return "metered", {
            "status": "audit_only",
            "user_id": uid,
            "cost_units": cost_units,
            "reason": "wallet_not_configured",
        }
    balance_before = _coerce_int((wallet or {}).get("balance_units"))
    if balance_before < cost_units:
        return "insufficient_balance", {
            "status": "insufficient_balance",
            "user_id": uid,
            "cost_units": cost_units,
            "balance_before_units": balance_before,
            "balance_after_units": balance_before,
            "shortfall_units": cost_units - balance_before,
        }
    balance_after = balance_before - cost_units
    wallet_row = dict(wallet or {})
    wallet_row["user_id"] = uid
    wallet_row["balance_units"] = balance_after
    wallet_row["updated_at"] = _utc_iso()
    wallets[uid] = wallet_row
    return "debited", {
        "status": "debited",
        "user_id": uid,
        "cost_units": cost_units,
        "balance_before_units": balance_before,
        "balance_after_units": balance_after,
    }


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _money_str(value: Any) -> str:
    return format(_money(value), "f")


def _market_amount_for_cost_units(cost_units: int) -> Decimal:
    unit = _money(os.environ.get("MODEL_USAGE_MARKET_YUAN_PER_COST_UNIT") or "0.01")
    minimum = _money(os.environ.get("MODEL_USAGE_MARKET_MIN_CHARGE") or "0.01")
    amount = _money(max(_coerce_int(cost_units), 0) * unit)
    if cost_units > 0 and amount < minimum:
        amount = minimum
    return amount


def _market_base_url() -> str:
    return (
        (
            os.environ.get("MODEL_USAGE_MARKET_BASE_URL")
            or os.environ.get("XCAGI_MARKET_BASE_URL")
            or os.environ.get("MODSTORE_PLATFORM_URL")
            or "http://127.0.0.1:8765"
        )
        .strip()
        .rstrip("/")
    )


def _strip_bearer(value: str) -> str:
    token = (value or "").strip()
    if token.lower().startswith("authorization:"):
        token = token.split(":", 1)[1].strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _market_auth_token() -> str:
    token = _strip_bearer(
        os.environ.get("MODEL_USAGE_MARKET_AUTH_TOKEN")
        or os.environ.get("XCAGI_MARKET_AUTH_TOKEN")
        or os.environ.get("MODSTORE_AUTH_TOKEN")
        or ""
    )
    if token:
        return token
    try:
        from app.fastapi_routes.market_account import latest_session_market_token

        return _strip_bearer(latest_session_market_token())
    except (AttributeError, ImportError, OSError, RuntimeError):
        return ""


def _market_timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("MODEL_USAGE_MARKET_TIMEOUT") or "10"))
    except ValueError:
        return 10.0


def _market_post_json(
    path: str,
    *,
    token: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    base = _market_base_url()
    if not base:
        return None, {"status": "market_debit_failed", "message": "market_base_url_missing"}
    if not token:
        return None, {"status": "market_auth_missing", "message": "market_auth_token_missing"}
    url = f"{base}{path}"
    try:
        with httpx.Client(timeout=_market_timeout(), trust_env=False) as client:
            response = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        return None, {
            "status": "market_debit_failed",
            "message": str(exc) or type(exc).__name__,
            "market_base_url": base,
            "path": path,
        }
    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text[:500]}
    if response.status_code == 402:
        return None, {
            "status": "insufficient_balance",
            "message": str(data.get("message") or data.get("detail") or "余额不足"),
            "market_base_url": base,
            "path": path,
        }
    if response.status_code >= 400 or data.get("ok") is False or data.get("success") is False:
        msg = str(data.get("message") or data.get("detail") or data.get("error") or "")
        status = "insufficient_balance" if "余额不足" in msg else "market_debit_failed"
        return None, {
            "status": status,
            "message": msg or f"HTTP {response.status_code}",
            "market_base_url": base,
            "path": path,
        }
    return data, None


def _apply_market_wallet_debit(
    *,
    user_id: str,
    provider: str,
    model: str,
    cost_units: int,
    usage_key: str,
) -> tuple[str, dict[str, Any]]:
    uid = _wallet_user_id(user_id)
    if cost_units <= 0:
        return "unmetered", {"status": "not_required", "user_id": uid, "cost_units": 0}
    amount = _market_amount_for_cost_units(cost_units)
    token = _market_auth_token()
    request_id = (usage_key or f"usage_{uuid.uuid4().hex}")[:128]
    preauth_payload = {
        "amount": _money_str(amount),
        "provider": provider or "",
        "model": model or "",
        "request_id": request_id,
        "idempotency_key": f"{request_id}:preauth",
    }
    preauth, err = _market_post_json(
        "/api/wallet/ai/preauthorize",
        token=token,
        payload=preauth_payload,
    )
    base_payload = {
        "backend": "market",
        "user_id": uid,
        "cost_units": cost_units,
        "amount_yuan": _money_str(amount),
        "market_base_url": _market_base_url(),
    }
    if err:
        return str(err.get("status") or "market_debit_failed"), {**base_payload, **err}
    hold = preauth.get("hold") if isinstance(preauth, dict) else {}
    hold_no = str((hold or {}).get("hold_no") or "")
    if not hold_no:
        return "market_debit_failed", {
            **base_payload,
            "status": "market_debit_failed",
            "message": "market_preauthorize_missing_hold_no",
            "preauthorize": preauth,
        }
    settle_payload = {
        "hold_no": hold_no,
        "actual_amount": _money_str(amount),
        "idempotency_key": f"{request_id}:settle",
    }
    settled, settle_err = _market_post_json(
        "/api/wallet/ai/settle",
        token=token,
        payload=settle_payload,
    )
    if settle_err:
        return str(settle_err.get("status") or "market_debit_failed"), {
            **base_payload,
            **settle_err,
            "hold_no": hold_no,
            "preauthorized": True,
            "preauthorize": preauth,
        }
    balance = settled.get("balance") if isinstance(settled, dict) else None
    return "debited", {
        **base_payload,
        "status": "debited",
        "hold_no": hold_no,
        "balance_after_yuan": None if balance is None else _money_str(balance),
        "preauthorize": preauth,
        "settle": settled,
    }


def _apply_market_wallet_refund(
    *,
    user_id: str,
    hold_no: str,
    amount_yuan: Any,
    refund_key: str,
    reason: str,
) -> tuple[str, dict[str, Any]]:
    uid = _wallet_user_id(user_id)
    amount = _money(amount_yuan)
    if not hold_no:
        return "refund_pending", {
            "status": "refund_pending",
            "user_id": uid,
            "message": "market_wallet_hold_no_missing",
        }
    if amount <= 0:
        return "not_required", {"status": "not_required", "user_id": uid, "amount_yuan": "0.00"}
    payload = {
        "hold_no": hold_no,
        "refund_amount": _money_str(amount),
        "reason": str(reason or "")[:128],
        "idempotency_key": str(refund_key or f"{hold_no}:refund")[:128],
    }
    data, err = _market_post_json(
        "/api/wallet/ai/refund",
        token=_market_auth_token(),
        payload=payload,
    )
    base_payload = {
        "backend": "market",
        "user_id": uid,
        "hold_no": hold_no,
        "amount_yuan": _money_str(amount),
        "market_base_url": _market_base_url(),
    }
    if err:
        return "refund_pending", {**base_payload, **err, "status": "refund_pending"}
    refund = data.get("refund") if isinstance(data, dict) else {}
    return "refunded", {
        **base_payload,
        "status": "refunded",
        "balance_after_yuan": data.get("balance") if isinstance(data, dict) else None,
        "refund": refund if isinstance(refund, dict) else {},
    }


def set_model_wallet_balance(
    user_id: str,
    balance_units: int,
    *,
    reason: str = "manual_set",
) -> dict[str, Any]:
    uid = _wallet_user_id(user_id)
    with _ledger_lock:
        state = _load_usage_state()
        wallets: dict[str, Any] = state.setdefault("wallets", {})
        wallet = {
            "user_id": uid,
            "balance_units": max(_coerce_int(balance_units), 0),
            "reason": str(reason or ""),
            "updated_at": _utc_iso(),
        }
        wallets[uid] = wallet
        state["summary"] = _usage_summary(list(state.get("entries") or []))
        _atomic_write(model_usage_ledger_path(), state)
    return dict(wallet)


def get_model_wallet(user_id: str) -> dict[str, Any]:
    uid = _wallet_user_id(user_id)
    with _ledger_lock:
        state = _load_usage_state()
        wallet = _wallet_snapshot(state.get("wallets") or {}, uid)
    if wallet is None:
        return {"user_id": uid, "balance_units": 0, "configured": False}
    wallet["configured"] = True
    return wallet


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
    total = _coerce_int(total_tokens)
    prompt = _coerce_int(prompt_tokens)
    completion = _coerce_int(completion_tokens)
    if total <= 0:
        total = prompt + completion
    cost = _coerce_int(cost_units) or estimate_llm_cost_units(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
    )
    key = str(usage_key or "").strip()
    usage_id = f"usage_{uuid.uuid4().hex}"
    now = _utc_iso()
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
        "metadata": _safe_metadata(metadata or {}),
        "wallet_backend": model_usage_wallet_backend(),
        "created_at": now,
    }
    return _record_usage_entry(entry)


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
    cost = max(_coerce_int(cost_units), 0)
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
        "metadata": _safe_metadata(metadata or {}),
        "wallet_backend": model_usage_wallet_backend(),
        "created_at": _utc_iso(),
    }
    return _record_usage_entry(entry)


def refund_tool_usage(
    *,
    usage_key: str = "",
    usage_id: str = "",
    refund_key: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Mark a tool usage entry as refunded/compensated and restore local wallet units."""
    wanted_key = str(usage_key or "").strip()
    wanted_id = str(usage_id or "").strip()
    key = str(refund_key or wanted_key or wanted_id or f"refund_{uuid.uuid4().hex}").strip()
    now = _utc_iso()
    with _ledger_lock:
        state = _load_usage_state()
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

        cost_units = _coerce_int(target.get("cost_units"))
        wallet_debit = (
            target.get("wallet_debit") if isinstance(target.get("wallet_debit"), dict) else {}
        )
        billing_source = str(target.get("billing_source") or "")
        uid = _wallet_user_id(str(target.get("user_id") or ""))
        refund = {
            "refund_key": key,
            "reason": str(reason or ""),
            "cost_units": max(cost_units, 0),
            "created_at": now,
        }
        if cost_units <= 0 or str(target.get("billing_status") or "") in {
            "insufficient_balance",
            "market_debit_failed",
        }:
            refund.update({"status": "not_charged", "user_id": uid})
        elif (
            str(wallet_debit.get("status") or "") == "debited"
            and billing_source == "local_model_wallet"
        ):
            wallets: dict[str, Any] = state.setdefault("wallets", {})
            wallet = _wallet_snapshot(wallets, uid) or {"user_id": uid, "balance_units": 0}
            balance_before = _coerce_int(wallet.get("balance_units"))
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
            amount_yuan = wallet_debit.get("amount_yuan") or _market_amount_for_cost_units(
                cost_units
            )
            refund_status, market_refund = _apply_market_wallet_refund(
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
        state["summary"] = _usage_summary(entries)
        _atomic_write(model_usage_ledger_path(), state)
        return dict(target)


def _record_usage_entry(entry: dict[str, Any]) -> dict[str, Any]:
    with _ledger_lock:
        state = _load_usage_state()
        entries: list[dict[str, Any]] = state.setdefault("entries", [])
        for existing in entries:
            if str(existing.get("usage_key") or "") == entry["usage_key"]:
                return dict(existing)
        backend = model_usage_wallet_backend()
        if backend == "audit":
            wallet_status, wallet_debit = (
                "metered" if entry["cost_units"] else "unmetered",
                {
                    "status": "audit_only",
                    "user_id": _wallet_user_id(entry["user_id"]),
                    "cost_units": entry["cost_units"],
                    "reason": "wallet_backend_audit",
                },
            )
        elif backend == "market":
            wallet_status, wallet_debit = _apply_market_wallet_debit(
                user_id=entry["user_id"],
                provider=entry["provider"],
                model=entry["model"],
                cost_units=entry["cost_units"],
                usage_key=entry["usage_key"],
            )
        else:
            wallet_status, wallet_debit = _apply_wallet_debit(
                state,
                user_id=entry["user_id"],
                cost_units=entry["cost_units"],
            )
        entry["wallet_debit"] = wallet_debit
        if wallet_status in {"debited", "insufficient_balance"}:
            entry["billing_status"] = wallet_status
            entry["billing_source"] = (
                "market_wallet" if backend == "market" else "local_model_wallet"
            )
        elif wallet_status in {"market_debit_failed", "market_auth_missing"}:
            entry["billing_status"] = "market_debit_failed"
            entry["billing_source"] = "market_wallet"
        entries.append(entry)
        state["summary"] = _usage_summary(entries)
        _atomic_write(model_usage_ledger_path(), state)
    return dict(entry)


def list_model_usage_entries(
    *,
    limit: int = 50,
    run_id: str = "",
    user_id: str = "",
) -> list[dict[str, Any]]:
    with _ledger_lock:
        entries = list(_load_usage_state().get("entries") or [])
    wanted_run_id = str(run_id or "").strip()
    wanted_user_id = str(user_id or "").strip()
    if wanted_run_id:
        entries = [entry for entry in entries if str(entry.get("run_id") or "") == wanted_run_id]
    if wanted_user_id:
        entries = [entry for entry in entries if str(entry.get("user_id") or "") == wanted_user_id]
    entries.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
    return [dict(entry) for entry in entries[: max(0, int(limit or 0))]]
