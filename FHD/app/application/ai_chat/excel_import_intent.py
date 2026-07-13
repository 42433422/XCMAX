"""Intent predicates selecting Excel and workflow paths."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ExcelImportIntentMatcher:
    @staticmethod
    def _excel_analysis_payload_present(context: dict[str, Any] | None) -> bool:
        """请求里是否带有可用的 excel_analysis（与 extract-grid 结构一致）。"""
        ea = (context or {}).get("excel_analysis") if isinstance(context, dict) else None
        if not isinstance(ea, dict) or not ea:
            return False
        if str(ea.get("summary") or "").strip():
            return True
        fields = ea.get("fields")
        if isinstance(fields, list) and len(fields) > 0:
            return True
        pd = ea.get("preview_data") if isinstance(ea.get("preview_data"), dict) else {}
        if isinstance(pd.get("sample_rows"), list) and len(pd.get("sample_rows")) > 0:
            return True
        grid = (pd.get("grid_preview") or {}).get("rows") if isinstance(pd, dict) else None
        return isinstance(grid, list) and len(grid) >= 2

    @staticmethod
    def _looks_like_short_excel_import_command(text: str) -> bool:
        """
        用户常用短指令（如「加入数据库」）。无 excel_analysis 时若落入 DeepSeek / planner 会长时间无响应。
        """
        t = str(text or "").strip()
        if not t:
            return False
        exact = {
            "加入数据库",
            "加入库",
            "入库",
            "添加到库",
            "写入数据库",
            "导入数据库",
        }
        if t in exact:
            return True
        if len(t) > 40:
            return False
        return any(
            k in t
            for k in (
                "加入数据库",
                "导入数据库",
                "添加到库",
                "写入数据库",
            )
        )

    @staticmethod
    def _looks_like_explicit_workflow_tool_intent(text: str) -> bool:
        t = str(text or "").strip()
        if not t:
            return False
        lower = t.lower()
        employee_mentioned = any(k in t for k in ("员工", "调用", "交给")) or "employee" in lower
        employee_action = any(k in t for k in ("调用", "执行", "运行", "交给", "让")) or any(
            k in lower for k in ("call", "run", "execute", "employee")
        )
        if employee_mentioned and employee_action:
            return True

        db_mentioned = (
            any(k in t for k in ("数据库", "查库", "读库", "写库"))
            or "database" in lower
            or bool(re.search(r"\bdb\b", lower))
        )
        if not db_mentioned:
            return False
        db_object = any(k in t for k in ("客户", "单位", "产品", "物料", "原材料", "发货", "出货"))
        db_action = any(
            k in t
            for k in (
                "查",
                "读",
                "读取",
                "写",
                "写入",
                "新增",
                "添加",
                "创建",
                "更新",
                "删除",
            )
        ) or any(k in lower for k in ("read", "query", "write", "create", "update", "delete"))
        return db_object and db_action

    @staticmethod
    def _looks_like_smart_workflow_intent(text: str, context: dict[str, Any] | None = None) -> bool:
        """Whether a non-pro chat turn should be allowed into executable planning.

        This keeps casual chat on the lightweight path, but lets ordinary
        desktop/mobile chat use the same agentic tool routing as pro mode for
        concrete tool/data/employee/file requests.
        """
        t = str(text or "").strip()
        if not t:
            return False
        if ExcelImportIntentMatcher._looks_like_explicit_workflow_tool_intent(t):
            return True

        ctx = context if isinstance(context, dict) else {}
        for key in (
            "excel_analysis",
            "file_analysis",
            "file_context",
            "multimodal_attachments",
            "attachments",
            "files",
            "artifacts",
            "ocr",
            "ocr_result",
            "excel_index_id",
            "excel_vector_index_id",
        ):
            if ctx.get(key):
                return True

        lower = t.lower()
        controlled_db = any(
            k in t
            for k in (
                "数据库",
                "查库",
                "读库",
                "写库",
                "业务库",
                "产品库",
                "客户库",
                "物料库",
                "原材料",
                "发货记录",
                "出货记录",
            )
        ) or any(k in lower for k in ("database", " db ", "business_db", "products table"))
        controlled_action = any(
            k in t
            for k in (
                "查",
                "查询",
                "读取",
                "统计",
                "多少",
                "几条",
                "列出",
                "新增",
                "添加",
                "写入",
                "更新",
                "删除",
                "导入",
                "入库",
            )
        ) or any(k in lower for k in ("read", "query", "count", "list", "write", "update"))
        if controlled_db and controlled_action:
            return True

        employee_request = any(k in t for k in ("员工", "超级员工", "调用", "交给", "执行")) or any(
            k in lower for k in ("employee", "agent", "run", "execute")
        )
        if employee_request and any(k in t for k in ("员工", "超级员工", "调用", "交给")):
            return True

        return False


__all__ = ["ExcelImportIntentMatcher"]
