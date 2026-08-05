"""产品仓储共享查询辅助：抽取 find_all / find_all_dict 复用过滤逻辑，避免超大文件。

- TRIVIAL_MEASURE_UNITS：products.unit 历史误填的纯计量词集合（供 find_product_units 去重排除）。
- apply_product_filters：对查询应用 unit_name / model_number / keyword 过滤（不含 get_db，纯查询构造）。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_

from app.db.models import Product as ProductModel

# products.unit 历史上常被误填为计量单位；客户筛选项应对齐 purchase_units，故从「产品表去重」里排除这些纯计量词（精确匹配）。
TRIVIAL_MEASURE_UNITS = frozenset(
    {
        "件",
        "个",
        "只",
        "箱",
        "盒",
        "包",
        "袋",
        "瓶",
        "桶",
        "罐",
        "千克",
        "公斤",
        "克",
        "斤",
        "两",
        "吨",
        "米",
        "厘米",
        "毫米",
        "千米",
        "升",
        "毫升",
        "套",
        "组",
        "台",
        "条",
        "张",
        "根",
        "卷",
        "块",
        "片",
        "支",
        "双",
        "对",
        "副",
        "把",
        "捆",
        "扎",
    }
)


def apply_product_filters(query: Any, **kwargs: Any) -> Any:
    """对产品查询应用 unit_name / model_number / keyword 过滤，返回过滤后的 query。"""
    unit_name = kwargs.get("unit_name")
    if unit_name:
        query = query.filter(ProductModel.unit == unit_name)

    model_number = kwargs.get("model_number")
    if model_number:
        model_token = str(model_number).strip()
        if model_token:
            pattern = f"%{model_token}%"
            # 优先通过型号字段匹配；兼容历史数据中型号写在名称里的情况。
            query = query.filter(
                or_(
                    ProductModel.model_number.like(pattern),
                    ProductModel.name.like(pattern),
                )
            )

    keyword = kwargs.get("keyword")
    if keyword:
        keyword_text = str(keyword).strip()
        u = func.coalesce(ProductModel.unit, "")
        n = func.coalesce(ProductModel.name, "")
        m = func.coalesce(ProductModel.model_number, "")
        s = func.coalesce(ProductModel.specification, "")
        concat_blob = u.op("||")(n).op("||")(m).op("||")(s)

        def _one_kw(kw: str) -> Any:
            k = str(kw).strip()
            if not k:
                return None
            tok = k.upper().replace("-", "").replace(" ", "")
            nm = func.upper(
                func.replace(
                    func.replace(func.coalesce(ProductModel.model_number, ""), "-", ""),
                    " ",
                    "",
                )
            )
            return or_(
                ProductModel.unit.like(f"%{k}%"),
                ProductModel.name.like(f"%{k}%"),
                ProductModel.model_number.like(f"%{k}%"),
                ProductModel.specification.like(f"%{k}%"),
                nm.like(f"%{tok}%"),
                concat_blob.like(f"%{k}%"),
            )

        segments = re.findall(r"[\u4e00-\u9fff]+|[0-9]+|[A-Za-z]+", keyword_text)
        segments = [p for p in segments if p.strip()]

        if len(segments) > 1:
            for seg in segments:
                filt = _one_kw(seg)
                if filt is not None:
                    query = query.filter(filt)
        else:
            kw_use = segments[0] if segments else keyword_text
            filt = _one_kw(kw_use if kw_use else keyword_text)
            if filt is not None:
                query = query.filter(filt)

    return query