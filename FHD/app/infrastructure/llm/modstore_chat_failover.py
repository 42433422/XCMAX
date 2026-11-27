"""桌面/FHD 经修茈市场聊天时的配额失败换模。

市场后端 ``allow_failover`` 部署前，桌面仍钉死 ``LLM_PROVIDER/LLM_MODEL`` 一枪失败。
本模块提供候选链与失败判定，供 ``ModstorePlatformAdapter`` 在客户端重试。
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional

_NON_FAILOVER_NEEDLES = (
    "java 支付服务不可用",
    "支付服务不可用",
    "wallet_dependency_unavailable",
    "payment service unavailable",
)


def is_market_chat_wallet_dependency_error(error_text: str) -> bool:
    """支付/钱包依赖不可达：换厂商仍会打同一依赖，客户端不应再换模。"""
    low = str(error_text or "").lower()
    return any(n in low for n in _NON_FAILOVER_NEEDLES)


def chat_failover_max_attempts() -> int:
    try:
        n = int(os.environ.get("XCAGI_LLM_CHAT_FAILOVER_MAX", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def is_market_chat_failoverable(status_code: Optional[int], error_text: str) -> bool:
    """Only an explicit unavailable-model/quota refusal permits another route.

    A proxy 5xx or transport exception does not prove inference never started.
    Text such as "timeout" cannot authorize replay or override account refusals.
    """
    return status_code in {404, 429} and not is_market_chat_wallet_dependency_error(error_text)


def _provider_row_usable(row: dict[str, Any], *, fernet_ok: bool) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("has_user_override"):
        # Match the credential resolver: an unreadable BYOK must not silently
        # fall through to another funding source.
        return row["has_user_override"] is True and fernet_ok
    return any(
        row.get(key) is True
        for key in ("has_platform_key", "has_env_key", "configured", "available")
    )


def first_model_from_catalog_block(block: dict[str, Any] | None) -> str:
    if not isinstance(block, dict):
        return ""
    for key in ("runtime_models", "models"):
        mids = block.get(key)
        if isinstance(mids, list) and mids:
            mid = str(mids[0] or "").strip()
            if mid:
                return mid
    detailed = block.get("models_detailed")
    if isinstance(detailed, list):
        for row in detailed:
            if isinstance(row, dict):
                mid = str(row.get("id") or "").strip()
                if mid:
                    return mid
    return ""


def build_chat_failover_candidates(
    *,
    primary_provider: str,
    primary_model: str,
    status_payload: dict[str, Any] | None,
    catalog_payload: dict[str, Any] | None,
    resolved_default: dict[str, Any] | None = None,
    max_attempts: int | None = None,
) -> list[tuple[str, str]]:
    """Select account-visible routes; a public catalog is not an authorization grant."""
    limit = max(
        1, min(max_attempts if max_attempts is not None else chat_failover_max_attempts(), 8)
    )
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(provider: str, model: str) -> None:
        p = (provider or "").strip().lower()
        m = (model or "").strip()
        if not p or not m:
            return
        key = (p, m)
        if key in seen:
            return
        seen.add(key)
        out.append(key)

    add(primary_provider, primary_model)

    catalog = catalog_payload or {}
    providers_catalog = (
        catalog.get("providers") if isinstance(catalog.get("providers"), list) else []
    )
    by_provider: dict[str, dict[str, Any]] = {}
    for block in providers_catalog or []:
        if isinstance(block, dict):
            pid = str(block.get("provider") or "").strip().lower()
            if pid:
                by_provider[pid] = block

    status = status_payload or {}
    fernet_ok = status.get("fernet_configured") is True
    rows = status.get("providers") if isinstance(status.get("providers"), list) else []
    available = {
        str(row.get("provider") or "").strip().lower(): _provider_row_usable(
            row, fernet_ok=fernet_ok
        )
        for row in rows or []
        if isinstance(row, dict)
    }
    if isinstance(resolved_default, dict) and resolved_default.get("ok") is not False:
        provider = str(resolved_default.get("provider") or "").strip().lower()
        if available.get(provider) is not False:
            add(provider, str(resolved_default.get("model") or ""))

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if not _provider_row_usable(row, fernet_ok=fernet_ok):
            continue
        pid = str(row.get("provider") or "").strip().lower()
        if not pid:
            continue
        mid = first_model_from_catalog_block(by_provider.get(pid))
        if mid:
            add(pid, mid)
        if len(out) >= limit:
            break

    # A gateway can expose several deployment aliases under one provider.
    # Only the account's usable credential rows authorize these alternatives.
    if len(out) < limit:
        for pid, block in by_provider.items():
            if available.get(pid) is not True:
                continue
            mids = block.get("runtime_models", block.get("models", []))
            for mid in mids if isinstance(mids, list) else []:
                if isinstance(mid, str):
                    add(pid, mid)
                if len(out) >= limit:
                    return out[:limit]

    return out[:limit]


def iter_unique_routes(routes: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for p, m in routes:
        key = ((p or "").strip().lower(), (m or "").strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


__all__ = [
    "build_chat_failover_candidates",
    "chat_failover_max_attempts",
    "first_model_from_catalog_block",
    "is_market_chat_failoverable",
    "is_market_chat_wallet_dependency_error",
    "iter_unique_routes",
]
