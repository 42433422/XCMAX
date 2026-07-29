"""用户聊天配额/瞬时失败时的模型自动切换。

Auto / 桌面默认路由此前只在发请求前选一次模型；上游配额耗尽后不会换车。
本模块为 ``POST /api/llm/chat``（及 stream）提供候选链：主模型失败且可切换时，
改试下一家具有可用 Key 的厂商模型。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy.orm import Session

from modstore_server.llm_failure_classifier import (
    is_quota_or_billing_failure,
    is_transient_failure,
)
from modstore_server.llm_key_resolver import KNOWN_PROVIDERS, resolve_api_key

logger = logging.getLogger(__name__)


def chat_failover_max_attempts() -> int:
    try:
        n = int(os.environ.get("MODSTORE_LLM_CHAT_FAILOVER_MAX", "3"))
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def is_wallet_balance_failure(error_text: str, status_code: Optional[int] = None) -> bool:
    """本侧钱包预授权/扣费失败（换平台 Key 无效，只有 BYOK 可能得救）。"""
    if status_code == 402:
        return True
    text = str(error_text or "")
    return "余额不足" in text


def is_chat_failoverable_failure(error_text: str, status_code: Optional[int] = None) -> bool:
    """上游配额/额度或瞬时限流——换厂商/模型可能恢复。"""
    if is_wallet_balance_failure(error_text, status_code):
        return True
    if is_quota_or_billing_failure(error_text, status_code):
        return True
    if is_transient_failure(error_text, status_code):
        return True
    return False


async def list_chat_failover_candidates(
    db: Session,
    user_id: int,
    primary_provider: str,
    primary_model: str,
) -> list[tuple[str, str]]:
    """主模型 + 其它有 Key 厂商的首个可用模型（去重，最多 failover_max）。"""
    from modstore_server.llm_catalog import get_models_for_provider

    primary_p = (primary_provider or "").strip().lower()
    primary_m = (primary_model or "").strip()
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(provider: str, model: str) -> None:
        p = (provider or "").strip().lower()
        m = (model or "").strip()
        if not p or not m or p not in KNOWN_PROVIDERS:
            return
        key = (p, m)
        if key in seen:
            return
        api_key, _ = resolve_api_key(db, user_id, p)
        if not api_key:
            return
        seen.add(key)
        out.append(key)

    _add(primary_p, primary_m)

    async def first_model_id(provider: str) -> str:
        try:
            block = await get_models_for_provider(db, user_id, provider, force_refresh=False)
        except Exception:
            return ""
        mids = list(block.get("runtime_models") or block.get("models") or [])
        return str(mids[0]).strip() if mids else ""

    # 账户默认（若与主模型不同）优先于任意厂商遍历
    try:
        import json

        from modstore_server.models import User as UserModel

        urow = db.query(UserModel).filter(UserModel.id == int(user_id)).first()
        raw = ((urow.default_llm_json if urow else None) or "").strip()
        prefs: dict[str, Any] = {}
        if raw:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                prefs = loaded
        pref_p = str(prefs.get("provider") or "").strip().lower()
        pref_m = str(prefs.get("model") or "").strip()
        if pref_p and pref_m:
            _add(pref_p, pref_m)
        elif pref_p:
            m0 = await first_model_id(pref_p)
            if m0:
                _add(pref_p, m0)
    except Exception:
        logger.debug("list_chat_failover_candidates prefs skipped", exc_info=True)

    for p in KNOWN_PROVIDERS:
        if len(out) >= chat_failover_max_attempts():
            break
        m0 = await first_model_id(p)
        if m0:
            _add(p, m0)

    return out[: chat_failover_max_attempts()]


def remaining_candidates_after_failure(
    candidates: list[tuple[str, str]],
    failed_index: int,
    *,
    error_text: str,
    status_code: Optional[int],
    key_source_by_provider: dict[str, str],
) -> list[tuple[str, str]]:
    """根据失败类型裁剪后续候选。"""
    rest = list(candidates[failed_index + 1 :])
    if not rest:
        return []
    if not is_chat_failoverable_failure(error_text, status_code):
        return []
    if is_wallet_balance_failure(error_text, status_code):
        # 钱包没钱：平台 Key 预授权仍会失败；仅尝试用户 BYOK
        return [(p, m) for p, m in rest if key_source_by_provider.get(p) == "user_override"]
    return rest


__all__ = [
    "chat_failover_max_attempts",
    "is_wallet_balance_failure",
    "is_chat_failoverable_failure",
    "list_chat_failover_candidates",
    "remaining_candidates_after_failure",
]
