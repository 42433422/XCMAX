"""注册时按真相源派生并写入账号体系字段。

写入 ``User``：
- ``tier``               账号身份（enterprise SKU → enterprise，否则 personal）
- ``industry_id``        当前行业（注册表单选择，可空则保持默认）
- ``budget_range``       预算区间（account_tier 派生来源）
- ``account_tier``       由 budget_range 派生（仅 enterprise）
- ``entitled_industries``按 tier + industry_id 初始化
"""

from __future__ import annotations

import logging

from app.application.account_tier_derivation import (
    derive_account_tier,
    should_have_account_tier,
)
from app.application.entitled_industries_init import init_entitled_industries_for_user
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


def apply_account_profile_on_register(
    username: str,
    *,
    tier: str = "personal",
    industry_id: str = "",
    budget_range: str = "",
) -> None:
    """注册成功后写入账号体系字段（幂等：找不到用户则跳过）。"""
    uname = (username or "").strip()
    if not uname:
        return
    t = (tier or "personal").strip().lower()
    iid = (industry_id or "").strip()
    budget = (budget_range or "").strip()
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.query(User).filter(User.username == uname).first()
            if user is None:
                return
            user.tier = t
            if iid:
                user.industry_id = iid
            if budget:
                user.budget_range = budget
            user.account_tier = derive_account_tier(budget) if should_have_account_tier(t) else None
            user.entitled_industries = init_entitled_industries_for_user(
                t, iid or str(getattr(user, "industry_id", "") or "")
            )
            db.commit()
    except RECOVERABLE_ERRORS:
        logger.exception("apply_account_profile_on_register failed for %s", uname)


def set_account_industry(username: str, industry_id: str) -> None:
    """选行业/装行业种子后把所选行业持久化到账号(industry_id + entitled_industries)。

    注册只定了初始行业(常为「通用」),用户后续在引导页选行业(install-industry-seed)
    必须回填账号,否则账号行业与所选不一致(单一真相源破裂)。幂等:找不到用户/空行业则跳过。
    """
    uname = (username or "").strip()
    iid = (industry_id or "").strip()
    if not uname or not iid:
        return
    try:
        from app.db.models.user import User
        from app.db.session import get_db

        with get_db() as db:
            user = db.query(User).filter(User.username == uname).first()
            if user is None:
                return
            user.industry_id = iid
            tier = str(getattr(user, "tier", "") or "personal").strip().lower()
            user.entitled_industries = init_entitled_industries_for_user(tier, iid)
            db.commit()
    except RECOVERABLE_ERRORS:
        logger.exception("set_account_industry failed for %s", uname)
