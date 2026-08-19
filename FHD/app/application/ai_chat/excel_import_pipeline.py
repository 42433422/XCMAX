# ruff: noqa: E402, F401
"""Excel import pipeline mixin for AIChatExcelImportMixin."""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from app.application.ai_chat.excel_import_policy import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
    _EXCEL_IMPORT_QTY_MEASURE_RE,
    _enrich_confirmation_inner,
)
from app.application.chat_tool_intent import looks_like_explicit_workflow_tool_intent

logger = logging.getLogger(__name__)

from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin01 import (
    _AIChatExcelImportMixinPart01Mixin,
)
from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin02 import (
    _AIChatExcelImportMixinPart02Mixin,
)
from app.application.ai_chat.excel_import_pipeline_aichatexcelimportmixin_mixin03 import (
    _AIChatExcelImportMixinPart03Mixin,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS


class AIChatExcelImportMixin(_AIChatExcelImportMixinPart01Mixin, _AIChatExcelImportMixinPart02Mixin, _AIChatExcelImportMixinPart03Mixin):
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















