"""账号等级兼容：已授予的旧等级保留，客户自报预算不授予权益。"""

from __future__ import annotations

# 预算区间规范展示值（前端 select 选项；空值/“暂未确定”表示未选）
BUDGET_RANGES: tuple[str, ...] = ("1–5 万", "5–10 万", "10–50 万", "50–100 万")

VALID_ACCOUNT_TIERS: frozenset[str] = frozenset({"normal", "pro", "max", "ultra"})
DEFAULT_ACCOUNT_TIER = "normal"


def derive_account_tier(budget_range: str | None) -> str:
    """兼容注册入口；预算仅作销售线索，新授权统一普通等级。"""
    return DEFAULT_ACCOUNT_TIER


def should_have_account_tier(tier: str | None) -> bool:
    """账号等级仅对企业账号有意义（personal/admin 时为 NULL）。"""
    return str(tier or "").strip().lower() == "enterprise"


def normalize_account_tier(raw: str | None) -> str | None:
    """校验并归一化管理端传入的 account_tier；非法值返回 None。"""
    v = str(raw or "").strip().lower()
    return v if v in VALID_ACCOUNT_TIERS else None


def resolve_account_tier_for_user(tier: str | None, account_tier: str | None) -> str | None:
    """运行时派生用户的有效账号等级。

    - 非企业账号（personal/admin）→ None
    - 企业账号但未设 account_tier → 默认 normal
    - 企业账号已设 → 返回已设值（非法值回退 normal）
    """
    if not should_have_account_tier(tier):
        return None
    return normalize_account_tier(account_tier) or DEFAULT_ACCOUNT_TIER
