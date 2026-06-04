"""专业版 Excel 导入：是否走规则捷径的策略与计量单位常量。"""

from __future__ import annotations

import os
import re
from typing import Any

# 报价表中「单位」列常为件/箱等计量，不是 purchase unit（客户全称）
_EXCEL_IMPORT_MEASURE_UNIT_TOKENS = frozenset(
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
        "套",
        "组",
        "台",
        "条",
        "张",
        "支",
        "pcs",
        "pc",
        "kg",
        "g",
        "ml",
        "l",
        "升",
        "公斤",
        "千克",
    }
)
EXCEL_IMPORT_MEASURE_UNIT_TOKENS = _EXCEL_IMPORT_MEASURE_UNIT_TOKENS
EXCEL_IMPORT_QTY_MEASURE_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*(?:件|个|只|箱|盒|包|袋|瓶|桶|罐|套|组|台|条|张|支|pcs|pc)\s*$",
    re.I,
)


def skip_pro_excel_deterministic_import(context: dict[str, Any] | None) -> bool:
    """
    是否跳过「专业版聊天：excel_analysis + 导入关键词 → 直接规则入库」的捷径。
    """
    ctx = context if isinstance(context, dict) else {}
    if ctx.get("excel_import_use_deterministic_shortcut") is True:
        return False
    if ctx.get("excel_import_skip_deterministic_shortcut") is True:
        return True
    if ctx.get("excel_import_ai_decides") is True:
        return True
    _truthy = frozenset({"1", "true", "yes", "on"})
    if (
        str(os.environ.get("XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT") or "").strip().lower()
        in _truthy
    ):
        return True
    if str(os.environ.get("XCAGI_EXCEL_IMPORT_AI_DECIDES") or "").strip().lower() in _truthy:
        return True
    return False
