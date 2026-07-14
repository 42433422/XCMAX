"""Excel import policy helpers for AI chat."""

from __future__ import annotations

import os
import re
from typing import Any


def _skip_pro_excel_deterministic_import(context: dict[str, Any] | None) -> bool:
    """
    是否跳过「专业版聊天：excel_analysis + 导入关键词 → 直接规则入库」的捷径。

    返回 True：不跑规则捷径，由主对话 / Planner 与工具链决策映射与写入。

    - ``context.excel_import_use_deterministic_shortcut == True`` → **不跳过**（强制走规则捷径，覆盖下列各条）
    - ``context.excel_import_ai_decides == True`` → 跳过（与产品默认「AI 决策」一致）
    - ``context.excel_import_skip_deterministic_shortcut == True`` → 跳过
    - 环境变量 ``XCAGI_EXCEL_IMPORT_AI_DECIDES`` / ``XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT`` 为 1/true/on → 跳过
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


# 报价表中「单位」列常为件/箱等计量，不是 purchase unit（客户全称）；与 app/legacy/tools.py 语义对齐。
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
    }
)
_EXCEL_IMPORT_QTY_MEASURE_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*(?:件|个|只|箱|盒|包|袋|瓶|桶|罐|套|组|台|条|张|支|pcs|pc)\s*$",
    re.I,
)


def _enrich_confirmation_inner(inner: dict[str, Any], *, action: str) -> dict[str, Any]:
    """Attach structured approval_card for Chat inline confirm UI (Wave 2)."""
    from app.application.workflow.approval_card import build_approval_card_payload

    enriched = dict(inner)
    enriched["approval_card"] = build_approval_card_payload(action=action, inner=inner)
    return enriched
