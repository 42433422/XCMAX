"""AI 聊天应用服务 — re-export shim (split into ai_chat/)."""

from __future__ import annotations

import httpx as httpx

from app.application.workflow import HybridRiskGate as HybridRiskGate
from app.application.workflow import LLMWorkflowPlanner as LLMWorkflowPlanner
from app.application.workflow import WorkflowEngine as WorkflowEngine
from app.application.workflow import get_approval_service as get_approval_service
from app.services import get_ai_conversation_service as get_ai_conversation_service

from .ai_chat.helpers import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS as _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
)
from .ai_chat.helpers import (
    _EXCEL_IMPORT_QTY_MEASURE_RE as _EXCEL_IMPORT_QTY_MEASURE_RE,
)
from .ai_chat.helpers import (
    _enrich_confirmation_inner as _enrich_confirmation_inner,
)
from .ai_chat.helpers import (
    _skip_pro_excel_deterministic_import as _skip_pro_excel_deterministic_import,
)
from .ai_chat.service import AIChatApplicationService as AIChatApplicationService
from .ai_chat.service import get_ai_chat_app_service as get_ai_chat_app_service
