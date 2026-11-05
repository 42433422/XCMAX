"""已授权行业（entitled_industries）初始化与校验。

单一真相源 + 自动派生（维度 2 · 行业授权）：
- 真相源：``User.entitled_industries``（admin 分配 / 注册时按 tier 初始化）
- 约束：``User.industry_id`` 写入时必须 ∈ ``entitled_industries``

初始化规则：
- personal   → ["通用"]
- enterprise → ["通用", <selected_industry_id>]（去重保序）
- admin      → ["管理端"]
"""

from __future__ import annotations

DEFAULT_INDUSTRY = "通用"
ADMIN_INDUSTRY = "管理端"


def merge_entitled_industries(existing: list[str] | None, additions: list[str] | None) -> list[str]:
    """合并已授权行业，去重并保持插入顺序。"""
    out: list[str] = []
    for item in list(existing or []) + list(additions or []):
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def init_entitled_industries_for_user(tier: str | None, industry_id: str | None) -> list[str]:
    """按账号身份初始化已授权行业集合。"""
    t = str(tier or "").strip().lower()
    if t == "admin":
        return [ADMIN_INDUSTRY]
    if t == "enterprise":
        iid = str(industry_id or "").strip()
        return merge_entitled_industries([DEFAULT_INDUSTRY], [iid] if iid else [])
    # personal 及其它 → 仅通用
    return [DEFAULT_INDUSTRY]


def validate_industry_in_entitled(
    industry_id: str | None, entitled_industries: list[str] | None
) -> bool:
    """校验 industry_id 是否在已授权集合内。

    空 industry_id 视为合法（表示沿用默认，不切换行业）。
    """
    iid = str(industry_id or "").strip()
    if not iid:
        return True
    ents = [str(x or "").strip() for x in (entitled_industries or [])]
    return iid in ents
