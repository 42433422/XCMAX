"""账号等级与经验体系。

口径：
- 商品 / 会员 / 钱包充值订单都按 1 元 = 100 经验入账（钱包充值同样计入）。
- 1 元 = 100 经验，按分计算后 1 分对应 1 经验，避免小额订单被 floor 吃掉。
- 退款成功后扣回相同经验。
- 通过 (source_type, source_order_id) 唯一键保证幂等：
    * 支付回调与查询补发重复触发时不重复加经验；
    * 退款重试不重复扣经验。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from modstore_server.models import AccountExperienceLedger, User

# 等级阈值：累计净经验 -> 等级；称号与下一等级阈值由 build_level_profile 计算。
# 阈值表保持升序；最后一档作为封顶。
LEVEL_THRESHOLDS: tuple[tuple[int, int, str], ...] = (
    (1, 0, "新手"),
    (2, 1_000, "探索者"),
    (3, 5_000, "创作者"),
    (4, 20_000, "专家"),
    (5, 50_000, "大师"),
    (6, 100_000, "宗师"),
    (7, 200_000, "传奇"),
)

# 哪些订单类型纳入经验体系。商品 / 会员 / 钱包充值均计入。
COUNTABLE_ORDER_KINDS: frozenset[str] = frozenset({"item", "plan", "wallet"})


@dataclass(frozen=True)
class LevelProfile:
    level: int
    title: str
    experience: int
    current_level_min_exp: int
    next_level_min_exp: Optional[int]
    progress: float

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "title": self.title,
            "experience": self.experience,
            "current_level_min_exp": self.current_level_min_exp,
            "next_level_min_exp": self.next_level_min_exp,
            "progress": round(self.progress, 4),
        }


def xp_from_amount(amount_yuan: float | int | None) -> int:
    """按分换算经验：1 元 = 100 经验。负值视为 0。"""
    try:
        amount = float(amount_yuan or 0)
    except (TypeError, ValueError):
        return 0
    if amount <= 0:
        return 0
    return int(round(amount * 100))


def is_countable_order(
    order_kind: str | None, *, item_id: int | None = None, plan_id: str | None = None
) -> bool:
    """判断订单是否纳入经验体系。

    与 _fulfill_paid_order 的判定保持一致：
    - 有 item_id → 商品购买
    - 有 plan_id（先判）→ 会员/套餐（避免仅 order_kind 脏数据漏发）
    - kind ∈ {item, plan, wallet} → 显式消费/充值
    """
    kind = (order_kind or "").strip().lower()
    if item_id and int(item_id or 0) > 0:
        return True
    if (plan_id or "").strip():
        return True
    return kind in COUNTABLE_ORDER_KINDS


def build_level_profile(experience: int | None) -> LevelProfile:
    """根据累计经验计算等级与进度。"""
    exp = max(int(experience or 0), 0)
    current = LEVEL_THRESHOLDS[0]
    next_threshold: Optional[tuple[int, int, str]] = None
    for idx, row in enumerate(LEVEL_THRESHOLDS):
        if exp >= row[1]:
            current = row
            next_threshold = LEVEL_THRESHOLDS[idx + 1] if idx + 1 < len(LEVEL_THRESHOLDS) else None
        else:
            break

    level, current_min, title = current
    next_min: Optional[int] = next_threshold[1] if next_threshold else None
    if next_min is None:
        progress = 1.0
    else:
        span = max(next_min - current_min, 1)
        progress = max(0.0, min(1.0, (exp - current_min) / span))
    return LevelProfile(
        level=level,
        title=title,
        experience=exp,
        current_level_min_exp=current_min,
        next_level_min_exp=next_min,
        progress=progress,
    )


def _existing_entry(
    session: Session, source_type: str, source_order_id: str
) -> Optional[AccountExperienceLedger]:
    return (
        session.query(AccountExperienceLedger)
        .filter(
            AccountExperienceLedger.source_type == source_type,
            AccountExperienceLedger.source_order_id == source_order_id,
        )
        .first()
    )


def _adjust_user_exp(session: Session, user_id: int, delta: int) -> int:
    user = session.query(User).filter(User.id == user_id).with_for_update().first()
    if not user:
        return 0
    current = int(getattr(user, "experience", 0) or 0)
    new_value = max(0, current + delta)
    user.experience = new_value
    return new_value


def apply_order_xp(
    session: Session,
    *,
    user_id: int,
    out_trade_no: str,
    amount_yuan: float | int | None,
    order_kind: str | None,
    item_id: int | None = None,
    plan_id: str | None = None,
    description: str = "",
) -> int:
    """支付履约成功后入账经验，幂等。

    返回写入的 xp_delta；若不计入或已存在，返回 0。
    调用方需自行 session.commit()。
    """
    if not user_id or not out_trade_no:
        return 0
    if not is_countable_order(order_kind, item_id=item_id, plan_id=plan_id):
        return 0
    xp = xp_from_amount(amount_yuan)
    if xp <= 0:
        return 0
    source_type = "order_paid"
    if _existing_entry(session, source_type, out_trade_no):
        return 0
    entry = AccountExperienceLedger(
        user_id=int(user_id),
        source_type=source_type,
        source_order_id=str(out_trade_no),
        amount=float(amount_yuan or 0),
        xp_delta=int(xp),
        description=description or f"订单经验 +{xp} ({out_trade_no})",
    )
    session.add(entry)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return 0
    _adjust_user_exp(session, int(user_id), int(xp))
    return int(xp)


def revoke_order_xp(
    session: Session,
    *,
    user_id: int,
    out_trade_no: str,
    description: str = "",
) -> int:
    """退款成功后扣回该订单已发放的经验，幂等。

    返回扣回的 xp（正数）；若该订单未发放经验或已扣回，返回 0。
    调用方需自行 session.commit()。
    """
    if not user_id or not out_trade_no:
        return 0
    paid_entry = _existing_entry(session, "order_paid", str(out_trade_no))
    if not paid_entry:
        return 0
    if _existing_entry(session, "order_refunded", str(out_trade_no)):
        return 0
    xp = int(paid_entry.xp_delta or 0)
    if xp <= 0:
        return 0
    entry = AccountExperienceLedger(
        user_id=int(user_id),
        source_type="order_refunded",
        source_order_id=str(out_trade_no),
        amount=-float(paid_entry.amount or 0),
        xp_delta=-int(xp),
        description=description or f"退款扣回经验 -{xp} ({out_trade_no})",
    )
    session.add(entry)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return 0
    _adjust_user_exp(session, int(user_id), -int(xp))
    return int(xp)


def get_user_level_profile(session: Session, user_id: int) -> LevelProfile:
    user = session.query(User).filter(User.id == user_id).first()
    exp = int(getattr(user, "experience", 0) or 0) if user else 0
    return build_level_profile(exp)
