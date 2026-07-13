"""Pure mapping and cell-normalization rules for Excel imports."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from app.utils.operational_errors import RECOVERABLE_ERRORS


def _infer_product_field_mapping(
    columns: list[str],
    *,
    price_column_hint: str | None = None,
) -> dict[str, str]:
    """按列名推断产品字段映射。"""
    cols = [str(c) for c in columns]
    mapping: dict[str, str] = {}

    def _norm(s: str) -> str:
        return s.replace(" ", "").replace("\u3000", "").strip()

    norm_pairs = [(c, _norm(c)) for c in cols]
    taken: set[str] = set()

    def _take(field: str, col: str) -> None:
        if field not in mapping and col not in taken:
            mapping[field] = col
            taken.add(col)

    for c, cn in norm_pairs:
        cl = c.lower()
        if "规格" in cn and "号" not in cn and "编" not in cn:
            continue
        if ("编" in c and "号" in c) or "编号" in cn or "编码" in cn or "sku" in cl:
            _take("model_number", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "型号" in c or "model" in cl:
            _take("model_number", c)
            break

    for c, cn in norm_pairs:
        if c in taken:
            continue
        if "规格" in c or "规格" in cn or ("规" in c and "格" in c):
            _take("specification", c)
            break

    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "产品名称" in cn or "品名" in cn or "名称" in c or "name" in cl:
            _take("name", c)
            break

    hint = _norm(price_column_hint) if price_column_hint else ""
    if hint:
        for c, cn in norm_pairs:
            if c in taken:
                continue
            cn_l = cn.lower()
            hl = hint.lower()
            if hint in cn or hl in cn_l or hint in c:
                _take("price", c)
                break

    if "price" not in mapping:
        price_order = [
            ("调价前", "price"),
            ("调价后", "price"),
            ("现价", "price"),
            ("单价", "price"),
            ("价格", "price"),
            ("price", "price"),
        ]
        for key_sub, field in price_order:
            ks = key_sub.lower()
            for c, cn in norm_pairs:
                if c in taken:
                    continue
                cn_l = cn.lower()
                if ks in cn_l or key_sub in c:
                    _take(field, c)
                    break
            if "price" in mapping:
                break

    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "单位" in c or "unit" in cl:
            _take("unit", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "数量" in c or "quantity" in cl or "qty" in cl:
            _take("quantity", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "备注" in c or "描述" in c or "description" in cl:
            _take("description", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "品牌" in c or "brand" in cl:
            _take("brand", c)
            break
    for c, cn in norm_pairs:
        cl = c.lower()
        if c in taken:
            continue
        if "类别" in c or "category" in cl or "分类" in c:
            _take("category", c)
            break

    return mapping


def _excel_cell_as_clean_str(val: Any) -> str:
    """pandas/Excel 单元格转展示用字符串；NaN、字面量 'nan' 视为空。"""
    if val is None:
        return ""
    if isinstance(val, bool):
        return ""
    try:
        if pd.isna(val):
            return ""
    except RECOVERABLE_ERRORS:
        pass
    if isinstance(val, float) and val != val:
        return ""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        s = str(val).strip()
        if s.lower() in ("nan", "inf", "-inf"):
            return ""
        return s
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null", "<na>", "nat"):
        return ""
    return s


def _excel_cell_as_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or (isinstance(val, float) and val != val):
            return default
        if pd.isna(val):
            return default
    except RECOVERABLE_ERRORS:
        pass
    try:
        v = float(val)
        if v != v:
            return default
        return v
    except (TypeError, ValueError):
        return default


_CLAUSE_SUBSTRINGS = (
    "含税价",
    "含税",
    "月结",
    "数期",
    "担保",
    "付款责任",
    "保质保量",
    "验收签名",
    "所送货物",
    "若贵司",
    "未能按时付款",
    "配套使用",
    "我厂产品",
    "所示比例施工",
    "供应方签名",
    "供应方",
    "采购方",
    "盖章",
    "出资人",
    "签名及盖章",
    "以上价格为",
    "以上各种产品",
    "请严格按",
    "请配套",
)


def _looks_like_contract_or_footer_line(name: str) -> bool:
    t = (name or "").strip()
    if len(t) < 6:
        return False
    if any(s in t for s in _CLAUSE_SUBSTRINGS):
        return True
    # 「1、xxx」「2、xxx」式条款，且去掉序号后仍像说明句
    m = re.match(r"^\s*(\d+)[、．\.]\s*(.+)$", t)
    if m and len(m.group(2)) >= 8:
        rest = m.group(2)
        if any(s in rest for s in _CLAUSE_SUBSTRINGS):
            return True
        if re.search(r"(以上|所送|数期|保质|验收|付款|月结|含税|施工|配套|货物)", rest):
            return True
    return False


__all__ = [
    "_infer_product_field_mapping",
    "_excel_cell_as_clean_str",
    "_excel_cell_as_float",
    "_looks_like_contract_or_footer_line",
]
