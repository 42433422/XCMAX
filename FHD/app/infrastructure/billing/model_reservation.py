"""Reserve model cost before I/O, settle once against the existing usage ledger.

The usage key, wallet, transaction and market idempotency are shared with the
existing billing implementation. A lost provider receipt retains its reservation
for reconciliation; it is never silently converted into a free call.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.infrastructure.billing import model_usage as ledger


class ModelReservationError(RuntimeError):
    def __init__(self, message: str, *, reconciliation_required: bool = True) -> None:
        super().__init__(message)
        self.reconciliation_required = reconciliation_required


def reserve_model_usage(
    *, usage_key: str, run_id: str, user_id: str, provider_id: str, model: str, token_ceiling: int
) -> dict[str, Any]:
    reserved = ledger.estimate_llm_cost_units(total_tokens=token_ceiling)
    entry = ledger.record_model_usage(
        usage_key=usage_key,
        run_id=run_id,
        user_id=user_id,
        provider_id=provider_id,
        provider=provider_id,
        model=model,
        cost_units=reserved,
        source="codex.model_gateway",
        metadata={"reservation_units": reserved, "usage_status": "reserved"},
    )
    if entry.get("billing_status") not in {"debited", "metered", "unmetered"}:
        raise ModelReservationError(
            "Model cost reservation was not confirmed",
            reconciliation_required=entry.get("billing_status") != "insufficient_balance",
        )
    return entry


def settle_model_usage(usage_key: str, usage: dict[str, int]) -> dict[str, Any]:
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if any(type(usage.get(key)) is not int or usage[key] < 0 for key in keys):
        raise ModelReservationError("Verified model usage is required for settlement")
    values = {key: usage[key] for key in keys}
    if values["total_tokens"] < values["prompt_tokens"] + values["completion_tokens"]:
        raise ModelReservationError("Model usage totals do not match")
    actual_cost = ledger.estimate_llm_cost_units(**values)
    with ledger._usage_key_lock(usage_key):
        with ledger._usage_db(write=True) as db:
            entry, state = ledger._read_entry(db, usage_key)
            if not entry or state != "complete":
                raise ModelReservationError("Model reservation requires reconciliation")
            metadata = dict(entry.get("metadata") or {})
            reservation = metadata.get("reservation_units")
            if type(reservation) is not int or actual_cost > reservation:
                raise ModelReservationError("Actual model cost exceeds its authorized ceiling")
            pending = metadata.get("settlement_usage")
            if pending is not None and pending != values:
                raise ModelReservationError("Model settlement usage cannot change")
            if metadata.get("usage_status") == "settled":
                return dict(entry)
            if entry.get("billing_status") not in {"debited", "metered", "unmetered"}:
                raise ModelReservationError("Model reservation was not charged successfully")
            previous = dict(entry)
            metadata.update(settlement_usage=values, usage_status="settlement_pending")
            entry["metadata"] = metadata
            difference = reservation - actual_cost
            debit = dict(entry.get("wallet_debit") or {})
            market = difference > 0 and entry.get("billing_source") == "market_wallet"
            if not market:
                if difference and entry.get("billing_source") == "local_model_wallet":
                    wallet = ledger._read_wallet(db, entry["user_id"])
                    if wallet is None:
                        raise ModelReservationError("Reserved wallet is unavailable")
                    wallet.update(
                        balance_units=wallet["balance_units"] + difference,
                        updated_at=ledger._utc_iso(),
                    )
                    ledger._save_wallet(db, entry["user_id"], wallet)
                entry.update(values, cost_units=actual_cost)
                metadata.update(usage_status="settled", released_units=difference)
            ledger._save_entry(db, entry, previous=previous, storage_key=usage_key)
        if market:
            # The captured market amount fixes the conversion rate for this hold.
            amount = (
                Decimal(str(debit["amount_yuan"])) * Decimal(difference) / Decimal(reservation)
            ).quantize(Decimal("0.01"))
            status, result = ledger._apply_market_wallet_refund(
                user_id=entry["user_id"],
                hold_no=str(debit.get("hold_no") or ""),
                amount_yuan=amount,
                refund_key=f"{usage_key}:unused",
                reason="Unused model reservation",
                request=entry.get("market_request"),
            )
            if status not in {"refunded", "not_required"}:
                raise ModelReservationError("Model reservation release requires reconciliation")
            with ledger._usage_db(write=True) as db:
                entry, _ = ledger._read_entry(db, usage_key)
                if entry["metadata"].get("usage_status") == "settled":
                    return dict(entry)
                previous = dict(entry)
                entry.update(values, cost_units=actual_cost)
                entry["metadata"] = {
                    **entry["metadata"],
                    "usage_status": "settled",
                    "released_units": difference,
                    "release_receipt": result,
                }
                ledger._save_entry(db, entry, previous=previous, storage_key=usage_key)
        return dict(entry)
