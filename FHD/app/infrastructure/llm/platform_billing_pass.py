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

from app.domain.shared_services.conversation.billing_metadata import (
    attach_billing_meta,
    billing_meta_from_headers,
    billing_meta_from_response,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


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
