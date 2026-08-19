# ruff: noqa: E402, F401
"""
AI 聊天应用服务

编排 AI 聊天业务逻辑：
- 处理即时工具执行（products/customers/shipments/shipment_generate）
- 构建统一响应格式
- 处理确认流程

说明：专业版下若请求已带 excel_analysis 且用户话术中命中「导入/入库」等关键词，
``_try_handle_dynamic_workflow`` 可能走「规则映射 + 写库」捷径（见 ``import_pipeline``）。

**决策权**：默认由前端随请求附带 ``excel_import_ai_decides: true``，此时**不**走规则捷径，
入库映射与执行交给主对话 / Planner 与工具链（与「AI 拥有决策权」一致）。若需恢复极速规则入库，
可在设置中开启「Excel 入库走规则捷径」，或请求体 ``context.excel_import_use_deterministic_shortcut: true``。

服务端还可设 ``XCAGI_EXCEL_IMPORT_AI_DECIDES=1``（全局倾向 AI 路径）或
``XCAGI_DISABLE_PRO_EXCEL_IMPORT_SHORTCUT=1`` / ``context.excel_import_skip_deterministic_shortcut``（等价跳过捷径）。
"""

import asyncio
import copy
import json
import logging
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx  # noqa: F401 - compatibility patch point for legacy tests/callers

if TYPE_CHECKING:
    # 仅用于类型标注；运行时经注入端口或 ``app.bootstrap`` 触发式解析，避免 import 期耦合。
    from app.application.workflow.ports.checkpoint import CheckpointStore
    from app.application.workflow.ports.runtime import WorkflowRuntime
    from app.application.workflow.types import PlanGraph

from app.di.registry import get_service_registry
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import resolve_fhd_repo_root

logger = logging.getLogger(__name__)

from app.application.ai_chat.excel_import_pipeline import AIChatExcelImportMixin
from app.application.ai_chat.excel_import_policy import (
    _EXCEL_IMPORT_MEASURE_UNIT_TOKENS as _EXCEL_IMPORT_MEASURE_UNIT_TOKENS,
)
from app.application.ai_chat.excel_import_policy import (
    _enrich_confirmation_inner,
    _skip_pro_excel_deterministic_import,
)
from app.application.ai_chat.instant_tools import AIChatInstantToolsMixin
from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin


def _import_workflow_components():
    from app.application.workflow import (
        HybridRiskGate,
        LLMWorkflowPlanner,
        WorkflowEngine,
        get_approval_service,
    )

    return HybridRiskGate, LLMWorkflowPlanner, WorkflowEngine, get_approval_service


def _import_ai_conversation_service():
    from app.services import get_ai_conversation_service as _get

    return _get


def get_ai_conversation_service():
    """Lazy re-export so unit tests can patch this module attribute."""
    return _import_ai_conversation_service()()


# 单测通过 ``patch("app.application.ai_chat_app_service.LLMWorkflowPlanner")`` 等方式
# 替换工作流组件；这些符号不能在模块顶层 ``from app.application.workflow import``，
# 否则会重新引入与 ``app.application.workflow.planner`` 的循环 import（见 commit
# ed1f6e7e0）。PEP 562 模块级 ``__getattr__`` 在属性未在 ``__dict__`` 时才触发，
# 既能让 ``mock.patch`` 取到原始值，又不会在 import 期触发循环。
_LAZY_WORKFLOW_RE_EXPORTS = (
    "HybridRiskGate",
    "LLMWorkflowPlanner",
    "WorkflowEngine",
    "get_approval_service",
)


def __getattr__(name: str):
    if name in _LAZY_WORKFLOW_RE_EXPORTS:
        HybridRiskGate, LLMWorkflowPlanner, WorkflowEngine, get_approval_service = (
            _import_workflow_components()
        )
        globals().update(
            HybridRiskGate=HybridRiskGate,
            LLMWorkflowPlanner=LLMWorkflowPlanner,
            WorkflowEngine=WorkflowEngine,
            get_approval_service=get_approval_service,
        )
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


from app.application.ai_chat_app_service_aichatapplicationservice_mixin01 import (
    _AIChatApplicationServicePart01Mixin,
)
from app.application.ai_chat_app_service_aichatapplicationservice_mixin02 import (
    _AIChatApplicationServicePart02Mixin,
)
from app.application.ai_chat_app_service_aichatapplicationservice_mixin03 import (
    _AIChatApplicationServicePart03Mixin,
)


class AIChatApplicationService(_AIChatApplicationServicePart01Mixin, _AIChatApplicationServicePart02Mixin, _AIChatApplicationServicePart03Mixin, AIChatExcelImportMixin, AIChatWorkflowResponseMixin, AIChatInstantToolsMixin):
    """
    AI 聊天应用服务

    编排 AI 对话和即时工具执行，负责：
    - 聊天主流程处理
    - 即时工具执行（source=pro 和普通模式）
    - 响应格式构建
    """











    _HEADER_HINT_RE = re.compile(
        r"(产品|名称|规格|型号|编号|单价|价格|调价|金额|单位|客户|厂名|品名)"
    )





















def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
