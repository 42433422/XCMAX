"""Pure normalization of platform model identity and billing metadata; no ledger IO."""

from __future__ import annotations

from typing import Any, Mapping

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
