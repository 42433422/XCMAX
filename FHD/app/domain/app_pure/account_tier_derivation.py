"""账号等级（普通/Pro/Max/Ultra）自动派生。

单一真相源 + 自动派生（维度 4）：
- 真相源：``User.budget_range``（注册时用户选的预算区间）
- 派生值：``User.account_tier``（注册时由 budget_range 派生写入；仅 ``tier=enterprise`` 有意义）

预算区间的规范展示值与 RegisterView / saas_plans.json 一致（注意中文长连字符 ``–`` U+2013）。
派生匹配时对连字符与空格做归一化，兼容前端可能传来的短横 ``-`` 等变体。
"""

from __future__ import annotations

# 预算区间规范展示值（前端 select 选项；空值/“暂未确定”表示未选）
BUDGET_RANGES: tuple[str, ...] = ("1–5 万", "5–10 万", "10–50 万", "50–100 万")

VALID_ACCOUNT_TIERS: frozenset[str] = frozenset({"normal", "pro", "max", "ultra"})
DEFAULT_ACCOUNT_TIER = "normal"

# 归一化后的预算 → 账号等级映射
_NORMALIZED_BUDGET_TO_TIER: dict[str, str] = {
    "1-5万": "normal",
    "5-10万": "pro",
    "10-50万": "max",
    "50-100万": "ultra",
    # 旧档位兼容：保持原有 tier 语义，避免存量预算值回退到 normal。
    "5万以内": "normal",
    "5-20万": "pro",
    "20-50万": "max",
    "50万以上": "ultra",
}


def _normalize_budget(raw: str | None) -> str:
    """归一化预算字符串：统一连字符、去空格，便于匹配。"""
    s = str(raw or "").strip()
    # 各类连字符（全角横线/破折号/中文长连字符）统一成 ASCII '-'
    for dash in ("－", "—", "–", "~", "～"):
        s = s.replace(dash, "-")
    # 去掉普通空格与不间断空格
    s = s.replace(" ", "").replace(" ", "")
    return s


def derive_account_tier(budget_range: str | None) -> str:
    """根据预算区间派生账号等级；未知/空值 → ``normal``。"""
    return _NORMALIZED_BUDGET_TO_TIER.get(_normalize_budget(budget_range), DEFAULT_ACCOUNT_TIER)


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
