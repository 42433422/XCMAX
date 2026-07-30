"""平台模型 / 计费完整传递：从网关响应提取并写入本地用量账本。

修茈 ``/v1/chat/completions`` 会在：
- 响应头 ``X-Xiuci-*``
- 响应体 ``xcagi`` / ``_modstore_meta``

返回 provider、resolved model、是否计费、CNY 费用。桌面端与 ETL 助抽
原先只吃 OpenAI 标准字段，导致「平台有多类模型，软件却像只能用 llm、计费丢了」。
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_HEADER_MAP = {
    "x-xiuci-request-id": "request_id",
    "x-xiuci-provider": "provider",
    "x-xiuci-resolved-model": "model",
    "x-xiuci-billed": "billed",
    "x-xiuci-charge-cny": "charge_amount_cny",
}


def billing_meta_from_headers(headers: Mapping[str, str] | None) -> dict[str, Any]:
    """从 HTTP 响应头提取修茈计费元数据。"""
    if not headers:
        return {}
    out: dict[str, Any] = {}
    # httpx Headers 大小写不敏感；dict 可能小写
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    for hk, field in _HEADER_MAP.items():
        if hk not in lowered:
            continue
        raw = lowered.get(hk)
        if raw is None:
            continue
        text = str(raw).strip()
        if field == "billed":
            out[field] = text in {"1", "true", "yes", "on"}
        elif field == "charge_amount_cny":
            try:
                out[field] = float(text)
            except ValueError:
                out[field] = text
        else:
            out[field] = text
    return out


def billing_meta_from_response(result: Mapping[str, Any] | None) -> dict[str, Any]:
    """合并响应体 xcagi / _modstore_meta 与已嵌入的 _xcagi_billing。"""
    if not isinstance(result, Mapping):
        return {}
    merged: dict[str, Any] = {}
    for key in ("_xcagi_billing", "xcagi", "_modstore_meta"):
        block = result.get(key)
        if isinstance(block, Mapping):
            for k, v in block.items():
                if v is None or v == "":
                    continue
                merged[str(k)] = v
    # 统一字段名
    if "charge_amount" in merged and "charge_amount_cny" not in merged:
        merged["charge_amount_cny"] = merged.get("charge_amount")
    if "resolved_model" in merged and "model" not in merged:
        # keep both
        pass
    model = str(merged.get("model") or "").strip()
    provider = str(merged.get("provider") or "").strip()
    resolved = str(merged.get("resolved_model") or "").strip()
    if not resolved and provider and model and "/" not in model:
        resolved = f"{provider}/{model}"
    if resolved:
        merged["resolved_model"] = resolved
    if "billed" in merged:
        billed = merged["billed"]
        if isinstance(billed, str):
            merged["billed"] = billed.strip().lower() in {"1", "true", "yes", "on"}
        else:
            merged["billed"] = bool(billed)
    return merged


def attach_billing_meta(
    result: dict[str, Any],
    *,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """就地写入 ``_xcagi_billing``，返回同一 dict。"""
    meta = billing_meta_from_headers(headers)
    body_meta = billing_meta_from_response(result)
    merged = {**body_meta, **meta}
    if not merged:
        return result
    # 保证 model 字段为完整 provider/model（若可推断）
    resolved = str(merged.get("resolved_model") or "").strip()
    if resolved:
        result["model"] = resolved
    result["_xcagi_billing"] = merged
    return result


def record_platform_billing(
    result: Mapping[str, Any] | None,
    *,
    source: str = "llm_invoke",
    user_id: str = "",
    run_id: str = "",
) -> dict[str, Any] | None:
    """把平台计费写入本地 model_usage_ledger；无元数据则跳过。"""
    meta = billing_meta_from_response(result if isinstance(result, Mapping) else None)
    if not meta:
        return None
    usage = {}
    if isinstance(result, Mapping) and isinstance(result.get("usage"), dict):
        usage = result["usage"]
    try:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or 0)
    except (TypeError, ValueError):
        prompt = completion = total = 0
    if total <= 0:
        total = prompt + completion

    provider = str(meta.get("provider") or "").strip()
    model = str(meta.get("resolved_model") or meta.get("model") or "").strip()
    billed = bool(meta.get("billed"))
    charge = meta.get("charge_amount_cny")
    try:
        charge_f = float(charge) if charge is not None else 0.0
    except (TypeError, ValueError):
        charge_f = 0.0

    try:
        from app.infrastructure.billing.model_usage import (
            estimate_llm_cost_units,
            record_model_usage,
        )

        cost_units = estimate_llm_cost_units(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
        )
        return record_model_usage(
            run_id=run_id,
            user_id=user_id,
            provider_id="xcauto" if provider else "platform",
            provider=provider or "platform",
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cost_units=cost_units,
            billing_status="metered" if billed or cost_units else "unmetered",
            billing_source="platform_xcagi" if billed else "estimated_token_units",
            source=source,
            usage_key=str(meta.get("request_id") or ""),
            metadata={
                "charge_amount_cny": charge_f,
                "key_source": meta.get("key_source"),
                "hold_no": meta.get("hold_no"),
                "category": meta.get("category") or "llm",
                "billed": billed,
            },
        )
    except RECOVERABLE_ERRORS as exc:
        logger.info("record_platform_billing skipped: %s", exc)
        return None


__all__ = [
    "attach_billing_meta",
    "billing_meta_from_headers",
    "billing_meta_from_response",
    "record_platform_billing",
]
