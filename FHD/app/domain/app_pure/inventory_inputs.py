"""Named stock-in input alternatives shared by planning and execution gates."""

import math
from typing import Any


def missing_stock_in_fields(params: dict[str, Any]) -> list[str]:
    missing = []
    for id_key, name_key in (("product_id", "model_number"), ("warehouse_id", "warehouse_name")):
        if params.get(id_key) in (None, "") and not str(params.get(name_key) or "").strip():
            missing.append(name_key)
    if params.get("quantity") in (None, ""):
        missing.append("quantity")
    return missing


def validate_stock_in_request(params: dict[str, Any]) -> None:
    missing = missing_stock_in_fields(params)
    if missing:
        raise ValueError("缺少入库参数：" + "、".join(missing))
    for key in ("product_id", "warehouse_id"):
        value = params.get(key)
        if value not in (None, "") and (
            isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0
        ):
            raise ValueError("产品和仓库编号必须是正整数")
    for key in ("model_number", "warehouse_name"):
        if key in params and not isinstance(params[key], str):
            raise ValueError("产品型号和仓库名称必须是文本")
    quantity = params.get("quantity")
    if quantity is None:
        valid = False
    else:
        try:
            valid = (
                not isinstance(quantity, bool)
                and math.isfinite(float(quantity))
                and float(quantity) > 0
            )
        except (TypeError, ValueError, OverflowError):
            valid = False
    if not valid:
        raise ValueError("入库数量必须是有效正数")
