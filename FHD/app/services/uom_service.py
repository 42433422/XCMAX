"""UOM 单位换算服务（吸收 Odoo 18 的 UOM / conversion factor 逻辑）。

同一产品可拥有多个计量单位（如 斤/公斤/箱/个），同一量纲（UOM category）内的单位
通过 ``factor``（相对该类别基准单位的换算系数，基准单位 factor=1）互相换算，满足：

- ``目标数量 = 源数量 × factor_source ÷ factor_target``，全程 ``Decimal`` 精确运算，
  保证"10 箱 × 20 斤/箱 = 200 斤"这类换算在数量与金额上一致（金额 = 换算后数量 × 单价）。
- 遇到未知单位或文本中出现多个单位字面量时，返回**澄清要求**而非按默认单位执行
  （配合 workflow 层的 ``detect_erp_clarification`` 反问门禁，二者口径一致）。
"""

from __future__ import annotations

import re
from contextlib import nullcontext
from decimal import Decimal
from typing import Any

from app.db.models import Product, UomCategory, UomUnit
from app.db.session import get_db

__all__ = ["UomConversionError", "UomService"]


class UomConversionError(ValueError):
    """单位换算失败：未知单位 / 非正系数 / 换算无法完成。"""


# 匹配"数字 + 单位字面量"（斤/公斤/箱/个/件/包/瓶/盒/吨 等，中文或字母）。
_QTY_UNIT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([\u4e00-\u9fa5A-Za-z]+)")


