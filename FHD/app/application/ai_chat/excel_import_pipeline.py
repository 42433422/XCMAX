"""Excel import pipeline mixin for AIChatExcelImportMixin（组装器：平级叶子 mixin 组合）。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.application.ai_chat.excel_import_pipeline_agent_run import ExcelImportAgentRunMixin
from app.application.ai_chat.excel_import_pipeline_columns_fallback import (
    ExcelImportColumnFallbackMixin,
)
from app.application.ai_chat.excel_import_pipeline_columns_infer import (
    ExcelImportColumnInferMixin,
)
from app.application.ai_chat.excel_import_pipeline_extract import ExcelImportExtractMixin
from app.application.ai_chat.excel_import_pipeline_resolve import ExcelImportResolveMixin


class AIChatExcelImportMixin(
    ExcelImportResolveMixin,
    ExcelImportColumnFallbackMixin,
    ExcelImportColumnInferMixin,
    ExcelImportExtractMixin,
    ExcelImportAgentRunMixin,
):
    if TYPE_CHECKING:
        _is_number_text: Any
        _merge_tool_runtime_context: Any
        _pending_workflows: Any
        _row_values_look_like_table_headers: Any
        ai_service: Any

        def _format_agent_run_response(
            self,
            plan: Any,
            agent_run: Any,
            thinking_steps: str = "",
            user_message: str = "",
        ) -> dict[str, Any]:
            raise NotImplementedError

    _PACK_OR_MEASURE_RE = re.compile(
        r"^\s*\d+(\.\d+)?\s*[/／]\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|桶|箱|组|套|升|L|l)?\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨)\s*[/／]\s*(桶|箱|组|套|包|袋|罐|个|只)\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨|桶|箱|包|袋|罐|套|组|个|只|张|米|㎡|cm|CM|mm|MM)\s*$"
        r"|^\s*(桶|箱|包|袋|罐|套|组|个|只|张|升|公斤|千克|斤)\s*$",
        re.I,
    )
