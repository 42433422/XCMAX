"""桌面/FHD 经修茈市场聊天时的配额失败换模。

市场后端 ``allow_failover`` 部署前，桌面仍钉死 ``LLM_PROVIDER/LLM_MODEL`` 一枪失败。
本模块提供候选链与失败判定，供 ``ModstorePlatformAdapter`` 在客户端重试。
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterable, Optional

_FAILOVER_NEEDLES = (
    "insufficient_quota",
    "insufficient quota",
    "quota exhausted",
    "quota_exhausted",
    "rate limit",
    "ratelimit",
    "too many requests",
    "配额",
    "额度",
    "余额不足",
    "payment required",
)


def chat_failover_max_attempts() -> int:
    try:
        n = int(os.environ.get("XCAGI_LLM_CHAT_FAILOVER_MAX", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def is_market_chat_failoverable(status_code: Optional[int], error_text: str) -> bool:
    """市场返回是否值得换厂商/模型再试。"""
    if status_code in {402, 403, 429}:
        return True
    text = str(error_text or "")
    # 「平台错误(429): ...」
    m = re.search(r"平台错误\((\d{3})\)", text)
    if m and int(m.group(1)) in {402, 403, 429}:
        return True
    low = text.lower()
    return any(n in text or n in low for n in _FAILOVER_NEEDLES)


def _provider_row_usable(row: dict[str, Any], *, fernet_ok: bool) -> bool:
    if not isinstance(row, dict):
        return False
    if row.get("has_platform_key") or row.get("has_env_key"):
        return True
    if row.get("has_user_override") and fernet_ok:
        return True
    # 兼容旧 status 字段
    if row.get("configured") or row.get("available"):
        return True
    return False


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
    """组装桌面聊天换模候选：主模型 → resolve-default → status 中有 Key 的厂商首模。"""
    limit = max_attempts if max_attempts is not None else chat_failover_max_attempts()
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

    if isinstance(resolved_default, dict) and resolved_default.get("ok") is not False:
        add(str(resolved_default.get("provider") or ""), str(resolved_default.get("model") or ""))

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
    fernet_ok = bool(status.get("fernet_configured"))
    rows = status.get("providers") if isinstance(status.get("providers"), list) else []
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

    # catalog 里有模型但 status 行缺失时的兜底
    if len(out) < limit:
        for pid, block in by_provider.items():
            mid = first_model_from_catalog_block(block)
            if mid:
                add(pid, mid)
            if len(out) >= limit:
                break

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
    "iter_unique_routes",
]
