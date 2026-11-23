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


def record_platform_model_usage(
    *,
    usage_key: str,
    run_id: str,
    user_id: str,
    request_id: str,
    route: Any,
    usage: dict[str, int],
    receipt: Any,
) -> dict[str, Any]:
    """Audit an authenticated platform settlement without debiting either wallet."""
    if (
        any(
            type(usage.get(k)) is not int or usage[k] < 0
            for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        or usage["total_tokens"] < usage["prompt_tokens"] + usage["completion_tokens"]
    ):
        raise ModelReservationError("Platform response usage is invalid")
    cost = ledger.estimate_llm_cost_units(**usage)
    if receipt is None and any(usage.values()):
        raise ModelReservationError("Platform settlement receipt is missing")
    if receipt is not None:
        expected = {
            "schema": "xcmax.responses-billing.v1",
            "provider": route.provider_id,
            "model": route.model.removeprefix(route.provider_id + "/"),
            "key_source": route.key_source,
            "config_revision": route.config_revision,
            "client_request_id": request_id,
        }
        if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items()):
            raise ModelReservationError("Platform settlement does not match the authorized request")
        raw = receipt.get("usage")
        if (
            not isinstance(raw, dict)
            or any(
                type(raw.get(k)) is not int or raw[k] != usage[v]
                for k, v in (
                    ("input_tokens", "prompt_tokens"),
                    ("output_tokens", "completion_tokens"),
                )
            )
            or (
                type(raw.get("total_tokens")) is not int
                or raw["total_tokens"] != usage["total_tokens"]
            )
        ):
            raise ModelReservationError("Platform settlement usage does not match the response")
        byok = route.key_source in {"byok", "user", "user_override"}
        if (
            receipt.get("billing_status") != ("byok" if byok else "settled")
            or type(receipt.get("billed")) is not bool
            or (byok and receipt["billed"])
            or not isinstance(receipt.get("request_id"), str)
            or not receipt["request_id"]
            or (receipt["billed"] and not receipt.get("hold_no"))
        ):
            raise ModelReservationError("Platform billing has not completed")
        from decimal import InvalidOperation

        try:
            amount = Decimal(str(receipt.get("charge_amount")))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ModelReservationError("Platform billing amount is invalid") from exc
        if (
            not amount.is_finite()
            or amount < 0
            or (byok and amount != 0)
            or (amount > 0 and not receipt["billed"])
        ):
            raise ModelReservationError("Platform billing amount is invalid")
        receipt = {
            **expected,
            "request_id": receipt["request_id"],
            "hold_no": str(receipt.get("hold_no") or ""),
            "billed": receipt["billed"],
            "charge_amount": str(amount),
            "billing_status": receipt["billing_status"],
            "usage": dict(usage),
        }
    entry = {
        "usage_id": usage_key,
        "usage_key": usage_key,
        "entry_type": "model_call",
        "run_id": run_id,
        "user_id": user_id,
        "provider_id": route.provider_id,
        "provider": route.provider_id,
        "model": route.model,
        **usage,
        "cost_units": cost,
        "billing_status": "metered" if cost else "unmetered",
        "billing_source": "platform_xcagi",
        "source": "codex.model_gateway",
        "metadata": {"platform_receipt": receipt, "usage_status": "settled"},
        "wallet_backend": "audit",
        "created_at": ledger._utc_iso(),
    }
    recorded = ledger._record_usage_entry(entry)
    if any(
        recorded.get(k) != entry[k]
        for k in (
            "run_id",
            "user_id",
            "provider_id",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "cost_units",
            "metadata",
            "wallet_backend",
        )
    ):
        raise ModelReservationError("Existing platform settlement cannot be rebound")
    return recorded