class UomService:
    """UOM 换算服务：支持注入会话（``db``）以便在事务内复用，或独立自开会话。"""

    def __init__(self, db: Any = None) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # 纯函数换算核心（Decimal 安全）
    # ------------------------------------------------------------------
    @staticmethod
    def _dec(value: Any) -> Decimal:
        if isinstance(value, Decimal):
            return value
        if value is None:
            raise UomConversionError("换算数量/系数不能为空")
        try:
            return Decimal(str(value))
        except (TypeError, ValueError) as exc:  # pragma: no cover - 防御
            raise UomConversionError(f"无法解析为十进制: {value!r}") from exc

    def convert(self, quantity: Any, from_factor: Any, to_factor: Any) -> Decimal:
        """按系数换算：``quantity × from_factor ÷ to_factor``。

        ``factor`` 表示"1 个该单位 = factor 个基准单位"（基准单位 factor=1）。
        """
        qty = self._dec(quantity)
        ff = self._dec(from_factor)
        tf = self._dec(to_factor)
        if ff <= 0 or tf <= 0:
            raise UomConversionError("换算系数必须大于 0")
        return qty * ff / tf

    # ------------------------------------------------------------------
    # 获取某产品/类别的单位系数表
    # ------------------------------------------------------------------
    def get_product_units(
        self,
        product: Product | None = None,
        *,
        category_code: str | None = None,
        tenant_id: int | None = None,
    ) -> dict[str, Decimal]:
        """返回 ``{单位代码: 相对基准的换算系数}``。

        优先读取产品所属 UOM category 下已激活的 ``UomUnit``（权威来源）；
        无 category 时退回仅含产品自身 ``unit`` 的单元素表（factor 取产品 ``uom_factor``）。
        """
        units: dict[str, Decimal] = {}
        cat_code = category_code or (product.uom_category if product is not None else None)

        cm = nullcontext(self._db) if self._db is not None else get_db()
        with cm as db:
            if cat_code:
                cat_q = db.query(UomCategory)
                if tenant_id is not None:
                    cat_q = cat_q.filter(UomCategory.tenant_id == tenant_id)
                category = cat_q.filter(UomCategory.code == cat_code).first()
                if category is not None:
                    unit_q = db.query(UomUnit).filter(
                        UomUnit.category_id == category.id, UomUnit.is_active == 1
                    )
                    if tenant_id is not None:
                        unit_q = unit_q.filter(UomUnit.tenant_id == tenant_id)
                    for u in unit_q.all():
                        units[u.code] = self._dec(u.factor)

        if product is not None and product.unit not in units:
            factor = product.uom_factor if product.uom_factor is not None else Decimal("1")
            units[product.unit] = self._dec(factor)
        return units

    def convert_quantity(
        self,
        quantity: Any,
        from_unit: str,
        to_unit: str,
        *,
        product: Product | None = None,
        units: dict[str, Decimal] | None = None,
        tenant_id: int | None = None,
    ) -> Decimal:
        """在已知单位表内换算数量；任一单位未知即抛错，绝不静默使用默认单位。"""
        unit_table = (
            units if units is not None else self.get_product_units(product, tenant_id=tenant_id)
        )
        if not unit_table:
            raise UomConversionError("未配置任何计量单位")
        if from_unit not in unit_table:
            raise UomConversionError(f"未知单位: {from_unit}")
        if to_unit not in unit_table:
            raise UomConversionError(f"未知单位: {to_unit}")
        return self.convert(quantity, unit_table[from_unit], unit_table[to_unit])

    def convert_amount(
        self,
        quantity: Any,
        from_unit: str,
        to_unit: str,
        unit_price: Any,
        *,
        product: Product | None = None,
        units: dict[str, Decimal] | None = None,
        tenant_id: int | None = None,
    ) -> dict[str, Any]:
        """换算数量并按换算后数量计算金额，保证换算前后数量/金额一致。

        返回：``{quantity, unit, unit_price, amount}``（``amount = quantity × unit_price``，
        以 ``to_unit`` 计）。金额一致性由换算的乘法结合律保证：
        ``(数量×系数)×单价 = 数量×(系数×单价)``。
        """
        converted = self.convert_quantity(
            quantity, from_unit, to_unit, product=product, units=units, tenant_id=tenant_id
        )
        price = self._dec(unit_price)
        amount = (converted * price).quantize(Decimal("0.01"))
        return {
            "quantity": converted,
            "unit": to_unit,
            "unit_price": price,
            "amount": amount,
        }

    # ------------------------------------------------------------------
    # 自然语言数量+单位解析（歧义 → 澄清，而非按默认单位执行）
    # ------------------------------------------------------------------
    def resolve_quantity_unit(
        self,
        quantity_text: Any,
        *,
        product: Product | None = None,
        units: dict[str, Decimal] | None = None,
    ) -> dict[str, Any]:
        """解析"数量 + 单位"的自然语言表达。

        - 未提供数量 / 单位未知 / 出现多个单位字面量 → 返回 ``requires_clarification=True``
          及 ``reason``（missing_quantity / unknown_unit / ambiguous_unit），不按默认单位执行；
        - 解析成功 → ``{quantity: Decimal, unit: str, requires_clarification: False}``。
        """
        unit_table = units if units is not None else self.get_product_units(product=product)
        text = str(quantity_text or "").strip()
        if not text:
            return {
                "requires_clarification": True,
                "reason": "missing_quantity",
                "question": "请提供要操作的数量与单位。",
            }

        matches = _QTY_UNIT_RE.findall(text)
        distinct_units = {u for _, u in matches}
        if len(matches) >= 2 and len(distinct_units) >= 2:
            return {
                "requires_clarification": True,
                "reason": "ambiguous_unit",
                "question": "检测到多个计量单位，请确认实际操作单位与换算口径后我再执行。",
            }
        if not matches:
            return {
                "requires_clarification": True,
                "reason": "missing_unit",
                "question": "未识别到计量单位，请明确单位（如 斤/箱/个）后我再执行。",
            }
        raw_qty, unit = matches[0]
        if not unit_table or unit not in unit_table:
            return {
                "requires_clarification": True,
                "reason": "unknown_unit",
                "question": f"产品未配置单位「{unit}」或该单位未知，请确认后再执行。",
            }
        return {
            "requires_clarification": False,
            "quantity": self._dec(raw_qty),
            "unit": unit,
        }
