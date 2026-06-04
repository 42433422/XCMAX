"""三套计费引擎（阶段 11）：订阅 / 买断 / 增值计量。

统一抽象：
- ``BillingMode``      订阅 / 买断 / 计量
- ``Charge``           一次计费结果（金额、币种、明细）
- ``BillingEngine``    抽象基类；三个具体引擎实现 ``quote()``

设计目标：与 ``infrastructure.payment.payment_sot`` 对齐，金额计算与「真相源」解耦，
计费引擎只负责「算多少钱」，由 metering 层负责「记在哪、谁扣款」。
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


class BillingMode(str, enum.Enum):
    SUBSCRIPTION = "subscription"  # 订阅（周期费）
    ONE_TIME = "one_time"          # 买断（一次性）
    USAGE = "usage"                # 增值 / 计量（按量）


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class Charge:
    mode: BillingMode
    amount: Decimal
    currency: str = "CNY"
    period: str = ""                       # 订阅周期，如 "monthly" / "yearly"
    line_items: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "amount": float(self.amount),
            "currency": self.currency,
            "period": self.period,
            "line_items": self.line_items,
            "meta": self.meta,
        }


class BillingEngine(abc.ABC):
    mode: BillingMode

    @abc.abstractmethod
    def quote(self, **kwargs) -> Charge:
        """根据入参计算应收金额。"""
        raise NotImplementedError


class SubscriptionEngine(BillingEngine):
    """订阅计费：按周期 + 可选按席位（seats）+ 比例折扣。"""

    mode = BillingMode.SUBSCRIPTION

    # 周期 -> 相对月价的倍数（年付打折）
    _PERIOD_FACTOR = {"monthly": Decimal("1"), "quarterly": Decimal("3") * Decimal("0.95"),
                      "yearly": Decimal("12") * Decimal("0.85")}

    def quote(self, *, plan_price_monthly, seats: int = 1, period: str = "monthly",
              discount: float = 0.0, currency: str = "CNY", **_) -> Charge:
        factor = self._PERIOD_FACTOR.get(period, Decimal("1"))
        base = _money(plan_price_monthly) * factor * Decimal(max(1, int(seats)))
        amount = _money(base * (Decimal("1") - _money(discount) / 100 if discount > 1 else (Decimal("1") - _money(discount))))
        return Charge(
            mode=self.mode, amount=amount, currency=currency, period=period,
            line_items=[{"desc": f"订阅 {period} x {seats} 席位", "amount": float(amount)}],
            meta={"seats": seats, "period": period, "discount": discount},
        )


class OneTimeEngine(BillingEngine):
    """买断计费：一次性价格 + 数量。"""

    mode = BillingMode.ONE_TIME

    def quote(self, *, unit_price, quantity: int = 1, currency: str = "CNY", **_) -> Charge:
        amount = _money(_money(unit_price) * Decimal(max(1, int(quantity))))
        return Charge(
            mode=self.mode, amount=amount, currency=currency,
            line_items=[{"desc": f"买断 x {quantity}", "amount": float(amount)}],
            meta={"quantity": quantity},
        )


class UsageMeteringEngine(BillingEngine):
    """增值/计量计费：按用量分档（tiered）计价 + 起步价。

    tiers 形如 [{"up_to": 1000, "price_per_unit": 0.01}, {"up_to": null, "price_per_unit": 0.005}]
    （up_to=None 表示无上限的最后一档）。
    """

    mode = BillingMode.USAGE

    def quote(self, *, units, tiers: list[dict] | None = None, unit_price=None,
              min_charge=0.0, currency: str = "CNY", **_) -> Charge:
        units = Decimal(str(units))
        total = Decimal("0")
        line_items: list[dict] = []
        if tiers:
            remaining = units
            lower = Decimal("0")
            for tier in tiers:
                up_to = tier.get("up_to")
                # 单价保留完整精度（不可量化到分，否则 0.005 会被舍入成 0.01）
                price = Decimal(str(tier.get("price_per_unit", 0)))
                cap = Decimal(str(up_to)) if up_to is not None else None
                span = (cap - lower) if cap is not None else remaining
                billable = min(remaining, span) if cap is not None else remaining
                if billable <= 0:
                    break
                seg = _money(billable * price)
                total += seg
                line_items.append({"desc": f"用量档 {lower}-{up_to or '∞'}", "units": float(billable), "amount": float(seg)})
                remaining -= billable
                lower = cap if cap is not None else lower
                if remaining <= 0:
                    break
        else:
            price = Decimal(str(unit_price or 0))
            total = _money(units * price)
            line_items.append({"desc": "按量计费", "units": float(units), "amount": float(total)})

        amount = _money(max(total, _money(min_charge)))
        return Charge(
            mode=self.mode, amount=amount, currency=currency, line_items=line_items,
            meta={"units": float(units), "min_charge": float(min_charge)},
        )


_ENGINES: dict[BillingMode, BillingEngine] = {
    BillingMode.SUBSCRIPTION: SubscriptionEngine(),
    BillingMode.ONE_TIME: OneTimeEngine(),
    BillingMode.USAGE: UsageMeteringEngine(),
}


def get_engine(mode: str | BillingMode) -> BillingEngine:
    m = BillingMode(mode) if not isinstance(mode, BillingMode) else mode
    return _ENGINES[m]


def quote(mode: str | BillingMode, **kwargs) -> Charge:
    """统一计费入口：按模式选择引擎并报价。"""
    return get_engine(mode).quote(**kwargs)


__all__ = [
    "BillingMode",
    "Charge",
    "BillingEngine",
    "SubscriptionEngine",
    "OneTimeEngine",
    "UsageMeteringEngine",
    "get_engine",
    "quote",
]
