"""渠道 / 代理 / OEM 分佣体系（阶段 11）。

定义三类销售渠道及其分佣模型，并提供把一笔成交金额拆分为
平台 / 渠道 / 代理（多级）/ OEM 各方应得的计算。

- ``ChannelType``    direct（直销）/ reseller（渠道代理）/ oem（贴牌）
- ``ChannelPartner`` 渠道方（含费率、上级、OEM 折扣）
- ``split_commission`` 按渠道链路拆分金额（支持二级代理）
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


class ChannelType(str, enum.Enum):
    DIRECT = "direct"       # 平台直销
    RESELLER = "reseller"   # 渠道 / 代理分销
    OEM = "oem"             # 贴牌 / OEM


def _money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class ChannelPartner:
    partner_id: str
    name: str
    channel_type: ChannelType = ChannelType.RESELLER
    # 渠道分佣比例（占成交额，0-1）。
    commission_rate: Decimal = field(default_factory=lambda: Decimal("0.20"))
    # 上级渠道（二级代理场景），上级按 override_rate 抽成。
    parent_id: str = ""
    parent_override_rate: Decimal = field(default_factory=lambda: Decimal("0"))
    # OEM 拿货折扣（OEM 成本 = 成交额 * (1 - oem_discount)）。
    oem_discount: Decimal = field(default_factory=lambda: Decimal("0"))


@dataclass
class CommissionSplit:
    gross: Decimal
    currency: str
    platform: Decimal
    partner: Decimal
    parent: Decimal
    oem_cost: Decimal
    breakdown: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "gross": float(self.gross),
            "currency": self.currency,
            "platform": float(self.platform),
            "partner": float(self.partner),
            "parent": float(self.parent),
            "oem_cost": float(self.oem_cost),
            "breakdown": self.breakdown,
        }


def split_commission(
    gross,
    partner: ChannelPartner | None = None,
    currency: str = "CNY",
) -> CommissionSplit:
    """把一笔成交额按渠道链路拆分。

    - direct / 无 partner：全额归平台。
    - reseller：partner 抽 commission_rate；若有上级，上级抽 parent_override_rate；平台得剩余。
    - oem：OEM 按 (1 - oem_discount) 拿货，差额（折扣部分）记为平台让利，平台收 oem_cost。
    """
    gross_m = _money(gross)
    breakdown: list[dict] = []

    if partner is None or partner.channel_type == ChannelType.DIRECT:
        return CommissionSplit(
            gross=gross_m, currency=currency, platform=gross_m,
            partner=Decimal("0"), parent=Decimal("0"), oem_cost=Decimal("0"),
            breakdown=[{"party": "platform", "amount": float(gross_m)}],
        )

    if partner.channel_type == ChannelType.OEM:
        oem_cost = _money(gross_m * (Decimal("1") - partner.oem_discount))
        platform = oem_cost  # 平台向 OEM 收取的批发价
        breakdown.append({"party": "oem", "role": "wholesale_cost", "amount": float(oem_cost)})
        breakdown.append({"party": "platform", "amount": float(platform)})
        return CommissionSplit(
            gross=gross_m, currency=currency, platform=platform,
            partner=Decimal("0"), parent=Decimal("0"), oem_cost=oem_cost, breakdown=breakdown,
        )

    # reseller（含可选二级代理）
    partner_amt = _money(gross_m * partner.commission_rate)
    parent_amt = _money(gross_m * partner.parent_override_rate) if partner.parent_id else Decimal("0")
    platform = _money(gross_m - partner_amt - parent_amt)
    breakdown.append({"party": "partner", "partner_id": partner.partner_id, "amount": float(partner_amt)})
    if parent_amt > 0:
        breakdown.append({"party": "parent", "partner_id": partner.parent_id, "amount": float(parent_amt)})
    breakdown.append({"party": "platform", "amount": float(platform)})
    return CommissionSplit(
        gross=gross_m, currency=currency, platform=platform,
        partner=partner_amt, parent=parent_amt, oem_cost=Decimal("0"), breakdown=breakdown,
    )


def partner_from_dict(data: dict) -> ChannelPartner:
    return ChannelPartner(
        partner_id=str(data.get("partner_id") or ""),
        name=str(data.get("name") or ""),
        channel_type=ChannelType(str(data.get("channel_type") or "reseller")),
        commission_rate=Decimal(str(data.get("commission_rate", "0.20"))),
        parent_id=str(data.get("parent_id") or ""),
        parent_override_rate=Decimal(str(data.get("parent_override_rate", "0"))),
        oem_discount=Decimal(str(data.get("oem_discount", "0"))),
    )


__all__ = [
    "ChannelType",
    "ChannelPartner",
    "CommissionSplit",
    "split_commission",
    "partner_from_dict",
]
