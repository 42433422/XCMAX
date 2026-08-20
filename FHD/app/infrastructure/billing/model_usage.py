from __future__ import annotations

import json
import math
import os
import sys
import threading
from datetime import UTC, datetime
from decimal import Decimal as Decimal
from pathlib import Path
from typing import Any

import httpx as httpx

from app.utils.path_io.path_utils import get_app_data_dir

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
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return Path(get_app_data_dir()) / "data" / "model_usage_ledger.json"
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
    except TypeError:  # noqa: BLE001 - normalize untrusted metadata values
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


from app.infrastructure.billing.model_usage_market import (
    _apply_market_wallet_debit as _apply_market_wallet_debit,
)
from app.infrastructure.billing.model_usage_market import (
    _apply_market_wallet_refund as _apply_market_wallet_refund,
)
from app.infrastructure.billing.model_usage_market import (
    _market_amount_for_cost_units as _market_amount_for_cost_units,
)
from app.infrastructure.billing.model_usage_market import _market_auth_token as _market_auth_token
from app.infrastructure.billing.model_usage_market import _market_base_url as _market_base_url
from app.infrastructure.billing.model_usage_market import _market_post_json as _market_post_json
from app.infrastructure.billing.model_usage_market import _market_timeout as _market_timeout
from app.infrastructure.billing.model_usage_market import _money as _money
from app.infrastructure.billing.model_usage_market import _money_str as _money_str
from app.infrastructure.billing.model_usage_market import _strip_bearer as _strip_bearer
from app.infrastructure.billing.model_usage_records import record_model_usage as record_model_usage
from app.infrastructure.billing.model_usage_records import record_tool_usage as record_tool_usage
from app.infrastructure.billing.model_usage_records import refund_tool_usage as refund_tool_usage


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
