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
import json
import logging
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, cast

import httpx

from app.application.workflow import (
    HybridRiskGate,
    LLMWorkflowPlanner,
    WorkflowEngine,
    get_approval_service,
)
from app.di.registry import get_service_registry
from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

logger = logging.getLogger(__name__)


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


class AIChatApplicationService:
    """
    AI 聊天应用服务

    编排 AI 对话和即时工具执行，负责：
    - 聊天主流程处理
    - 即时工具执行（source=pro 和普通模式）
    - 响应格式构建
    """

    def __init__(self):
        self.ai_service = get_ai_conversation_service()
        self.workflow_planner = LLMWorkflowPlanner()
        self.risk_gate = HybridRiskGate()
        self.workflow_engine = WorkflowEngine(tool_dispatcher=self._dispatch_workflow_tool)
        self.approval_service = get_approval_service()
        self._pending_workflows: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _is_pro_source(source: str | None) -> bool:
        """兼容 pro 来源字段的多种写法（与 fastapi_routes.ai_chat._is_pro_source 对齐）。"""
        normalized = str(source or "").strip().lower().replace("-", "_")
        return normalized in {
            "pro",
            "pro_mode",
            "promode",
            "professional",
            "xcagi_pro",
        }

    @staticmethod
    def _merge_tool_runtime_context(
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime_ctx: dict[str, Any] = {"user_id": user_id, "message": message}
        if isinstance(context, dict):
            for key in ("ui_surface", "intent_channel", "tool_execution_profile"):
                if key in context and context[key] is not None:
                    runtime_ctx[key] = context[key]
            # 透传 Excel 分析上下文，支持自然语言按 sheet 入模板库
            for key in ("excel_analysis", "last_excel_analysis_context"):
                if key in context and isinstance(context[key], dict):
                    runtime_ctx[key] = context[key]
        return runtime_ctx

    def process_chat(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any] | None = None,
        source: str | None = None,
        file_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        处理聊天请求

        Args:
            user_id: 用户 ID
            message: 用户消息
            context: 额外上下文
            source: 来源标识（pro 表示专业模式）
            file_context: 文件上下文（用于确认流程）

        Returns:
            处理结果字典
        """
        if not message:
            return {
                "success": False,
                "message": "消息内容不能为空",
            }

        try:
            from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_received

            neuro_notify_chat_received(user_id, message, source)
        except RECOVERABLE_ERRORS:
            logger.debug("neuro_notify_chat_received skipped", exc_info=True)

        ctx = context or {}
        # Excel 向量：须在 _try_handle_dynamic_workflow 之前注入，否则「规则导入捷径」提前 return 时永远不会检索索引。
        ctx = self._inject_excel_vector_context(message=message, context=dict(ctx))

        def _finalize(resp: dict[str, Any]) -> dict[str, Any]:
            try:
                from app.neuro_bus.application_neuro_bridge import neuro_notify_chat_completed

                neuro_notify_chat_completed(user_id, message, resp)
            except RECOVERABLE_ERRORS:
                logger.debug("neuro_notify_chat_completed skipped", exc_info=True)
            try:
                self._persist_chat_turn(user_id, message, ctx, resp)
            except RECOVERABLE_ERRORS as persist_err:
                logger.warning("会话落库失败（已返回对话结果）: %s", persist_err)

            return resp

        self._handle_confirmation_flow(user_id, message, file_context)
        workflow_result = self._try_handle_dynamic_workflow(
            user_id=user_id,
            message=message,
            source=source,
            context=ctx,
            file_context=file_context or {},
        )
        if workflow_result is not None:
            return _finalize(workflow_result)

        enriched_context = dict(ctx)
        if isinstance(file_context, dict):
            excel_file_path = file_context.get("file_path") or file_context.get(
                "original_file_path"
            )
            if excel_file_path:
                excel_analysis_obj = {
                    "file_path": str(excel_file_path).strip(),
                }
                sheet_name = file_context.get("sheet_name")
                if sheet_name:
                    excel_analysis_obj["sheet_name"] = str(sheet_name).strip()
                enriched_context["excel_analysis"] = excel_analysis_obj

        # 向量已在 ctx 上注入；enriched_context 由 ctx 浅拷贝而来，无需再次检索。
        prepared_context = enriched_context

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            ai_result = loop.run_until_complete(
                self.ai_service.chat(user_id, message, prepared_context, source=source)
            )
        except ConnectionError as conn_err:
            logger.error("AI 服务连接失败：%s", conn_err)
            loop.close()
            return _finalize(
                self._build_fallback_response(
                    message, "AI 服务连接失败，可能是网络问题或服务未启动"
                )
            )
        except TimeoutError as timeout_err:
            logger.error("AI 服务请求超时：%s", timeout_err)
            loop.close()
            return _finalize(self._build_fallback_response(message, "AI 服务响应超时，请稍后重试"))
        except RECOVERABLE_ERRORS as e:
            logger.error("AI 服务处理异常：%s", e, exc_info=True)
            loop.close()
            error_msg = str(e)
            if "api_key" in error_msg.lower() or "apikey" in error_msg.lower():
                return _finalize(
                    self._build_fallback_response(
                        message, "AI 服务 API Key 未配置或无效，请联系管理员"
                    )
                )
            elif "connection" in error_msg.lower():
                return _finalize(
                    self._build_fallback_response(message, "无法连接到 AI 服务，请检查网络设置")
                )
            else:
                return _finalize(
                    self._build_fallback_response(message, f"AI 服务暂时不可用：{error_msg[:100]}")
                )
        finally:
            loop.close()

        logger.info(
            "用户 %s 消息：%s... -> %s", user_id, message[:50], ai_result.get("action", "unknown")
        )

        response_data = self._build_response(ai_result, source, message)

        return _finalize(response_data)

    def _persist_chat_turn(
        self,
        user_id: str,
        message: str,
        context: dict[str, Any],
        response_data: dict[str, Any],
    ) -> None:
        """
        在请求携带 session_id / conversation_id 时，将会话与工具结果摘要写入 ai_conversations，
        便于审计与和出货/产品等业务联动检索。
        """
        session_id = str(context.get("session_id") or context.get("conversation_id") or "").strip()
        if not session_id:
            return

        from app.services import get_conversation_service

        inner = response_data.get("data") if isinstance(response_data.get("data"), dict) else {}
        inner_payload = inner.get("data") if isinstance(inner.get("data"), dict) else {}
        tool_call = (
            response_data.get("toolCall") if isinstance(response_data.get("toolCall"), dict) else {}
        )
        intent = str(
            inner_payload.get("intent")
            or inner_payload.get("tool_key")
            or tool_call.get("tool_id")
            or inner.get("action")
            or "",
        ).strip()

        summary = {
            "success": bool(response_data.get("success")),
            "action": inner.get("action"),
            "intent": intent,
            "toolCall": tool_call or None,
            "plan_id": inner_payload.get("plan_id"),
            "document": (
                (inner_payload.get("document") or {}).get("doc_name")
                if isinstance(inner_payload.get("document"), dict)
                else None
            ),
            "excel_import": (
                inner_payload.get("result")
                if inner_payload.get("intent") == "excel_import_to_db"
                else None
            ),
        }

        meta_user = json.dumps({"role_hint": "user", "summary": summary}, ensure_ascii=False)[
            :12000
        ]
        meta_assistant = json.dumps(
            {"role_hint": "assistant", "summary": summary}, ensure_ascii=False
        )[:12000]

        conv = get_conversation_service()
        conv.save_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=str(message)[:8000],
            intent=intent or "chat",
            metadata=meta_user,
        )
        reply = str(response_data.get("response") or inner.get("text") or "")[:8000]
        conv.save_message(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=reply,
            intent=intent or "assistant_reply",
            metadata=meta_assistant,
        )

    def _inject_excel_vector_context(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        若请求携带 excel_index_id，则做一次语义检索并将结果写入 excel_vector_context。
        与 context 中已有的 excel_analysis（专用 extract-grid 等）可同时存在，二者一并进入下游提示词。

        注意：本方法在 process_chat 中会先于 _try_handle_dynamic_workflow 调用，以便规则导入捷径
        也能携带 excel_vector_context（供日志/后续扩展；当前列映射仍以 extract-grid 与字段索引为主）。
        若未传 excel_index_id / excel_vector_index_id，则不会检索（前端需在聊天 context 中带上建索引返回的 id）。
        """
        if not isinstance(context, dict):
            return {}

        excel_index_id = str(
            context.get("excel_index_id") or context.get("excel_vector_index_id") or ""
        ).strip()
        if not excel_index_id:
            return context

        top_k_raw = context.get("excel_top_k", 5)
        try:
            top_k = int(top_k_raw)
        except RECOVERABLE_ERRORS:
            top_k = 5

        try:
            from app.application import get_excel_vector_search_app_service

            search_service = get_excel_vector_search_app_service()
            result = search_service.query(
                index_id=excel_index_id,
                query_text=message,
                top_k=top_k,
            )
            if result.get("success"):
                enriched = dict(context)
                enriched["excel_vector_context"] = {
                    "index_id": excel_index_id,
                    "query": message,
                    "hits": result.get("hits", []),
                }
                return enriched
        except RECOVERABLE_ERRORS as err:
            logger.warning("注入 Excel 向量上下文失败: %s", err, exc_info=True)

        return context

    @staticmethod
    def _build_fallback_response(message: str, error_reason: str) -> dict[str, Any]:
        """
        构建 AI 服务不可用时的降级响应。

        当 AI 服务（LLM API、意图识别等）出现异常时，
        返回友好的错误提示，而不是让用户看到技术性错误信息。
        """
        text = (message or "").strip().lower()

        fallback_responses = {
            "greeting": "您好！我是 XCAGI 智能助手。😊\n\n⚠️ 当前 AI 服务暂时不可用，但我仍可以帮您：\n• 生成发货单\n• 查询产品库\n• 管理客户信息\n\n请尝试使用上述功能，或稍后再试。",
            "default": f"抱歉，AI 助手暂时无法为您提供智能回复。\n\n原因：{error_reason}\n\n您可以：\n1. 稍后重试\n2. 使用其他功能（如产品查询、生成发货单）\n3. 联系管理员检查服务状态",
        }

        if any(k in text for k in ("你好", "您好", "hi", "hello", "嗨")):
            response_text = fallback_responses["greeting"]
        else:
            response_text = fallback_responses["default"]

        return {
            "success": False,
            "message": error_reason,
            "response": response_text,
            "data": {
                "text": response_text,
                "action": "error_fallback",
                "data": {
                    "error_reason": error_reason,
                    "original_message": message[:100],
                    "fallback_mode": True,
                },
            },
        }

    @staticmethod
    def _is_number_text(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        try:
            float(text.replace(",", ""))
            return True
        except RECOVERABLE_ERRORS:
            return False

    _HEADER_HINT_RE = re.compile(
        r"(产品|名称|规格|型号|编号|单价|价格|调价|金额|单位|客户|厂名|品名)"
    )

    @classmethod
    def _row_values_look_like_table_headers(cls, values: list[str]) -> bool:
        non_empty = [v for v in values if str(v or "").strip()]
        if len(non_empty) < 2:
            return False
        hits = sum(1 for v in non_empty if cls._HEADER_HINT_RE.search(str(v)))
        return hits >= 2 and hits >= max(2, len(non_empty) // 3)

    @staticmethod
    def _resolve_excel_path_for_import(
        excel_analysis: dict[str, Any], preview_data: dict[str, Any]
    ) -> str:
        fp = str(excel_analysis.get("file_path") or "").strip()
        if not fp and isinstance(preview_data, dict):
            fp = str(preview_data.get("file_path") or "").strip()
        return fp

    @staticmethod
    def _customer_hint_from_preview_grid(preview_data: dict[str, Any]) -> str:
        """与前端网格预览一致：从 grid_preview.rows[].text 解析抬头里的客户名（合并单元格常见）。"""
        if not isinstance(preview_data, dict):
            return ""
        gp = preview_data.get("grid_preview")
        if not isinstance(gp, dict):
            return ""
        grid_rows = gp.get("rows")
        if not isinstance(grid_rows, list):
            return ""
        try:
            from app.application.template_grid_core import _extract_inline_customer_hits_from_cell
        except RECOVERABLE_ERRORS:
            return ""
        for row in grid_rows[:22]:
            if not isinstance(row, list):
                continue
            parts: list[str] = []
            for cell in row:
                if not isinstance(cell, dict):
                    continue
                t = str(cell.get("text") or "").strip()
                if not t:
                    continue
                hits = _extract_inline_customer_hits_from_cell(t)
                if hits:
                    return hits[0]
                parts.append(t)
            joined = " ".join(parts).strip()
            if joined:
                hits = _extract_inline_customer_hits_from_cell(joined)
                if hits:
                    return hits[0]
        return ""

    @staticmethod
    def _excel_cell_looks_like_product_measure_unit(value: Any) -> bool:
        """单元格是否为 SKU 计量单位（非客户全称），用于入库时避免把「件」当成客户。"""
        t = str(value or "").strip()
        if not t:
            return False
        if t.lower() in _EXCEL_IMPORT_MEASURE_UNIT_TOKENS:
            return True
        return bool(_EXCEL_IMPORT_QTY_MEASURE_RE.match(t))

    @staticmethod
    def _default_purchase_unit_for_import(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> str:
        """
        默认客户：优先读表内「客户」类标签与标题区公司名；文档没有时再退回文件名推断。
        """
        logger.debug(
            "[导入调试] _default_purchase_unit_for_import 开始, request_context type: %s",
            type(request_context).__name__,
        )
        if isinstance(request_context, dict):
            hint = str(request_context.get("excel_customer_hint") or "").strip()
            logger.debug("[导入调试] request_context.excel_customer_hint = %s", repr(hint))
            if hint:
                return hint
        if isinstance(preview_data, dict):
            hint = str(
                preview_data.get("customer_hint")
                or preview_data.get("document_customer")
                or excel_analysis.get("customer_hint")
                or ""
            ).strip()
            logger.debug("[导入调试] preview_data/excel_analysis customer_hint = %s", repr(hint))
            if hint:
                return hint
        grid_hint = AIChatApplicationService._customer_hint_from_preview_grid(preview_data)
        if grid_hint:
            return grid_hint
        fp = AIChatApplicationService._resolve_excel_path_for_import(excel_analysis, preview_data)
        sheet = AIChatApplicationService._resolve_sheet_name_for_reimport(
            excel_analysis, preview_data, request_context
        )
        if fp:
            path = Path(fp)
            if path.is_file():
                try:
                    from app.application.template_grid_core import _extract_customer_hint_from_excel

                    doc_unit = str(
                        _extract_customer_hint_from_excel(str(path), sheet) or ""
                    ).strip()
                    if doc_unit:
                        return doc_unit
                except RECOVERABLE_ERRORS as err:
                    logger.debug("从工作簿读取客户提示失败: %s", err)
        return AIChatApplicationService._guess_default_purchase_unit(excel_analysis)

    @staticmethod
    def _guess_default_purchase_unit(excel_analysis: dict[str, Any]) -> str:
        """
        仅作兜底：报价类文件无表内客户信息时，用文件名猜测公司名。
        """
        name = str(
            excel_analysis.get("file_name") or excel_analysis.get("template_name") or ""
        ).strip()
        fp = str(excel_analysis.get("file_path") or "").strip()
        if not name and fp:
            name = Path(fp).name
        stem = Path(name).stem if name else ""
        stem = str(stem).strip()
        if not stem:
            return ""
        stem = re.sub(r"\d{2,4}年?$", "", stem).strip()
        for token in ("产品报价表", "报价表", "报价单", "价格表", "产品报价", "报价"):
            if stem.endswith(token):
                stem = stem[: -len(token)].strip()
        m = re.search(
            r"(.+?(?:有限公司|股份有限公司|集团有限公司|实业有限公司|科技公司|集团公司|公司|厂|店))",
            stem,
        )
        if m:
            return m.group(1).strip()
        return stem if len(stem) >= 2 else ""

    @staticmethod
    def _sanitize_import_scalar(val: Any) -> Any:
        """pandas/openpyxl 空值与 nan，避免参与字段推断时出现字面量 'nan'。"""
        if val is None:
            return None
        if isinstance(val, float) and math.isnan(val):
            return None
        if isinstance(val, str):
            s = val.strip()
            if s.lower() in ("nan", "none", "nat", "<na>", "null"):
                return None
            return s
        try:
            fv = float(val)
            if fv != fv:
                return None
        except (TypeError, ValueError):
            pass
        return val

    @staticmethod
    def _resolve_force_header_row_1based(
        excel_analysis: dict[str, Any], preview_data: dict[str, Any]
    ) -> int | None:
        """与前端 slim 上下文中的 grid_preview.header_row_index / tables[].header_row 对齐。"""
        pd = preview_data if isinstance(preview_data, dict) else {}
        gp = pd.get("grid_preview") if isinstance(pd.get("grid_preview"), dict) else {}
        for key in ("header_row_index",):
            raw = gp.get(key)
            if raw is not None:
                try:
                    n = int(raw)
                    if n >= 1:
                        return n
                except (TypeError, ValueError):
                    pass
        tables = pd.get("tables")
        if isinstance(tables, list):
            for t in tables:
                if not isinstance(t, dict):
                    continue
                raw = t.get("header_row")
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        sheets = (
            excel_analysis.get("sheets") if isinstance(excel_analysis.get("sheets"), list) else None
        )
        if sheets:
            for s in sheets:
                if not isinstance(s, dict):
                    continue
                st = s.get("tables")
                if isinstance(st, list):
                    for t in st:
                        if not isinstance(t, dict):
                            continue
                        raw = t.get("header_row")
                        if raw is not None:
                            try:
                                n = int(raw)
                                if n >= 1:
                                    return n
                            except (TypeError, ValueError):
                                pass
                sg = s.get("grid_preview") if isinstance(s.get("grid_preview"), dict) else {}
                raw = sg.get("header_row_index")
                if raw is not None:
                    try:
                        n = int(raw)
                        if n >= 1:
                            return n
                    except (TypeError, ValueError):
                        pass
        return None

    @staticmethod
    def _resolve_sheet_name_for_reimport(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> str | None:
        if isinstance(request_context, dict):
            sel = request_context.get("excel_analysis_selected_sheet")
            if isinstance(sel, dict):
                sn = str(sel.get("sheet_name") or "").strip()
                if sn:
                    return sn
            ps = str(request_context.get("preferred_sheet_name") or "").strip()
            if ps:
                return ps
        if isinstance(preview_data, dict):
            for key in ("selected_sheet_name", "sheet_name"):
                v = preview_data.get(key)
                if v and str(v).strip():
                    return str(v).strip()
        sheets = (
            excel_analysis.get("sheets") if isinstance(excel_analysis.get("sheets"), list) else None
        )
        if sheets and isinstance(sheets[0], dict):
            sn = sheets[0].get("sheet_name")
            if sn and str(sn).strip():
                return str(sn).strip()
        return None

    @staticmethod
    def _try_structured_reload_records(
        excel_analysis: dict[str, Any],
        preview_data: dict[str, Any],
        request_context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | None:
        """
        聊天上下文里的 sample_rows 常来自 pandas（Unnamed 列）或已被截断；若服务器上仍有原文件，
        默认用 openpyxl 表头识别重读；若 preview_data.parse_mode 为 rectangular，则按矩形区域全读（列键 A/B/…），
        不再依赖推断的数据表头行。
        """
        fp = str(excel_analysis.get("file_path") or "").strip() or (
            str(preview_data.get("file_path") or "").strip()
            if isinstance(preview_data, dict)
            else ""
        )
        if not fp:
            return None
        path = Path(fp)
        if not path.is_file():
            return None
        sheet = AIChatApplicationService._resolve_sheet_name_for_reimport(
            excel_analysis, preview_data, request_context
        )
        force_hdr = AIChatApplicationService._resolve_force_header_row_1based(
            excel_analysis, preview_data
        )
        try:
            pd0 = preview_data if isinstance(preview_data, dict) else {}
            if str(pd0.get("parse_mode") or "").strip().lower() == "rectangular":
                from app.application.template_grid_core import _extract_rectangular_excel_preview

                structured = _extract_rectangular_excel_preview(str(path), sheet_name=sheet)
            else:
                from app.application.template_grid_core import _extract_structured_excel_preview

                structured = _extract_structured_excel_preview(
                    str(path),
                    sheet_name=sheet,
                    sample_limit=800,
                    force_header_row_1based=force_hdr,
                )
            rows = structured.get("sample_rows") or []
            if not isinstance(rows, list) or not rows:
                return None
            out: list[dict[str, Any]] = []
            for row in rows:
                if isinstance(row, dict):
                    out.append(
                        {
                            k: AIChatApplicationService._sanitize_import_scalar(v)
                            for k, v in row.items()
                        }
                    )
            return out or None
        except RECOVERABLE_ERRORS as err:
            logger.debug("结构化重读 Excel 跳过: %s", err)
            return None

    @staticmethod
    def _model_like_score(value: str) -> float:
        text = str(value or "").strip()
        if not text:
            return 0.0
        has_digit = any(ch.isdigit() for ch in text)
        has_alpha = any(ch.isalpha() for ch in text)
        compact = text.replace("-", "").replace("_", "")
        if len(compact) < 2 or len(compact) > 24:
            return 0.0
        if has_digit and has_alpha:
            return 1.0
        if has_digit and len(compact) <= 12:
            return 0.6
        return 0.0

    _PACK_OR_MEASURE_RE = re.compile(
        r"^\s*\d+(\.\d+)?\s*[/／]\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|桶|箱|组|套|升|L|l)?\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨)\s*[/／]\s*(桶|箱|组|套|包|袋|罐|个|只)\s*$"
        r"|^\s*\d+(\.\d+)?\s*(kg|KG|公斤|g|G|ml|ML|l|L|升|斤|吨|桶|箱|包|袋|罐|套|组|个|只|张|米|㎡|cm|CM|mm|MM)\s*$"
        r"|^\s*(桶|箱|包|袋|罐|套|组|个|只|张|升|公斤|千克|斤)\s*$",
        re.I,
    )

    @classmethod
    def _packaging_or_measure_ratio(cls, values: list[str]) -> float:
        """列取值多为包装规格/计量单位时接近 1（不应作为客户列）。"""
        nonempty = [str(v or "").strip() for v in values if str(v or "").strip()]
        if not nonempty:
            return 0.0
        hit = 0
        for v in nonempty:
            if cls._PACK_OR_MEASURE_RE.match(v):
                hit += 1
                continue
            if v in {
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
            }:
                hit += 1
        return hit / float(len(nonempty))

    @staticmethod
    def _header_hint_column_roles(keys: list[str]) -> dict[str, str]:
        """
        表头 → 客户/名称/型号/单价 四角色：词条来自 ``resources/config/ai_db_field_index.json`` 中
        ``products`` 各列的 ``excel_synonyms_zh`` / ``api_aliases``，可按业务增删而无需改 Python。
        """
        empty_roles = {
            "unit_name": "",
            "product_name": "",
            "model_number": "",
            "unit_price": "",
        }
        try:
            from app.services.ai_db_schema_index import match_excel_import_roles_from_field_index

            roles = cast("dict[str, str]", match_excel_import_roles_from_field_index(list(keys)))
        except RECOVERABLE_ERRORS as err:
            logger.debug("字段索引表头匹配失败，回退空映射: %s", err)
            roles = dict(empty_roles)

        roles = {**empty_roles, **dict(roles or {})}
        for key in keys:
            text = str(key or "").strip()
            normalized = re.sub(r"[\s:_：\-_/（）()]+", "", text).lower()
            if not normalized:
                continue
            if normalized in {
                "客户",
                "客户名",
                "客户名称",
                "客户全称",
                "购买单位",
                "购货单位",
                "单位名称",
                "公司",
                "公司名称",
                "厂名",
            }:
                roles["unit_name"] = text
                continue
            if normalized in {
                "产品",
                "产品名",
                "产品名称",
                "商品",
                "商品名称",
                "品名",
                "名称",
                "物料名称",
            }:
                roles["product_name"] = text
                continue
            if normalized in {"型号", "规格型号", "产品型号", "编码", "产品编码", "model", "sku"}:
                roles["model_number"] = text
                continue
            if normalized in {"单价", "价格", "产品单价", "销售单价", "报价", "unitprice", "price"}:
                roles["unit_price"] = text
        return roles

    def _fallback_excel_product_name_column(
        self,
        records: list[dict[str, Any]],
        reserved: set[str],
    ) -> str:
        """
        推断/LLM 未给出名称列时，从剩余列中选最像「产品描述」的一列，减轻聊天入库丢名称。
        """
        if not records or not isinstance(records[0], dict):
            return ""
        skip_re = re.compile(r"(序|序号|行号|单号|单据|^id$|^no\.?$)", re.I)
        best_col = ""
        best_score = -1.0
        min_nonempty = max(1, min(3, len(records) // 4))
        for key in records[0].keys():
            sk = str(key or "").strip()
            if not sk or sk in reserved:
                continue
            if skip_re.search(sk):
                continue
            values = [str((row or {}).get(sk) or "").strip() for row in records]
            nonempty = [v for v in values if v]
            if len(nonempty) < min_nonempty:
                continue
            if self._packaging_or_measure_ratio(nonempty) >= 0.45:
                continue
            num_ratio = sum(1 for v in nonempty if self._is_number_text(v)) / float(len(nonempty))
            avg_len = sum(len(v) for v in nonempty) / float(len(nonempty) or 1)
            score = (1.0 - num_ratio) * 0.5 + min(avg_len, 48.0) / 48.0 * 0.5
            if score > best_score:
                best_score = score
                best_col = sk
        return best_col if best_score >= 0.35 else ""

    def _fallback_excel_model_number_column(
        self,
        records: list[dict[str, Any]],
        reserved: set[str],
    ) -> str:
        """未识别型号列时，在剩余列上按型号样字符串得分选列，减轻丢型号。"""
        if not records or not isinstance(records[0], dict):
            return ""
        best_col = ""
        best_score = -1.0
        for key in records[0].keys():
            sk = str(key or "").strip()
            if not sk or sk in reserved:
                continue
            values = [str((row or {}).get(sk) or "").strip() for row in records]
            nonempty = [v for v in values if v]
            if not nonempty:
                continue
            mr = sum(self._model_like_score(v) for v in nonempty) / float(len(nonempty))
            if mr > best_score:
                best_score = mr
                best_col = sk
        return best_col if best_score >= 0.22 else ""

    def _infer_excel_column_roles(
        self, records: list[dict[str, Any]]
    ) -> tuple[dict[str, str], float]:
        if not records:
            return {}, 0.0
        keys = [k for k in records[0].keys() if str(k).strip()]
        if not keys:
            return {}, 0.0

        stats: dict[str, dict[str, float]] = {}
        for key in keys:
            values = [str((row or {}).get(key) or "").strip() for row in records]
            non_empty = [v for v in values if v]
            if not non_empty:
                continue
            count = float(len(non_empty))
            numeric_ratio = sum(1 for v in non_empty if self._is_number_text(v)) / count
            model_ratio = sum(self._model_like_score(v) for v in non_empty) / count
            unique_ratio = len(set(non_empty)) / count
            avg_len = sum(len(v) for v in non_empty) / count
            repeat_ratio = 1.0 - unique_ratio
            stats[key] = {
                "numeric_ratio": numeric_ratio,
                "model_ratio": model_ratio,
                "unique_ratio": unique_ratio,
                "avg_len": avg_len,
                "repeat_ratio": repeat_ratio,
            }

        if not stats:
            return {}, 0.0

        score_map = {
            "unit_price": lambda s: s["numeric_ratio"] * 0.9 + (1.0 - s["avg_len"] / 20.0) * 0.1,
            "model_number": lambda s: s["model_ratio"] * 0.8 + s["unique_ratio"] * 0.2,
            "unit_name": lambda s: (
                (1.0 - s["numeric_ratio"]) * 0.35
                + s["repeat_ratio"] * 0.5
                + (1.0 - min(s["avg_len"], 20.0) / 20.0) * 0.15
            ),
            "product_name": lambda s: (
                (1.0 - s["numeric_ratio"]) * 0.45
                + s["unique_ratio"] * 0.35
                + min(s["avg_len"], 30.0) / 30.0 * 0.2
            ),
        }

        ranked_by_role: dict[str, list[tuple[str, float]]] = {}
        for role, fn in score_map.items():
            ranked_by_role[role] = sorted(
                [(k, float(fn(v))) for k, v in stats.items()],
                key=lambda x: x[1],
                reverse=True,
            )

        # 避免角色冲突：如果推断冲突，优先保留最强语义的列，其他角色留空。
        used: set[str] = set()
        resolved: dict[str, str] = {}
        confidences: list[float] = []
        for role in ("unit_price", "model_number", "unit_name", "product_name"):
            ranked = ranked_by_role.get(role) or []
            key = str((ranked[0][0] if ranked else "") or "").strip()
            if key and key not in used:
                resolved[role] = key
                used.add(key)
                top_score = ranked[0][1] if ranked else 0.0
                next_score = ranked[1][1] if len(ranked) > 1 else 0.0
                # 置信度由绝对分和领先差共同决定
                role_conf = max(
                    0.0, min(1.0, top_score * 0.7 + max(0.0, top_score - next_score) * 0.3)
                )
                confidences.append(role_conf)
            else:
                resolved[role] = ""
                confidences.append(0.0)
        confidence = sum(confidences) / float(len(confidences) or 1)
        return resolved, confidence

    def _infer_excel_column_roles_with_llm(self, records: list[dict[str, Any]]) -> dict[str, str]:
        if not records:
            return {}
        try:
            from app.infrastructure.llm.providers.credentials import (
                default_chat_completions_url,
                resolve_default_chat_model,
                resolve_openai_env_credentials,
            )

            env_api_key, env_base_url = resolve_openai_env_credentials()
            api_key = str(getattr(self.ai_service, "api_key", "") or env_api_key or "").strip()
            api_url = str(getattr(self.ai_service, "api_url", "") or "").strip()
            if not api_url and env_base_url:
                api_url = f"{env_base_url.rstrip('/')}/chat/completions"
            api_url = api_url or default_chat_completions_url()
            model = str(getattr(self.ai_service, "model", "") or resolve_default_chat_model())
            if not api_key:
                return {}

            keys = [str(k).strip() for k in records[0].keys() if str(k).strip()]
            columns = []
            for key in keys[:30]:
                samples = []
                for row in records[:12]:
                    val = str((row or {}).get(key) or "").strip()
                    if val:
                        samples.append(val[:40])
                    if len(samples) >= 6:
                        break
                columns.append({"column": key, "samples": samples})

            prompt = {
                "task": "判断 Excel 列语义角色",
                "roles": ["unit_name", "product_name", "model_number", "unit_price"],
                "columns": columns,
                "rules": [
                    "只输出 JSON",
                    "每个角色映射一个列名，不确定时填空字符串",
                    "不要编造不存在的列名",
                    "若同时存在「调价前…价」与「调价后…价」两列，unit_price 必须二选一映射到其中一列；"
                    "若无法从列名判断业务应以哪个为准，则 unit_price 填空字符串",
                ],
                "output_schema": {
                    "unit_name": "column_name_or_empty",
                    "product_name": "column_name_or_empty",
                    "model_number": "column_name_or_empty",
                    "unit_price": "column_name_or_empty",
                },
            }
            resp = httpx.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "你是表格列语义识别器，只输出 JSON。"},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 300,
                },
                timeout=10.0,
            )
            if resp.status_code >= 400:
                return {}
            content = (
                ((resp.json().get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            ).strip()
            if not content:
                return {}
            content = (
                content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            )
            parsed = json.loads(content)
            roles = {}
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                key = str(parsed.get(role) or "").strip()
                roles[role] = key if key in keys else ""
            return roles
        except RECOVERABLE_ERRORS as err:
            logger.debug("LLM 列角色推断失败: %s", err)
            return {}

    @staticmethod
    def _price_column_buckets(keys: list[str]) -> tuple[list[str], list[str], list[str]]:
        """将列名划分为 调价前类 / 调价后类 / 其它价格类（词条与 ``ai_db_field_index.json`` 同步）。"""
        try:
            from app.services.ai_db_schema_index import price_column_buckets_for_keys

            return cast(
                "tuple[list[str], list[str], list[str]]", price_column_buckets_for_keys(list(keys))
            )
        except RECOVERABLE_ERRORS as err:
            logger.debug("价格列分桶失败，回退启发式: %s", err)
            before: list[str] = []
            after: list[str] = []
            generic: list[str] = []
            for raw in keys:
                cn = str(raw or "").strip()
                if not cn or "数量" in cn or "计量" in cn or "件数" in cn:
                    continue
                if not re.search(r"(单价|价格|报价|含税价|含税单价|金额)", cn):
                    continue
                if re.search(r"(调价\s*前|调价前|调整前|原价)", cn):
                    before.append(cn)
                elif re.search(r"(调价\s*后|调价后|折后|执行价|现用)", cn):
                    after.append(cn)
                else:
                    generic.append(cn)
            return before, after, generic

    @staticmethod
    def _merge_user_intent_for_price_resolution(
        user_message: str,
        request_context: dict[str, Any] | None,
    ) -> str:
        """
        合并「最近对话」与当前用户句，用于识别「调价前/后」单价列偏好。

        - 含 ``recent_messages`` 中 **user** 与 **assistant / ai**（前端气泡角色为 ``ai``）：
          否则助手已写「导入调价前数据」而用户只回「确认/导入」时，规则入库读不到承诺列。
        - 当前 ``user_message`` 放在 **末尾**，避免与历史中同一句重复时覆盖最新意图。
        """
        chunks: list[str] = []
        cur = str(user_message or "").strip()

        def _strip_htmlish(s: str) -> str:
            t = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
            return re.sub(r"<[^>]+>", "", t).strip()

        if isinstance(request_context, dict):
            rm = request_context.get("recent_messages")
            if isinstance(rm, list):
                for item in rm:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role") or "").strip().lower()
                    if role not in ("user", "assistant", "ai"):
                        continue
                    c = _strip_htmlish(str(item.get("content") or ""))
                    if not c or c in chunks:
                        continue
                    chunks.append(c)
            for k in ("message", "user_message"):
                extra = _strip_htmlish(str(request_context.get(k) or ""))
                if extra and extra not in chunks:
                    chunks.append(extra)
        cur_clean = _strip_htmlish(cur) if cur else ""
        if cur_clean:
            chunks.append(cur_clean)
        merged = "\n".join(chunks)
        if len(merged) > 8000:
            merged = merged[-8000:]
        return merged

    @staticmethod
    def _resolve_unit_price_column(
        keys: list[str],
        current: str,
        user_message: str,
        overrides: dict[str, Any] | None,
    ) -> tuple[str, str | None]:
        """
        结合列名与用户话术确定入库单价列。
        返回 (column_name, error_code)；error_code 为 ambiguous_price_columns 时应中止自动入库。
        user_message 建议传入 _merge_user_intent_for_price_resolution 的结果（含最近用户轮次）。
        """
        ov = overrides if isinstance(overrides, dict) else {}
        forced = str(ov.get("unit_price") or ov.get("price") or "").strip()
        if forced:
            for k in keys:
                if str(k).strip() == forced:
                    return str(k), None

        keyset = [str(k).strip() for k in keys if str(k).strip()]
        if not keyset:
            return "", None

        um = str(user_message or "").strip()
        before, after, generic = AIChatApplicationService._price_column_buckets(keyset)
        has_tension = bool(before and after)
        # 分桶漏检（表头含空格/异体等）时，只要键名上同时出现「调价前」「调价后」仍视为双价列，须话术或覆盖项
        if not has_tension:
            pres = [k for k in keyset if "调价前" in str(k).replace(" ", "")]
            posts = [k for k in keyset if "调价后" in str(k).replace(" ", "")]
            if pres and posts:
                has_tension = True

        def _first(opts: list[str]) -> str:
            return str(opts[0]).strip() if opts else ""

        # 长句里「导入 …（文件名/说明）… 调价前」可能远超 12 字距，放宽窗口并允许跨行
        _gap = r"[\s\S]{0,360}?"
        prefer_before = bool(
            re.search(
                rf"(用|取|要|导入|写入|入库){_gap}调价\s*前|调价\s*前{_gap}(?:价|单价|列|数据)|"
                rf"价格{_gap}调价\s*前|单价{_gap}调价\s*前|"
                rf"(?:按|以|采用|使用|选用|取){_gap}调价\s*前",
                um,
                re.I,
            )
        )
        prefer_after = bool(
            re.search(
                rf"(用|取|要|导入|写入|入库){_gap}调价\s*后|调价\s*后{_gap}(?:价|单价|列|数据)|"
                rf"价格{_gap}调价\s*后|单价{_gap}调价\s*后|"
                rf"(?:按|以|采用|使用|选用|取){_gap}调价\s*后",
                um,
                re.I,
            )
        )
        # 整段话里仅出现一侧字样时的强提示（助手整段说明常用）
        if "调价前" in um and "调价后" not in um:
            prefer_before = True
        if "调价后" in um and "调价前" not in um:
            prefer_after = True

        if has_tension:
            if prefer_before and not prefer_after:
                return _first(before), None
            if prefer_after and not prefer_before:
                return _first(after), None
            if prefer_before and prefer_after:
                return "", "ambiguous_price_columns"
            # 未从话术判断时：报价类表格默认以「调价前」为入库单价（与 import_excel_to_database 工具侧一致）
            return _first(before), None

        cur = str(current or "").strip()
        if cur and cur in keyset:
            return cur, None
        if before and not after:
            return _first(before), None
        if after and not before:
            return _first(after), None
        if generic:
            if len(generic) == 1:
                return generic[0], None
            if cur and cur in generic:
                return cur, None
            if len(generic) >= 2:
                return "", "ambiguous_price_columns"
        return "", None

    def _extract_excel_import_records(
        self,
        excel_analysis: dict[str, Any],
        request_context: dict[str, Any] | None = None,
        *,
        user_message: str = "",
    ) -> tuple[list[dict[str, Any]], str | None]:
        preview_data = (
            excel_analysis.get("preview_data")
            if isinstance(excel_analysis.get("preview_data"), dict)
            else {}
        )
        preview_data = preview_data or {}
        records: list[dict[str, Any]] = []

        reloaded = self._try_structured_reload_records(
            excel_analysis, preview_data, request_context
        )
        if reloaded:
            records = reloaded
        else:
            sample_rows = preview_data.get("sample_rows") or []
            if isinstance(sample_rows, list):
                for row in sample_rows:
                    if isinstance(row, dict):
                        records.append(dict(row))

            grid_rows = (preview_data.get("grid_preview") or {}).get("rows") or []
            if isinstance(grid_rows, list) and len(grid_rows) >= 2:
                header = grid_rows[0]
                if isinstance(header, list):
                    header_keys = [str(h or "").strip() for h in header]
                    for row in grid_rows[1:]:
                        if not isinstance(row, list):
                            continue
                        item: dict[str, Any] = {}
                        for idx, key in enumerate(header_keys):
                            if not key:
                                continue
                            item[key] = row[idx] if idx < len(row) else None
                        if any(str(v or "").strip() for v in item.values()):
                            records.append(item)

        # 某些表格第一行是“真实表头”，但被解析为数据行（键名为 Unnamed:*）
        if records:
            first = records[0]
            if isinstance(first, dict):
                keys = list(first.keys())
                key_unnamed_ratio = 0.0
                if keys:
                    unnamed_count = sum(1 for k in keys if str(k).startswith("Unnamed:"))
                    key_unnamed_ratio = unnamed_count / len(keys)
                header_values = [str(first.get(k) or "").strip() for k in keys]
                label_like_ratio = sum(
                    1 for v in header_values if v and not self._is_number_text(v)
                ) / float(len(header_values) or 1)
                headerish = self._row_values_look_like_table_headers(header_values)
                should_promote = len(records) >= 2 and (
                    (key_unnamed_ratio >= 0.5 and label_like_ratio >= 0.5)
                    or (key_unnamed_ratio >= 0.35 and headerish)
                )
                if should_promote:
                    rebuilt: list[dict[str, Any]] = []
                    for row in records[1:]:
                        if not isinstance(row, dict):
                            continue
                        mapped: dict[str, Any] = {}
                        for idx, key in enumerate(keys):
                            header = header_values[idx] if idx < len(header_values) else ""
                            if not header:
                                continue
                            mapped[header] = row.get(key)
                        if any(str(v or "").strip() for v in mapped.values()):
                            rebuilt.append(mapped)
                    if rebuilt:
                        records = rebuilt

        records = [
            (
                {k: AIChatApplicationService._sanitize_import_scalar(v) for k, v in r.items()}
                if isinstance(r, dict)
                else r
            )
            for r in records
        ]

        if not records:
            return [], None

        inferred_roles, role_conf = self._infer_excel_column_roles(records)
        if role_conf < 0.55:
            llm_roles = self._infer_excel_column_roles_with_llm(records)
            # 低置信度时优先采用 LLM 非空结果，空值回退特征推断
            for role in ("unit_name", "product_name", "model_number", "unit_price"):
                if llm_roles.get(role):
                    inferred_roles[role] = llm_roles[role]

        header_roles = AIChatApplicationService._header_hint_column_roles(
            [str(k).strip() for k in records[0].keys()] if records else []
        )
        for role in ("unit_name", "product_name", "model_number", "unit_price"):
            hk = str(header_roles.get(role) or "").strip()
            if hk:
                inferred_roles[role] = hk

        keys = [str(k).strip() for k in records[0].keys() if str(k).strip()]
        merged_intent = AIChatApplicationService._merge_user_intent_for_price_resolution(
            user_message, request_context
        )
        overrides = (
            request_context.get("excel_import_column_overrides")
            if isinstance(request_context, dict)
            else None
        )
        cur_price = str(inferred_roles.get("unit_price") or "").strip()
        price_col, price_err = AIChatApplicationService._resolve_unit_price_column(
            keys, cur_price, merged_intent, overrides if isinstance(overrides, dict) else {}
        )
        if price_err:
            return [], price_err
        inferred_roles["unit_price"] = price_col

        unit_key = inferred_roles.get("unit_name", "")
        product_key = inferred_roles.get("product_name", "")
        model_key = inferred_roles.get("model_number", "")
        price_key = inferred_roles.get("unit_price", "")

        default_unit = self._default_purchase_unit_for_import(
            excel_analysis, preview_data, request_context
        )
        logger.debug(
            "[导入调试] _default_purchase_unit_for_import 返回: %s (request_context keys: %s)",
            repr(default_unit),
            (
                list(request_context.keys())
                if isinstance(request_context, dict)
                else type(request_context).__name__
            ),
        )
        if unit_key:
            col_vals = [str((row or {}).get(unit_key) or "").strip() for row in records]
            if AIChatApplicationService._packaging_or_measure_ratio(col_vals) >= 0.45:
                unit_key = ""
        if unit_key and unit_key == product_key:
            unit_key = ""
        if unit_key and product_key and unit_key == model_key:
            unit_key = ""

        reserved_cols = {c for c in (unit_key, product_key, model_key, price_key) if c}
        if not product_key:
            fb_name = self._fallback_excel_product_name_column(records, reserved_cols)
            if fb_name:
                product_key = fb_name
                reserved_cols.add(fb_name)
        if not model_key:
            fb_model = self._fallback_excel_model_number_column(records, reserved_cols)
            if fb_model:
                model_key = fb_model

        dedup: set[tuple[str, str, str]] = set()
        normalized: list[dict[str, Any]] = []
        for row in records:
            unit_name = str((row or {}).get(unit_key) or "").strip() if unit_key else ""
            if (
                not unit_name
                and default_unit
                or (
                    default_unit
                    and unit_name
                    and AIChatApplicationService._excel_cell_looks_like_product_measure_unit(
                        unit_name
                    )
                )
            ):
                unit_name = default_unit.strip()
            product_name = str((row or {}).get(product_key) or "").strip() if product_key else ""
            model_number = (
                str((row or {}).get(model_key) or "").strip().upper() if model_key else ""
            )
            price_text = str((row or {}).get(price_key) or "").strip() if price_key else ""
            try:
                unit_price = float(price_text) if price_text else 0.0
            except RECOVERABLE_ERRORS:
                unit_price = 0.0
            if not unit_name:
                continue
            if not product_name and not model_number:
                continue
            dedup_key = (unit_name, product_name, model_number)
            if dedup_key in dedup:
                continue
            dedup.add(dedup_key)
            normalized.append(
                {
                    "unit_name": unit_name,
                    "product_name": product_name or model_number,
                    "model_number": model_number,
                    "unit_price": unit_price,
                }
            )
        return normalized, None

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
    def _attach_deterministic_workflow_trace(
        payload: dict[str, Any],
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any] | None,
        intent: str,
        file_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            from app.application.agent_orchestrator.chat_trace import attach_chat_trace_run
        except RECOVERABLE_ERRORS:
            logger.exception("AgentRun 追踪模块不可用，跳过 deterministic workflow trace")
            return payload

        runtime_context = dict(context or {}) if isinstance(context, dict) else {}
        runtime_context["workflow_intent"] = intent
        runtime_context["workflow_trace_mode"] = "deterministic_shortcut"
        if isinstance(file_context, dict) and file_context:
            runtime_context["file_context"] = file_context
        return attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel="deterministic_workflow",
            intent=intent,
        )

    def _start_deterministic_import_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any] | None,
        file_context: dict[str, Any] | None,
        plan,
        thinking_steps: str,
    ) -> dict[str, Any]:
        from app.application.agent_orchestrator import AgentOrchestrator

        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["deterministic_workflow"] = True
        if isinstance(file_context, dict) and file_context:
            runtime_ctx["file_context"] = dict(file_context)

        agent_run = AgentOrchestrator().start_run_from_plan(
            user_id=user_id,
            message=message,
            plan=plan,
            runtime_context=runtime_ctx,
            auto_execute=True,
        )
        if agent_run.status != "waiting_user":
            return self._format_agent_run_response(
                plan,
                agent_run,
                thinking_steps=thinking_steps,
                user_message=str(message or ""),
            )

        blocking_nodes = [step.node_id for step in agent_run.steps if step.status == "waiting_user"]
        artifact_payloads = [
            artifact.to_dict() for artifact in getattr(agent_run, "artifacts", []) or []
        ]
        self._pending_workflows[user_id] = {
            "plan": plan,
            "runtime_context": runtime_ctx,
            "pending_id": uuid.uuid4().hex,
            "agent_run_id": agent_run.run_id,
            "thinking_steps": thinking_steps,
            "approval_required": False,
            "approval_nodes": [],
        }
        todo_text = "\n".join(f"- {step}" for step in (getattr(plan, "todo_steps", None) or []))
        response_text = (
            "我已生成导入工作流计划：\n"
            f"{thinking_steps}\n\n"
            f"{todo_text}\n\n"
            f"检测到写库步骤（{', '.join(blocking_nodes) or 'import'}），"
            "回复「确认」继续执行，回复「取消」终止。"
        )
        return {
            "success": True,
            "message": "处理完成",
            "response": response_text,
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "data": {
                "text": response_text,
                "action": "workflow_confirmation_required",
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "plan_id": plan.plan_id,
                    "intent": plan.intent,
                    "thinking_steps": thinking_steps,
                    "todo": plan.todo_steps,
                    "artifact_count": len(artifact_payloads),
                    "artifacts": artifact_payloads,
                    "blocking_nodes": blocking_nodes,
                    "reason": "导入会写入业务数据库，需确认后执行",
                    "approval_required": False,
                    "approval_nodes": [],
                },
            },
        }

    def _try_handle_dynamic_workflow(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        file_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        text = str(message or "").strip()
        if not text:
            return None
        explicit_workflow_tool_intent = self._looks_like_explicit_workflow_tool_intent(text)
        has_pending_workflow = user_id in self._pending_workflows
        if (
            not self._is_pro_source(source)
            and not explicit_workflow_tool_intent
            and not has_pending_workflow
        ):
            return None

        merged_file_ctx = {}
        if isinstance(context, dict):
            merged_file_ctx.update(context.get("file_analysis") or {})
            merged_file_ctx.update(context.get("file_context") or {})
        if isinstance(file_context, dict):
            merged_file_ctx.update(file_context)

        import_intent = any(k in text for k in ("导入", "入库", "添加到数据库", "写入数据库"))
        if import_intent and (merged_file_ctx.get("suggested_use") == "unit_products_db"):
            saved_name = str(merged_file_ctx.get("saved_name") or "").strip()
            unit_name = str(
                merged_file_ctx.get("unit_name") or merged_file_ctx.get("unit_name_guess") or ""
            ).strip()
            if not saved_name:
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": "已识别导入意图，但缺少源文件上下文。请先上传并分析 .db 文件。",
                    "data": {"text": "请先上传并分析 .db 文件。", "action": "followup", "data": {}},
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="import_unit_products_db",
                )
            if not unit_name:
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": "已识别导入意图，请补充客户名称后继续导入。",
                    "data": {
                        "text": "请补充客户名称后继续导入。",
                        "action": "followup",
                        "data": {"missing_fields": ["unit_name"]},
                    },
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="import_unit_products_db",
                )

            todo_lines = [
                "检查客户是否存在，不存在则自动创建",
                "读取源库 products 表并映射字段",
                "按单位+型号/名称去重后导入产品",
                "返回导入结果（新增/跳过/失败）",
            ]
            from app.application.workflow.types import PlanGraph, WorkflowNode

            plan = PlanGraph(
                plan_id=f"plan_unit_products_import_{uuid.uuid4().hex[:12]}",
                intent="import_unit_products_db",
                todo_steps=todo_lines,
                nodes=[
                    WorkflowNode(
                        node_id="import_unit_products",
                        tool_id="unit_products_import",
                        action="execute_import",
                        params={
                            "saved_name": saved_name,
                            "unit_name": unit_name,
                            "create_purchase_unit": True,
                            "skip_duplicates": True,
                        },
                        risk="medium",
                        idempotent=False,
                        description="从已分析 .db 文件导入单位和产品",
                    )
                ],
                risk_level="medium",
                metadata={
                    "source": "deterministic_file_import",
                    "artifacts": [
                        {
                            "artifact_type": "database_file",
                            "name": saved_name,
                            "source": "file_analysis",
                            "summary": f"unit_products_db 导入源文件，目标客户：{unit_name}",
                            "fields": [
                                {"name": "saved_name", "value": saved_name},
                                {"name": "unit_name", "value": unit_name},
                                {
                                    "name": "suggested_use",
                                    "value": merged_file_ctx.get("suggested_use"),
                                },
                            ],
                            "metadata": {
                                "suggested_use": merged_file_ctx.get("suggested_use"),
                                "unit_name_guess": merged_file_ctx.get("unit_name_guess"),
                            },
                        }
                    ],
                },
            )
            thinking_steps = self._build_workflow_thinking_steps(
                plan,
                "unit_products 导入会写入客户和产品数据库，需用户确认",
            )
            return self._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                plan=plan,
                thinking_steps=thinking_steps,
            )

        # 无分析结果时短指令勿走 LLM（混合 normal 画像下否则会长时间阻塞在 DeepSeek）
        if (
            not self._excel_analysis_payload_present(context)
            and self._looks_like_short_excel_import_command(text)
            and not explicit_workflow_tool_intent
        ):
            payload = {
                "success": True,
                "message": "处理完成",
                "response": (
                    "未检测到 Excel 分析上下文。请先点击工具栏「分析 Excel」上传并分析表格，再发送「加入数据库」等指令。\n"
                    "若已分析过，可能是会话切换或页面刷新导致上下文丢失——请重新分析一次。"
                ),
                "data": {
                    "text": "未检测到 Excel 分析上下文，请先分析 Excel。",
                    "action": "followup",
                    "data": {"intent": "excel_import_missing_context"},
                },
            }
            return self._attach_deterministic_workflow_trace(
                payload,
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                intent="excel_import_missing_context",
            )

        # 下列分支为「规则入库捷径」：关键词 + excel_analysis 即写库，不经过本轮主对话模型的端到端推理。
        # 默认由前端 context.excel_import_ai_decides 跳过本分支，改走主链路使模型/Planner 拥有入库决策权。
        excel_analysis = (
            (context or {}).get("excel_analysis") if isinstance(context, dict) else None
        )
        if (
            isinstance(excel_analysis, dict)
            and any(k in text for k in ("数据库", "入库", "导入", "添加到库"))
            and not _skip_pro_excel_deterministic_import(context)
        ):
            fields = excel_analysis.get("fields") or []
            field_names = []
            for item in fields[:10]:
                if isinstance(item, dict):
                    field_names.append(str(item.get("label") or item.get("name") or "").strip())
                else:
                    field_names.append(str(item).strip())
            field_names = [x for x in field_names if x]
            summary = str(excel_analysis.get("summary") or "").strip()
            todo_lines = [
                "解析 Excel 数据并映射单位/产品/型号/价格字段",
                "检查客户是否存在，不存在则创建",
                "检查产品是否存在，缺失则创建并绑定单位",
                "返回导入结果（新增单位/新增产品/跳过重复）",
            ]
            records, extract_err = self._extract_excel_import_records(
                excel_analysis, context, user_message=text
            )
            if extract_err == "ambiguous_price_columns":
                cols_preview = "、".join(field_names[:24]) if field_names else "（见上文字段列表）"
                followup_text = (
                    "已检测到多个「价格」相关列（例如同时存在「调价前…价」与「调价后…价」），"
                    "为避免入错库，已暂停自动写入。\n"
                    "请在下一条消息中明确指定，例如：「导入数据库，价格用调价前列」或「…单价取调价后那一列」。\n"
                    f"当前识别到的部分列名：{cols_preview}"
                )
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": followup_text,
                    "data": {
                        "text": followup_text,
                        "action": "followup",
                        "data": {
                            "intent": "excel_import_to_db",
                            "import_pipeline": "deterministic_shortcut",
                            "import_pipeline_zh": "服务端规则入库（非本轮大模型端到端决策）",
                            "thinking_steps": "价格列存在歧义，需用户明确选用调价前或调价后",
                            "todo": todo_lines,
                            "blocked_reason": extract_err,
                        },
                    },
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="excel_import_to_db",
                )
            if not records:
                followup_text = (
                    "我已读取到 Excel 上下文，但未解析到可入库的单位/产品记录。\n"
                    f"已识别字段: {'、'.join(field_names) if field_names else '未识别到字段'}"
                )
                if summary:
                    followup_text += f"\n上下文摘要:\n{summary[:500]}"
                payload = {
                    "success": True,
                    "message": "处理完成",
                    "response": followup_text,
                    "data": {
                        "text": followup_text,
                        "action": "followup",
                        "data": {
                            "intent": "excel_import_to_db",
                            "import_pipeline": "deterministic_shortcut",
                            "import_pipeline_zh": "服务端规则入库（非本轮大模型端到端决策）",
                            "thinking_steps": "已完成字段识别，但记录提取为空",
                            "todo": todo_lines,
                        },
                    },
                }
                return self._attach_deterministic_workflow_trace(
                    payload,
                    user_id=user_id,
                    message=message,
                    source=source,
                    context=context,
                    file_context=merged_file_ctx,
                    intent="excel_import_to_db",
                )

            from app.application.workflow.types import PlanGraph, WorkflowNode

            plan = PlanGraph(
                plan_id=f"plan_excel_import_{uuid.uuid4().hex[:12]}",
                intent="excel_import_to_db",
                todo_steps=todo_lines,
                nodes=[
                    WorkflowNode(
                        node_id="import_excel_records",
                        tool_id="excel_import",
                        action="import_records",
                        params={
                            "records": records,
                            "source": "deterministic_shortcut",
                        },
                        risk="medium",
                        idempotent=False,
                        description="将 Excel 解析记录写入客户和产品数据库",
                    )
                ],
                risk_level="medium",
                metadata={
                    "source": "deterministic_excel_import",
                    "artifacts": [
                        {
                            "artifact_type": "excel_records",
                            "name": str(
                                excel_analysis.get("file_name")
                                or excel_analysis.get("template_name")
                                or "excel_import_records"
                            ),
                            "source": "excel_analysis",
                            "uri": str(excel_analysis.get("file_path") or ""),
                            "summary": summary or f"Excel 入库记录 {len(records)} 条",
                            "fields": [
                                {"name": name}
                                for name in field_names[:40]
                                if str(name or "").strip()
                            ],
                            "preview": {
                                "record_count": len(records),
                                "sample_records": records[:3],
                            },
                            "metadata": {
                                "import_pipeline": "deterministic_shortcut",
                                "sheet_name": excel_analysis.get("sheet_name"),
                            },
                        }
                    ],
                },
            )
            thinking_steps = self._build_workflow_thinking_steps(
                plan,
                "Excel 入库会写入客户和产品数据库，需用户确认",
            )
            return self._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                plan=plan,
                thinking_steps=thinking_steps,
            )

        from app.application.normal_chat_dispatch import (
            build_customers_query_response_dict,
            build_inventory_alert_response_dict,
            build_label_print_response_dict,
            build_product_query_response_dict,
            resolve_tool_execution_profile,
            route_normal_mode_message,
            run_normal_slot_shipment_preview,
        )

        profile = resolve_tool_execution_profile(context if isinstance(context, dict) else {})
        if profile == "normal" and not explicit_workflow_tool_intent:
            rr = route_normal_mode_message(text)
            if rr.get("intent") == "product_query":
                pq = build_product_query_response_dict(rr)
                if pq:
                    return pq
            if rr.get("intent") == "shipment":
                ship = run_normal_slot_shipment_preview(text)
                if ship.get("success"):
                    ship.pop("normal_slot_dispatch", None)
                    return ship
            if rr.get("intent") == "customers_query":
                cq = build_customers_query_response_dict(rr)
                if cq:
                    return cq
            if rr.get("intent") == "inventory_alert":
                ia = build_inventory_alert_response_dict(rr)
                if ia:
                    return ia
            if rr.get("intent") == "label_print":
                lp = build_label_print_response_dict(rr)
                if lp:
                    return lp
            if rr.get("intent") == "price_list":
                customer_name_match = re.search(
                    r"([^\s，,。]{2,}(?:有限公司|集团有限公司|实业有限公司|公司\s|单位|客户|厂|店))",
                    text,
                )
                keyword_match = re.search(r"[的的]\s*([^\s，,。]+)", text)
                slots = {}
                if customer_name_match:
                    slots["customer_name"] = customer_name_match.group(1)
                if keyword_match:
                    slots["keyword"] = keyword_match.group(1)

                if not slots.get("customer_name"):
                    return {
                        "success": False,
                        "message": "缺少客户名称",
                        "response": "请告诉我您要生成哪家客户的价格表？例如：「打印某某公司的价格表」",
                    }

                # 直接调用价格表生成 API，而不是返回 tool_call
                try:
                    fhd_root = resolve_fhd_repo_root(anchor=Path(__file__).resolve())
                    from app.application.tools import handle_price_list_export

                    logger.info("价格表生成 - FHD根目录: %s", fhd_root)

                    result = handle_price_list_export(
                        {
                            "customer_name": slots.get("customer_name", ""),
                            "keyword": slots.get("keyword"),
                            "export_date": None,
                        },
                        workspace_root=str(fhd_root) if fhd_root else None,
                    )

                    logger.info("价格表生成结果: %s", result)

                    if result.get("success"):
                        product_count = len(result.get("products", []))
                        file_path = result.get("file_path", "")
                        filename = (
                            file_path.split("/")[-1].split("\\")[-1] if file_path else "价格表.docx"
                        )

                        return {
                            "success": True,
                            "message": result.get("message", "价格表已生成"),
                            "response": f"好的，价格表已生成成功！\n\n{result.get('message', '')}\n\n📄 文件名：{filename}\n💡 已在右侧任务面板中添加下载和打印按钮。",
                            "data": {
                                "file_path": file_path,
                                "download_url": result.get("download_url"),
                                "filename": filename,
                                "product_count": product_count,
                                "intent": "price_list",
                                "action": "tool_call",
                                "tool_key": "price_list",
                            },
                        }
                    else:
                        return {
                            "success": False,
                            "message": result.get("error", "价格表生成失败"),
                            "response": f"抱歉，价格表生成失败：{result.get('error', '未知错误')}",
                        }
                except RECOVERABLE_ERRORS as e:
                    logger.error("价格表生成异常：%s", e, exc_info=True)
                    return {
                        "success": False,
                        "message": f"价格表生成异常：{str(e)}",
                        "response": f"抱歉，价格表生成时出现错误：{str(e)}",
                    }

        # 处理混合模式下的确认/取消
        pending = self._pending_workflows.get(user_id)
        if pending:
            confirm_words = {"确认", "是", "好的", "继续", "执行", "ok", "yes"}
            cancel_words = {"取消", "否", "不要", "停止", "no"}
            if text.lower() in confirm_words or text in confirm_words:
                plan = pending.get("plan")
                runtime_ctx = pending.get("runtime_context", {})
                approval_required = pending.get("approval_required", False)
                approval_nodes = pending.get("approval_nodes", [])

                if approval_required and approval_nodes:
                    for node_info in approval_nodes:
                        node = None
                        for n in plan.nodes:
                            if n.node_id == node_info.get("node_id"):
                                node = n
                                break
                        if node:
                            self.approval_service.create_approval_request(
                                plan_id=plan.plan_id,
                                node=node,
                                runtime_context=runtime_ctx,
                                plan=plan,
                            )

                    return {
                        "success": True,
                        "message": "处理完成",
                        "response": "已提交审批请求，请等待审批完成后继续。",
                        "data": {
                            "text": "已提交审批请求，请等待审批完成后继续。",
                            "action": "approval_pending",
                            "data": {
                                "plan_id": plan.plan_id,
                                "approval_required": True,
                                "approval_nodes": approval_nodes,
                            },
                        },
                    }

                agent_run_id = str(pending.get("agent_run_id") or "").strip()
                if agent_run_id:
                    from app.application.agent_orchestrator import AgentOrchestrator

                    agent_run = AgentOrchestrator().continue_run(
                        agent_run_id,
                        approved_by=user_id,
                        runtime_context=runtime_ctx,
                    )
                    self._pending_workflows.pop(user_id, None)
                    if agent_run is not None:
                        return self._format_agent_run_response(
                            plan,
                            agent_run,
                            thinking_steps=str(pending.get("thinking_steps") or ""),
                            user_message=str(runtime_ctx.get("message") or ""),
                        )

                run_result = self.workflow_engine.run(
                    plan=plan, runtime_context=runtime_ctx, max_retries=1
                )
                self._pending_workflows.pop(user_id, None)
                return self._format_workflow_run_response(
                    plan,
                    run_result,
                    user_message=str(runtime_ctx.get("message") or ""),
                )
            if text.lower() in cancel_words or text in cancel_words:
                self._pending_workflows.pop(user_id, None)
                return {
                    "success": True,
                    "message": "处理完成",
                    "response": "已取消本次工作流执行。",
                    "data": {
                        "text": "已取消本次工作流执行。",
                        "action": "workflow_cancelled",
                        "data": {},
                    },
                }

        # 普通工具画像（含「普通界面 + 专业意图」）：未命中槽位时勿走 LLM 工作流规划，避免长时间阻塞在 plan()；
        # 交给下方主对话链路（DeepSeek 等），体验与普通聊天一致。
        if profile == "normal" and not explicit_workflow_tool_intent:
            return None

        # 专业界面默认画像：发货单/开单句式与普通版槽位路由一致时，勿让 LLM 工作流规划抢先返回
        # 「我已根据语义生成动态工作流计划…节点 products.query / products.create…」，
        # 否则 Jarvis 收不到主链路里的 shipment_generate / toolCall，用户只看到冗长计划文案。
        if profile == "pro_default":
            rr_pro_ship = route_normal_mode_message(text)
            if rr_pro_ship.get("intent") == "shipment":
                # 订单句若能被 _parse_order_text 结构化，直接下发 shipment_generate / toolCall，
                # 避免再走意图识别（槽位空→追问）或主模型只回文本导致前端从不调用 /api/tools/execute。
                try:
                    from app.application.facades.tools_facade import _parse_order_text

                    parsed_quick = _parse_order_text(text)
                except RECOVERABLE_ERRORS:
                    parsed_quick = {"success": False}
                if parsed_quick.get("success"):
                    # 结构与 _build_tool_call_response 一致，避免把多余键摊进 toolCall.params
                    quick_ai = {
                        "text": "已识别订单，正在生成发货单…",
                        "action": "tool_call",
                        "data": {
                            "tool_key": "shipment_generate",
                            "intent": "shipment_generate",
                            "slots": {
                                "unit_name": (parsed_quick.get("unit_name") or "").strip(),
                                "products": parsed_quick.get("products") or [],
                            },
                            "hints": [],
                            "habit_suggestion": None,
                        },
                    }
                    return self._build_response(quick_ai, source, text)
                return None

        # 动态规划：不依赖关键词硬编码决策
        from app.application.facades.tools_facade import get_workflow_tool_registry

        tool_registry = get_workflow_tool_registry()
        plan = self.workflow_planner.plan(
            user_id=user_id,
            message=message,
            tool_registry=tool_registry,
            context=context,
        )

        decision = self.risk_gate.evaluate(plan=plan, context=context)
        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx["source"] = str(source or "").strip()
        runtime_ctx["workflow_trace_mode"] = "agent_orchestrator"
        runtime_ctx["dynamic_workflow"] = True
        thinking_steps = self._build_workflow_thinking_steps(
            plan=plan, decision_reason=decision.reason
        )

        approval_required_nodes = self.approval_service.get_approval_required_nodes(plan)
        has_approval_requirement = bool(approval_required_nodes)
        approval_info = ""
        if has_approval_requirement:
            approval_node_names = [f"{n.tool_id}.{n.action}" for n in approval_required_nodes]
            approval_info = "\n以下操作需要审批后执行：" + "、".join(approval_node_names)

        use_agentic = bool((runtime_ctx.get("excel_analysis") or {}).get("file_path"))
        if not has_approval_requirement and not use_agentic:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self._format_agent_run_response(
                    plan,
                    agent_run,
                    thinking_steps=thinking_steps,
                    user_message=str(message or ""),
                )
            blocking_nodes = [
                step.node_id
                for step in getattr(agent_run, "steps", []) or []
                if step.status == "waiting_user"
            ]
            self._pending_workflows[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run.run_id,
                "thinking_steps": thinking_steps,
                "approval_required": False,
                "approval_nodes": [],
            }
            todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
            reason = decision.reason or "工具策略要求用户确认"
            response_text = (
                "我已根据语义生成动态工作流计划：\n"
                f"{thinking_steps}\n\n"
                f"{todo_text}\n\n"
                f"检测到需确认步骤（{', '.join(blocking_nodes) or 'workflow'}），"
                "回复「确认」继续执行，回复「取消」终止。"
            )
            return {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "data": {
                        "run_id": agent_run.run_id,
                        "agent_run_id": agent_run.run_id,
                        "plan_id": plan.plan_id,
                        "intent": plan.intent,
                        "thinking_steps": thinking_steps,
                        "todo": plan.todo_steps,
                        "blocking_nodes": blocking_nodes,
                        "reason": reason,
                        "approval_required": False,
                        "approval_nodes": [],
                    },
                },
            }

        agent_run_id = ""
        if decision.requires_confirmation and not has_approval_requirement:
            from app.application.agent_orchestrator import AgentOrchestrator

            agent_run = AgentOrchestrator().start_run_from_plan(
                user_id=user_id,
                message=message,
                plan=plan,
                runtime_context=runtime_ctx,
                auto_execute=True,
            )
            if agent_run.status != "waiting_user":
                return self._format_agent_run_response(
                    plan,
                    agent_run,
                    thinking_steps=thinking_steps,
                    user_message=str(message or ""),
                )
            agent_run_id = agent_run.run_id

        if decision.requires_confirmation or has_approval_requirement:
            self._pending_workflows[user_id] = {
                "plan": plan,
                "runtime_context": runtime_ctx,
                "pending_id": uuid.uuid4().hex,
                "agent_run_id": agent_run_id,
                "thinking_steps": thinking_steps,
                "approval_required": has_approval_requirement,
                "approval_nodes": [
                    {
                        "node_id": n.node_id,
                        "tool_id": n.tool_id,
                        "action": n.action,
                        "params": n.params,
                    }
                    for n in approval_required_nodes
                ],
            }
            todo_text = "\n".join(f"- {step}" for step in (plan.todo_steps or []))
            response_text = (
                "我已根据语义生成动态工作流计划：\n"
                f"{thinking_steps}\n\n"
                f"{todo_text}\n\n"
                f"检测到中高风险步骤（{', '.join(decision.blocking_nodes)}），"
                "回复「确认」继续执行，回复「取消」终止。"
                f"{approval_info if has_approval_requirement else ''}"
            )
            payload: dict[str, Any] = {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "data": {
                        "plan_id": plan.plan_id,
                        "intent": plan.intent,
                        "thinking_steps": thinking_steps,
                        "todo": plan.todo_steps,
                        "blocking_nodes": decision.blocking_nodes,
                        "reason": decision.reason,
                        "approval_required": has_approval_requirement,
                        "approval_nodes": [
                            {"node_id": n.node_id, "tool_id": n.tool_id, "action": n.action}
                            for n in approval_required_nodes
                        ],
                    },
                },
            }
            if agent_run_id:
                payload["run_id"] = agent_run_id
                payload["agent_run_id"] = agent_run_id
                payload["data"]["run_id"] = agent_run_id
                payload["data"]["agent_run_id"] = agent_run_id
                payload["data"]["data"]["run_id"] = agent_run_id
                payload["data"]["data"]["agent_run_id"] = agent_run_id
            return payload

        agentic_pre_run = None
        if use_agentic:
            try:
                agentic_pre_run = self._start_agentic_workflow_agent_run(
                    user_id=user_id,
                    message=message,
                    plan=plan,
                    runtime_context=runtime_ctx,
                )
                runtime_ctx["run_id"] = agentic_pre_run.run_id
                runtime_ctx["agent_run_id"] = agentic_pre_run.run_id
            except RECOVERABLE_ERRORS:
                logger.debug("Agentic workflow AgentRun pre-create skipped", exc_info=True)

        run_result = self.workflow_engine.run(
            plan=plan,
            runtime_context=runtime_ctx,
            max_retries=1,
            agentic_loop=use_agentic,
            tool_registry=tool_registry,
            user_id=user_id,
        )
        if use_agentic:
            agent_run = self._bridge_agentic_workflow_result_to_agent_run(
                user_id=user_id,
                message=message,
                plan=plan,
                run_result=run_result,
                runtime_context=runtime_ctx,
                agent_run=agentic_pre_run,
            )
            return self._format_agent_run_response(
                plan,
                agent_run,
                thinking_steps=thinking_steps,
                user_message=str(message or ""),
            )
        return self._format_workflow_run_response(
            plan,
            run_result,
            thinking_steps=thinking_steps,
            user_message=str(message or ""),
        )

    def _build_workflow_thinking_steps(self, plan, decision_reason: str) -> str:
        node_lines = []
        for node in plan.nodes or []:
            deps = ",".join(node.depends_on) if node.depends_on else "无"
            node_lines.append(
                f"- 节点 {node.node_id}: {node.tool_id}.{node.action} "
                f"(risk={node.risk}, depends_on={deps})"
            )
        nodes_text = "\n".join(node_lines) if node_lines else "- 无可执行节点"

        metadata = getattr(plan, "metadata", {}) or {}
        user_memory_rag_summary = str(metadata.get("user_memory_rag_summary") or "").strip()
        memory_v2_summary = str(metadata.get("memory_v2_summary") or "").strip()
        tool_probe_outputs = metadata.get("tool_probe_outputs") or []
        if not isinstance(tool_probe_outputs, list):
            tool_probe_outputs = []

        probe_lines = []
        for item in tool_probe_outputs[:3]:
            if not isinstance(item, dict):
                continue
            tid = str(item.get("tool_id") or "").strip()
            action = str(item.get("action") or "").strip()
            ok = bool(item.get("success"))
            msg = str(item.get("message") or "").strip()
            preview = str(item.get("data_preview") or "").strip()
            if preview:
                preview = preview[:220] + ("…" if len(preview) > 220 else "")
            probe_lines.append(f"- {tid}.{action}: success={ok}; {msg} {preview}".strip())

        memory_block = (
            f"3.5) 用户记忆 RAG 概览:\n{user_memory_rag_summary}\n"
            if user_memory_rag_summary
            else ""
        )
        memory_v2_block = (
            f"3.6) Memory v2 已确认记忆:\n{memory_v2_summary}\n" if memory_v2_summary else ""
        )
        probe_block = (
            "3.7) 工具探测概览:\n"
            + ("\n".join(probe_lines) if probe_lines else "- 无成功探测结果")
            + "\n"
        )
        return (
            "思考步骤:\n"
            f"1) 意图理解: {plan.intent}\n"
            "2) 计划生成: 基于工具注册表构建可执行节点图\n"
            f"3) 风险判断: {decision_reason}\n"
            f"{memory_block}{memory_v2_block}{probe_block}"
            "4) 执行编排: 按依赖顺序执行节点并传递上下文\n"
            f"5) 节点图:\n{nodes_text}"
        )

    def _workflow_products_float_query(self, plan, run_result, user_message: str) -> str:
        """从产品查询节点参数/结果或用户原话中提取副窗搜索词。"""
        for node in plan.nodes or []:
            if node.tool_id == "products" and node.action == "query":
                p = node.params or {}
                q = (
                    str(p.get("keyword") or "").strip()
                    or str(p.get("model_number") or "").strip()
                    or str(p.get("product_name") or p.get("name") or "").strip()
                )
                if q:
                    return q
        for r in run_result.node_results:
            if not r.success or r.tool_id != "products" or r.action != "query":
                continue
            out = r.output or {}
            rows = out.get("data") or []
            if isinstance(rows, list) and rows:
                row = rows[0] if isinstance(rows[0], dict) else {}
                if isinstance(row, dict):
                    m = str(row.get("model_number") or "").strip()
                    n = str(row.get("name") or row.get("product_name") or "").strip()
                    if m:
                        return m
                if n:
                    return n
        return str(user_message or "").strip()

    def _start_agentic_workflow_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        runtime_context: dict[str, Any],
    ):
        from app.application.agent_orchestrator.run_models import AgentRun
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository

        repository = get_agent_run_repository()
        run = AgentRun(
            user_id=str(user_id or ""),
            message=str(message or ""),
            status="running",
            plan_id=str(getattr(plan, "plan_id", "") or ""),
            intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
            metadata={
                "runtime_context": dict(runtime_context or {}),
                "trace_mode": "agentic_loop_bridge",
                "plan": {
                    "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                    "risk_level": str(getattr(plan, "risk_level", "") or ""),
                    "metadata": dict(getattr(plan, "metadata", {}) or {}),
                },
            },
        )
        run.add_event("run.created", "Agentic workflow run 已创建")
        run.add_event(
            "planner.completed",
            "Agentic workflow 计划已接管",
            {
                "plan_id": run.plan_id,
                "intent": run.intent,
                "source": "workflow_engine.agentic_loop",
            },
        )
        run.add_event(
            "agentic_loop.started",
            "Agentic workflow loop 开始执行",
            {"observed": True},
        )
        return repository.save(run)

    def _bridge_agentic_workflow_result_to_agent_run(
        self,
        *,
        user_id: str,
        message: str,
        plan,
        run_result,
        runtime_context: dict[str, Any],
        agent_run=None,
    ):
        from app.application.agent_orchestrator.run_models import (
            AgentRun,
            AgentStep,
            ToolCall,
            artifact_from_dict,
        )
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec

        repository = get_agent_run_repository()
        runtime_ctx = dict(runtime_context or {})
        run = agent_run
        if run is None:
            run = AgentRun(
                user_id=str(user_id or ""),
                message=str(message or ""),
                status="running",
                plan_id=str(getattr(plan, "plan_id", "") or ""),
                intent=str(getattr(plan, "intent", "") or "agentic_workflow"),
                metadata={
                    "runtime_context": dict(runtime_ctx),
                    "trace_mode": "agentic_loop_bridge",
                    "plan": {
                        "todo_steps": list(getattr(plan, "todo_steps", []) or []),
                        "risk_level": str(getattr(plan, "risk_level", "") or ""),
                        "metadata": dict(getattr(plan, "metadata", {}) or {}),
                    },
                },
            )
            run.add_event("run.created", "Agentic workflow run 已创建")
            run.add_event(
                "planner.completed",
                "Agentic workflow 计划已接管",
                {
                    "plan_id": run.plan_id,
                    "intent": run.intent,
                    "source": "workflow_engine.agentic_loop",
                },
            )
            run.add_event(
                "agentic_loop.started",
                "Agentic workflow loop 开始执行",
                {"observed": True},
            )
        run.metadata["runtime_context"] = dict(runtime_ctx)
        run.metadata["trace_mode"] = "agentic_loop_bridge"
        run.add_event(
            "agentic_loop.completed",
            str(getattr(run_result, "message", "") or "AgenticLoop 已完成"),
            {"observed": True},
        )

        node_outputs: dict[str, Any] = {}
        for result in getattr(run_result, "node_results", []) or []:
            spec = get_tool_action_spec(result.tool_id, result.action)
            status = "completed" if bool(getattr(result, "success", False)) else "failed"
            step = AgentStep(
                node_id=str(result.node_id or f"agent_{result.tool_id}_{result.action}"),
                tool_id=str(result.tool_id or ""),
                action=str(getattr(spec, "action", "") or result.action or ""),
                params=dict(getattr(result, "params", {}) or {}),
                risk=str(getattr(spec, "risk", "") or "medium"),
                idempotent=bool(getattr(spec, "idempotent", False)),
                description="agentic loop observed tool execution",
                status=status,
                output=dict(getattr(result, "output", {}) or {}),
                error=str(getattr(result, "error", "") or ""),
                started_at=str(getattr(result, "started_at", "") or ""),
                finished_at=str(getattr(result, "finished_at", "") or ""),
                duration_ms=int(getattr(result, "duration_ms", 0) or 0),
            )
            if status == "failed" and not step.error:
                step.error = self._workflow_output_message(step.output) or "tool failed"
            call = ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params or {}),
                status="completed" if status == "completed" else "failed",
                output=dict(step.output or {}),
                error=step.error,
                cost_units=int(getattr(spec, "cost_units", 0) or 0),
                permission=str(getattr(spec, "permission", "") or ""),
                started_at=step.started_at or "",
                finished_at=step.finished_at or "",
                duration_ms=step.duration_ms,
                metadata={
                    "observed": True,
                    "trace_mode": "agentic_loop_bridge",
                    "retryable": bool(getattr(result, "retryable", True)),
                    "retries": int(getattr(result, "retries", 0) or 0),
                    "recovery_hint": str(getattr(result, "recovery_hint", "") or ""),
                },
            )
            run.steps.append(step)
            run.tool_calls.append(call)
            node_outputs[step.node_id] = step.output
            run.add_event(
                "tool.started",
                f"观察到 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "cost_units": call.cost_units,
                    "permission": call.permission,
                    "observed": True,
                },
            )
            run.add_event(
                "tool.completed" if status == "completed" else "tool.failed",
                f"记录 agentic 工具 {step.tool_id}.{step.action}",
                {
                    "step_id": step.step_id,
                    "node_id": step.node_id,
                    "call_id": call.call_id,
                    "duration_ms": step.duration_ms,
                    "cost_units": call.cost_units,
                    "observed": True,
                    "error": step.error,
                },
            )
            for artifact_payload in self._iter_agentic_artifact_payloads(step.output):
                artifact = artifact_from_dict(artifact_payload)
                if not artifact.artifact_type:
                    continue
                artifact.source = artifact.source or f"{step.tool_id}.{step.action}"
                artifact.metadata = {
                    **dict(artifact.metadata or {}),
                    "step_id": step.step_id,
                    "call_id": call.call_id,
                    "trace_mode": "agentic_loop_bridge",
                }
                run.artifacts.append(artifact)
                run.add_event(
                    "artifact.attached",
                    f"Artifact 已附加: {artifact.artifact_type}",
                    {
                        "artifact_id": artifact.artifact_id,
                        "artifact_type": artifact.artifact_type,
                        "name": artifact.name,
                        "source": artifact.source,
                    },
                )

        cost_units_total = sum(int(call.cost_units or 0) for call in run.tool_calls)
        run.metadata["tool_call_count"] = len(run.tool_calls)
        run.metadata["cost_units_total"] = cost_units_total
        run.metadata["artifact_count"] = len(run.artifacts)
        run.final_output = {
            "node_outputs": node_outputs,
            "tool_calls": [call.to_dict() for call in run.tool_calls],
            "artifacts": [artifact.to_dict() for artifact in run.artifacts],
            "cost_units_total": cost_units_total,
            "workflow_result": {
                "success": bool(getattr(run_result, "success", False)),
                "message": str(getattr(run_result, "message", "") or ""),
                "workflow_status": dict(
                    (getattr(run_result, "final_context", {}) or {}).get("workflow_status") or {}
                ),
            },
        }
        run.status = "completed" if bool(getattr(run_result, "success", False)) else "failed"
        if run.status == "failed":
            run.error = str(getattr(run_result, "message", "") or "Agentic workflow failed")
            run.add_event("run.failed", run.error, run.final_output)
        else:
            run.add_event("run.completed", "Agentic workflow run 执行完成", run.final_output)
        return repository.save(run)

    @staticmethod
    def _iter_agentic_artifact_payloads(output: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(output, dict):
            return []
        artifacts = output.get("artifacts")
        if artifacts is None:
            artifacts = output.get("artifact")
        if isinstance(artifacts, dict):
            return [artifacts]
        if isinstance(artifacts, list):
            return [item for item in artifacts if isinstance(item, dict)]
        return []

    @staticmethod
    def _agent_plan_can_auto_execute(plan) -> bool:
        nodes = getattr(plan, "nodes", None)
        if not isinstance(nodes, (list, tuple)) or not nodes:
            return False
        try:
            from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        except RECOVERABLE_ERRORS:
            return False
        for node in nodes:
            spec = get_tool_action_spec(getattr(node, "tool_id", ""), getattr(node, "action", ""))
            risk = str(getattr(spec, "risk", "") or getattr(node, "risk", "") or "").lower()
            idempotent = bool(getattr(spec, "idempotent", getattr(node, "idempotent", False)))
            if risk != "low" or not idempotent:
                return False
        return True

    def _format_agent_run_response(
        self,
        plan,
        agent_run,
        thinking_steps: str = "",
        user_message: str = "",
    ) -> dict[str, Any]:
        lines = [
            f"工作流: {plan.intent}",
            f"计划ID: {plan.plan_id}",
            f"RunID: {agent_run.run_id}",
        ]
        if thinking_steps:
            lines.append(thinking_steps)
        if plan.todo_steps:
            lines.append("TODO:")
            lines.extend([f"- {x}" for x in plan.todo_steps])
        lines.append("执行结果:")

        node_params_by_id = {
            str(getattr(node, "node_id", "")): (getattr(node, "params", None) or {})
            for node in (getattr(plan, "nodes", None) or [])
        }
        for step in getattr(agent_run, "steps", []) or []:
            if step.status == "completed":
                item = type(
                    "AgentNodeResult",
                    (),
                    {
                        "node_id": step.node_id,
                        "success": True,
                        "tool_id": step.tool_id,
                        "action": step.action,
                        "output": step.output,
                        "error": "",
                    },
                )()
                lines.extend(
                    self._format_workflow_tool_success_line(
                        item,
                        node_params_by_id.get(str(step.node_id), {}),
                    )
                )
            else:
                lines.append(f"- {step.node_id}: {step.status}（{step.error or '未完成'}）")

        success = agent_run.status == "completed"
        cost_units_total = int((agent_run.metadata or {}).get("cost_units_total") or 0)
        tool_call_count = int((agent_run.metadata or {}).get("tool_call_count") or 0)
        artifact_payloads = [
            artifact.to_dict() for artifact in getattr(agent_run, "artifacts", []) or []
        ]
        if tool_call_count:
            lines.append(f"工具调用: {tool_call_count} 次，成本单位: {cost_units_total}")
        if artifact_payloads:
            lines.append(f"Artifacts: {len(artifact_payloads)} 个")
        response_text = "\n".join(lines)
        payload: dict[str, Any] = {
            "success": success,
            "message": "处理完成" if success else "处理失败",
            "response": response_text,
            "run_id": agent_run.run_id,
            "agent_run_id": agent_run.run_id,
            "data": {
                "text": response_text,
                "action": "workflow_done" if success else "workflow_failed",
                "run_id": agent_run.run_id,
                "agent_run_id": agent_run.run_id,
                "data": {
                    "run_id": agent_run.run_id,
                    "agent_run_id": agent_run.run_id,
                    "plan_id": plan.plan_id,
                    "intent": plan.intent,
                    "thinking_steps": thinking_steps,
                    "todo": plan.todo_steps,
                    "agent_status": agent_run.status,
                    "tool_call_count": tool_call_count,
                    "cost_units_total": cost_units_total,
                    "artifact_count": len(artifact_payloads),
                    "artifacts": artifact_payloads,
                    "tool_calls": [
                        {
                            "call_id": call.call_id,
                            "step_id": call.step_id,
                            "node_id": call.node_id,
                            "tool_id": call.tool_id,
                            "action": call.action,
                            "status": call.status,
                            "cost_units": call.cost_units,
                            "duration_ms": call.duration_ms,
                            "permission": call.permission,
                        }
                        for call in getattr(agent_run, "tool_calls", []) or []
                    ],
                    "node_results": [
                        {
                            "node_id": step.node_id,
                            "success": step.status == "completed",
                            "tool_id": step.tool_id,
                            "action": step.action,
                            "message": step.error or self._workflow_output_message(step.output),
                            "output_preview": self._workflow_output_preview(step.output),
                            "duration_ms": step.duration_ms,
                        }
                        for step in getattr(agent_run, "steps", []) or []
                    ],
                },
            },
        }
        if success and any(
            step.status == "completed" and step.tool_id == "products" and step.action == "query"
            for step in getattr(agent_run, "steps", []) or []
        ):
            payload["autoAction"] = {
                "type": "show_products_float",
                "feature": "products",
                "query": str(user_message or "").strip(),
            }
        return payload

    @staticmethod
    def _workflow_output_preview(output: Any, max_chars: int = 700) -> str:
        if output is None:
            return ""
        value = output
        if isinstance(output, dict):
            value = {
                k: v
                for k, v in output.items()
                if k
                in {
                    "success",
                    "message",
                    "error",
                    "employee_id",
                    "exists",
                    "created",
                    "unit_name",
                    "matched_count",
                    "redirect",
                }
            }
            data = output.get("data")
            if isinstance(data, list):
                value["row_count"] = len(data)
                value["rows"] = data[:5]
            elif isinstance(data, dict):
                value["data"] = {
                    k: v
                    for k, v in data.items()
                    if k
                    in {
                        "summary",
                        "result",
                        "error",
                        "success",
                        "registered_tool_count",
                        "available_employee_ids",
                    }
                } or str(data)[:260]
            elif data is not None:
                value["data"] = data
            raw = output.get("raw")
            if raw is not None and "data" not in value:
                value["raw"] = str(raw)[:260]
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
        text = text.strip()
        if len(text) > max_chars:
            return text[:max_chars] + "..."
        return text

    @staticmethod
    def _workflow_output_message(output: Any) -> str:
        if not isinstance(output, dict):
            return ""
        return str(output.get("message") or output.get("error") or "").strip()

    def _format_workflow_tool_success_line(
        self,
        item,
        node_params: dict[str, Any],
    ) -> list[str]:
        output = getattr(item, "output", None)
        out = output if isinstance(output, dict) else {}
        message = self._workflow_output_message(out)
        preview = self._workflow_output_preview(out)

        if item.tool_id == "employee":
            if item.action in ("list", "query"):
                data = out.get("data") if isinstance(out.get("data"), dict) else {}
                count = data.get("registered_tool_count", 0)
                line = f"- {item.node_id}: 成功（发现 {count} 个可调用员工）"
            else:
                employee_id = str(
                    out.get("employee_id") or node_params.get("employee_id") or "-"
                ).strip()
                suffix = f": {message}" if message else ""
                line = f"- {item.node_id}: 成功（员工 {employee_id}{suffix}）"
            return [line, f"    · 结果预览: {preview}"] if preview else [line]

        if item.tool_id == "business_db":
            entity = str(node_params.get("entity") or out.get("entity") or "-").strip()
            operation = str(node_params.get("operation") or item.action or "").strip()
            if item.action in ("read", "query", "list"):
                rows = out.get("data")
                count = len(rows) if isinstance(rows, list) else 0
                line = f"- {item.node_id}: 成功（{entity} 查询 {count} 条）"
            else:
                suffix = f": {message}" if message else ""
                line = f"- {item.node_id}: 成功（{entity}.{operation}{suffix}）"
            return [line, f"    · 结果预览: {preview}"] if preview else [line]

        if message:
            return [f"- {item.node_id}: 成功（{message}）"]
        return [f"- {item.node_id}: 成功"]

    def _format_workflow_run_response(
        self,
        plan,
        run_result,
        thinking_steps: str = "",
        user_message: str = "",
    ) -> dict[str, Any]:
        lines = [f"工作流: {plan.intent}", f"计划ID: {plan.plan_id}"]
        if thinking_steps:
            lines.append(thinking_steps)
        if plan.todo_steps:
            lines.append("TODO:")
            lines.extend([f"- {x}" for x in plan.todo_steps])
        lines.append("执行结果:")
        plan_nodes = getattr(plan, "nodes", None)
        if not isinstance(plan_nodes, (list, tuple)):
            plan_nodes = []
        node_params_by_id = {
            str(getattr(node, "node_id", "")): (getattr(node, "params", None) or {})
            for node in plan_nodes
        }
        for item in run_result.node_results:
            if item.success and item.tool_id == "products" and item.action == "query":
                rows = (item.output or {}).get("data") or []
                n = len(rows) if isinstance(rows, list) else 0
                lines.append(f"- {item.node_id}: 成功（产品库命中 {n} 条）")
                if isinstance(rows, list) and rows:
                    from app.utils.ai_helpers import format_money, safe_float

                    for row in rows[:5]:
                        if not isinstance(row, dict):
                            continue
                        m = str(row.get("model_number") or "").strip() or "-"
                        name = str(row.get("name") or row.get("product_name") or "-").strip()
                        p = safe_float(row.get("price"))
                        u = str(row.get("unit") or "").strip() or "-"
                        lines.append(f"    · {m} / {name} / ￥{format_money(p)} / 单位:{u}")
            elif item.success:
                node_params = node_params_by_id.get(str(item.node_id), {})
                lines.extend(self._format_workflow_tool_success_line(item, node_params))
            else:
                lines.append(f"- {item.node_id}: 失败（{item.error}）")
                retryable = getattr(item, "retryable", True)
                retryable = retryable if isinstance(retryable, bool) else True
                try:
                    retries = int(getattr(item, "retries", 0) or 0)
                except (TypeError, ValueError):
                    retries = 0
                if retryable and retries:
                    lines.append(f"    · 已自动重试: {retries} 次")
                elif not retryable:
                    lines.append("    · 未自动重试: 非幂等或中高风险操作")
                raw_recovery_hint = getattr(item, "recovery_hint", "")
                recovery_hint = (
                    raw_recovery_hint.strip() if isinstance(raw_recovery_hint, str) else ""
                )
                if recovery_hint:
                    lines.append(f"    · 恢复建议: {recovery_hint}")
        if run_result.message:
            lines.append(f"说明: {run_result.message}")
        response_text = "\n".join(lines)
        payload: dict[str, Any] = {
            "success": run_result.success,
            "message": "处理完成" if run_result.success else "处理失败",
            "response": response_text,
            "data": {
                "text": response_text,
                "action": "workflow_done" if run_result.success else "workflow_failed",
                "data": {
                    "plan_id": plan.plan_id,
                    "intent": plan.intent,
                    "thinking_steps": thinking_steps,
                    "todo": plan.todo_steps,
                    "node_results": [
                        {
                            "node_id": r.node_id,
                            "success": r.success,
                            "tool_id": r.tool_id,
                            "action": r.action,
                            "message": r.error or self._workflow_output_message(r.output),
                            "output_preview": self._workflow_output_preview(r.output),
                            "retries": getattr(r, "retries", 0),
                            "retryable": getattr(r, "retryable", True),
                            "recovery_hint": getattr(r, "recovery_hint", ""),
                            "duration_ms": getattr(r, "duration_ms", 0),
                        }
                        for r in run_result.node_results
                    ],
                    "workflow_status": getattr(run_result, "final_context", {}).get(
                        "workflow_status", {}
                    )
                    if isinstance(getattr(run_result, "final_context", {}), dict)
                    else {},
                    "workflow_trace": getattr(run_result, "final_context", {}).get(
                        "workflow_trace", []
                    )
                    if isinstance(getattr(run_result, "final_context", {}), dict)
                    else [],
                },
            },
        }
        if run_result.success and any(
            r.success and r.tool_id == "products" and r.action == "query"
            for r in run_result.node_results
        ):
            q = self._workflow_products_float_query(plan, run_result, user_message)
            payload["autoAction"] = {
                "type": "show_products_float",
                "feature": "products",
                "query": q,
            }
            if q:
                lines.append(f"\n已为你打开产品副窗，搜索：{q}")
            else:
                lines.append("\n已为你打开产品副窗，可在卡片中查询或编辑。")
            payload["response"] = "\n".join(lines)
            payload["data"]["text"] = payload["response"]

        slot_overlay = self._normal_slot_dispatch_chat_overlay(run_result)
        if slot_overlay:
            if slot_overlay.get("response"):
                payload["response"] = slot_overlay["response"]
            if slot_overlay.get("message"):
                payload["message"] = slot_overlay["message"]
            if slot_overlay.get("autoAction"):
                payload["autoAction"] = slot_overlay["autoAction"]
            if slot_overlay.get("task"):
                payload["task"] = slot_overlay["task"]
            payload.setdefault("data", {})
            payload["data"]["text"] = payload["response"]

        return payload

    @staticmethod
    def _normal_slot_dispatch_chat_overlay(run_result) -> dict[str, Any]:
        for item in reversed(run_result.node_results):
            if not item.success or item.tool_id != "normal_slot_dispatch":
                continue
            out = item.output or {}
            if not isinstance(out, dict) or not out.get("success"):
                continue
            if not (out.get("autoAction") or out.get("task")):
                continue
            picked: dict[str, Any] = {}
            for key in ("response", "message", "autoAction", "task"):
                if key in out:
                    picked[key] = out[key]
            return picked
        return {}

    def _dispatch_workflow_tool(
        self, tool_id: str, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            from app.application.facades.tools_facade import execute_registered_workflow_tool

            return execute_registered_workflow_tool(tool_id=tool_id, action=action, params=params)
        except RECOVERABLE_ERRORS as err:
            logger.error(
                "workflow 工具调度失败 tool=%s action=%s err=%s",
                tool_id,
                action,
                err,
                exc_info=True,
            )
            return {"success": False, "message": str(err)}

    def _handle_confirmation_flow(
        self, user_id: str, message: str, file_context: dict[str, Any] | None
    ) -> None:
        """处理确认流程"""
        if not file_context:
            return

        if message not in ("是", "好的", "确认", "yes", "ok", "好"):
            return

        saved_name = file_context.get("saved_name")
        unit_name = file_context.get("unit_name_guess") or file_context.get("unit_name", "")
        suggested_use = file_context.get("suggested_use", "")

        if saved_name and suggested_use == "unit_products_db" and unit_name:
            self.ai_service.set_pending_confirmation(
                user_id,
                {
                    "type": "import_unit_products",
                    "tool_key": "sqlite_import_unit_products",
                    "params": {
                        "saved_name": saved_name,
                        "unit_name": unit_name,
                    },
                    "description": f"导入 {unit_name} 的产品",
                },
            )
            logger.info("用户 %s 确认导入文件：%s -> %s", user_id, saved_name, unit_name)

    def _build_response(
        self, ai_result: dict[str, Any], source: str | None, original_message: str = ""
    ) -> dict[str, Any]:
        """构建响应数据"""
        response_data = {
            "success": True,
            "message": "处理完成",
            "data": {
                "text": ai_result.get("text", ""),
                "action": ai_result.get("action", ""),
                "data": ai_result.get("data", {}) or {},
            },
        }
        response_data["response"] = ai_result.get("text", "")

        action = ai_result.get("action")
        result_data = ai_result.get("data") or {}

        if action == "tool_call" and result_data:
            response_data = self._handle_tool_call(
                response_data, ai_result, result_data, source, original_message
            )
        else:
            if action == "followup":
                response_data["followup"] = result_data
            if action == "auto_action" and result_data:
                response_data["autoAction"] = result_data

        return response_data

    def _handle_tool_call(
        self,
        response_data: dict[str, Any],
        ai_result: dict[str, Any],
        result_data: dict[str, Any],
        source: str | None,
        original_message: str = "",
    ) -> dict[str, Any]:
        """处理工具调用响应"""
        tool_key = result_data.get("tool_key")
        parsed_params = result_data.get("params") or {}
        slots = result_data.get("slots", {})

        if not tool_key:
            response_data["response"] = ai_result.get("text", "")
            response_data["data"]["data"] = result_data.get("data", {}) or {}
            return response_data

        if self._is_pro_source(source):
            response_data = self._execute_pro_mode_tools(
                response_data, tool_key, slots, parsed_params, ai_result, original_message
            )
        else:
            response_data = self._execute_normal_mode_tools(
                response_data, tool_key, parsed_params, ai_result, result_data
            )

        return response_data

    def _execute_pro_mode_tools(
        self,
        response_data: dict[str, Any],
        tool_key: str,
        slots: dict[str, Any],
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
        original_message: str = "",
    ) -> dict[str, Any]:
        """执行专业模式工具"""
        if tool_key == "products":
            return self._execute_products_query(response_data, slots, parsed_params)
        elif tool_key == "customers":
            return self._execute_customers_intent(
                response_data=response_data,
                slots=slots,
                parsed_params=parsed_params,
                original_message=original_message,
            )
        elif tool_key == "shipment_generate":
            unit_name = slots.get("unit_name") or parsed_params.get("unit_name", "")
            quantity_tins = slots.get("quantity_tins") or parsed_params.get("quantity_tins", "")
            model_number = (
                slots.get("model_number")
                or slots.get("product_model")
                or parsed_params.get("model_number", "")
            )
            tin_spec = slots.get("tin_spec") or parsed_params.get("tin_spec", "")
            products_list = slots.get("products") or []
            parsed_products = []
            parsed_unit_name = ""

            # pro 模式优先从原消息解析整单，保留完整 products[]。
            try:
                from app.application.facades.tools_facade import _parse_order_text

                parsed_order = _parse_order_text(original_message or "")
                if parsed_order.get("success"):
                    parsed_products = parsed_order.get("products") or []
                    parsed_unit_name = parsed_order.get("unit_name") or ""
            except RECOVERABLE_ERRORS as parse_err:
                logger.debug("pro shipment_generate 解析原句失败，回退旧逻辑: %s", parse_err)

            if original_message and len(original_message) > 5:
                order_text = original_message
            elif unit_name and quantity_tins and model_number and tin_spec:
                order_text = (
                    f"{unit_name}{int(quantity_tins)} 桶 {model_number} 规格 {int(float(tin_spec))}"
                )
            elif unit_name and products_list:
                order_text = self._build_order_text_from_products(
                    unit_name, products_list, original_message, quantity_tins, tin_spec
                )
            else:
                order_text = ai_result.get("text", "")

            effective_products = parsed_products or products_list
            effective_unit_name = parsed_unit_name or unit_name
            response_data["toolCall"] = {
                "tool_id": tool_key,
                "action": "执行",
                "params": {
                    "order_text": order_text,
                    **parsed_params,
                    **ai_result.get("data", {}),
                    "products": effective_products,
                    "unit_name": effective_unit_name,
                },
            }
            response_data["response"] = ai_result.get("text", "")
            return response_data
        else:
            response_data["toolCall"] = {
                "tool_id": tool_key,
                "action": "执行",
                "params": {
                    "order_text": ai_result.get("text", ""),
                    **parsed_params,
                    **ai_result.get("data", {}),
                },
            }
            response_data["response"] = ai_result.get("text", "")
            return response_data

    def _execute_normal_mode_tools(
        self,
        response_data: dict[str, Any],
        tool_key: str,
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
        result_data: dict[str, Any],
    ) -> dict[str, Any]:
        """执行普通模式工具"""
        if tool_key == "shipment_generate":
            return self._execute_shipment_generate(response_data, parsed_params, ai_result)
        elif tool_key == "shipments":
            return self._execute_shipments_query(response_data)
        else:
            response_data["toolCall"] = {
                "tool_id": tool_key,
                "action": "执行",
                "params": {"order_text": ai_result.get("text", ""), **parsed_params, **result_data},
            }
            response_data["response"] = ai_result.get("text", "")
            return response_data

    def _execute_products_query(
        self, response_data: dict[str, Any], slots: dict[str, Any], parsed_params: dict[str, Any]
    ) -> dict[str, Any]:
        """执行产品查询"""
        try:
            from app.bootstrap import get_products_service
            from app.infrastructure.lookups.purchase_unit_resolver import resolve_purchase_unit

            unit_name = slots.get("unit_name") or parsed_params.get("unit_name", "")
            model_number = slots.get("model_number") or parsed_params.get("model_number", "")
            keyword = slots.get("keyword") or parsed_params.get("keyword", "")

            if not unit_name and not model_number and keyword and "的" in keyword:
                match = re.search(r"([\u4e00-\u9fa5]{2,6})的(\d+[A-Z]?)", keyword)
                if match:
                    potential_unit = match.group(1)
                    model_candidate = match.group(2)
                    resolved = resolve_purchase_unit(potential_unit)
                    if resolved:
                        unit_name = resolved.unit_name
                    else:
                        unit_name = potential_unit
                    model_number = model_candidate
                    keyword = None

            app_service = get_products_service()

            if model_number and unit_name:
                products_result = app_service.get_products(
                    model_number=model_number, unit_name=unit_name
                )
            elif model_number:
                products_result = app_service.get_products(model_number=model_number)
            elif unit_name:
                products_result = app_service.get_products(unit_name=unit_name)
            elif keyword:
                products_result = app_service.get_products(keyword=keyword)
            else:
                products_result = app_service.get_products()

            products_list = products_result.get("data", []) if products_result else []

            response_data["data"]["unit_name"] = unit_name
            response_data["data"]["model_number"] = model_number
            response_data["data"]["data"] = {"products": products_list}
            response_data["response"] = (
                f"查询到 {len(products_list)} 个产品" if products_list else "未找到产品"
            )
            response_data["toolCall"] = {
                "tool_id": "products",
                "action": "执行",
                "params": {
                    "unit_name": unit_name,
                    "model_number": model_number,
                    "keyword": keyword,
                },
            }
            response_data["autoAction"] = {
                "type": "tool_call",
                "tool_key": "products",
                "params": {
                    "unit_name": unit_name,
                    "model_number": model_number,
                    "keyword": keyword,
                },
                "products": products_list,
                "unit_name": unit_name,
                "query": model_number or keyword or "",
            }
        except RECOVERABLE_ERRORS as prod_err:
            logger.error("即时执行 products 查询失败: %s", prod_err, exc_info=True)
            response_data["response"] = f"查询产品失败：{str(prod_err)}"

        return response_data

    def _execute_customers_query(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """执行客户查询"""
        try:
            from app.bootstrap import get_customer_app_service

            app_service = get_customer_app_service()
            customers_result = app_service.get_all()
            customers = customers_result.get("data", []) if customers_result else []

            response_data["data"]["data"] = {"customers": customers}
            response_data["response"] = (
                f"查询到 {len(customers)} 个客户" if customers else "未找到客户"
            )
        except RECOVERABLE_ERRORS as cust_err:
            logger.error("即时执行 customers 查询失败: %s", cust_err, exc_info=True)
            response_data["response"] = f"查询客户失败：{str(cust_err)}"

        return response_data

    def _execute_customers_intent(
        self,
        response_data: dict[str, Any],
        slots: dict[str, Any],
        parsed_params: dict[str, Any],
        original_message: str = "",
    ) -> dict[str, Any]:
        text = str(original_message or "").strip()
        lower = text.lower()
        unit_name = str(
            slots.get("unit_name")
            or parsed_params.get("unit_name")
            or parsed_params.get("customer_name")
            or parsed_params.get("name")
            or ""
        ).strip()

        is_add_intent = any(k in text for k in ("添加", "新增", "新建", "创建")) or any(
            k in lower for k in ("add", "create", "new")
        )
        is_query_intent = any(k in text for k in ("查询", "查", "列表", "全部")) or any(
            k in lower for k in ("query", "search", "list")
        )

        if is_add_intent and not unit_name:
            response_data["response"] = (
                "你要添加哪个单位？请告诉我单位名称，例如：添加单位 七彩乐园。"
            )
            response_data["data"]["data"] = {
                "intent": "customer_create",
                "missing_fields": ["unit_name"],
            }
            return response_data

        if is_add_intent and unit_name:
            try:
                from app.application.facades.tools_facade import execute_registered_workflow_tool

                created = execute_registered_workflow_tool(
                    tool_id="customers",
                    action="ensure_exists",
                    params={"unit_name": unit_name},
                )
                if created.get("success"):
                    if created.get("created"):
                        response_data["response"] = f"单位已创建：{unit_name}"
                    else:
                        response_data["response"] = f"单位已存在：{unit_name}"
                    response_data["data"]["data"] = created
                    return response_data
                response_data["response"] = created.get("message", "处理单位失败")
                return response_data
            except RECOVERABLE_ERRORS as err:
                logger.error("customers 添加意图执行失败: %s", err, exc_info=True)
                response_data["response"] = f"处理单位失败：{str(err)}"
                return response_data

        if is_query_intent:
            return self._execute_customers_query(response_data)

        # 未明确意图时，不再默认查全表，避免“添加单位”误触发列表查询
        response_data["response"] = (
            "我可以帮你处理单位管理。你可以说：“添加单位 七彩乐园”或“查询客户列表”。"
        )
        response_data["data"]["data"] = {"intent": "customers_followup"}
        return response_data

    def _build_order_text_from_products(
        self,
        unit_name: str,
        products: list,
        original_message: str = "",
        default_qty: int = None,
        default_spec: int = None,
    ) -> str:
        """根据产品列表构建订单文本"""
        import re

        if not products:
            return ""
        if not unit_name:
            return ""

        if original_message and len(products) >= 1:
            normalized_msg = original_message.replace("，", ",").replace("。", "").replace(" ", "")
            order_pattern = re.compile(
                r"帮?打\s*(.+?)\s*的?\s*货单?[,，]?\s*(\d+)\s*桶\s*(\d+[A-Z]?(?:-\d+[A-Z]?)?)\s*规格\s*(\d+)\s*[,，]?\s*(\d+)\s*桶\s*(\d+[A-Z]?(?:-\d+[A-Z]?)?)\s*规格\s*(\d+)"
            )
            matches = list(order_pattern.finditer(normalized_msg))

            if len(matches) >= 1:
                m = matches[0]
                found_unit = m.group(1)
                if len(m.groups()) >= 7:
                    order_parts = []
                    for i in range(1, len(m.groups()), 4):
                        if i + 3 <= len(m.groups()):
                            qty = int(m.group(i + 1))
                            model = m.group(i + 2)
                            spec = int(m.group(i + 3))
                            order_parts.append(f"{qty}桶{model}规格{spec}")
                    if order_parts and found_unit:
                        return found_unit + "，" + "，".join(order_parts)
                else:
                    order_parts = []
                    for m in matches:
                        qty = int(m.group(2))
                        model = m.group(3)
                        spec = int(m.group(4))
                        order_parts.append(f"{qty}桶{model}规格{spec}")
                    if order_parts and found_unit:
                        return found_unit + "，" + "，".join(order_parts)

        parts = []
        for p in products:
            model = p.get("model") or p.get("model_number") or p.get("name") or ""
            qty = p.get("quantity_tins") or p.get("quantity") or p.get("qty") or 1
            spec = p.get("spec") or p.get("tin_spec") or p.get("规格") or default_spec or 25
            if model:
                parts.append(f"{int(qty)}桶{model}规格{int(float(spec))}")
            else:
                parts.append(f"{int(qty)}桶规格{int(float(spec))}")
        return unit_name + "，" + "，".join(parts)

    def _try_merge_split_model(self, text: str, product_template: dict) -> str:
        """尝试合并被拆分的型号（如 5003-2737B 被拆成 5003 和 2737B）"""
        import re

        qty = product_template.get("quantity_tins") or 1
        product_template.get("spec") or product_template.get("tin_spec") or 25

        number_pattern = r"(\d+)([A-Z]?)\s*规格\s*(\d+)"
        m = re.search(number_pattern, text)
        if m:
            model = m.group(1) + m.group(2)
            spec_val = int(m.group(3))
            return f"{int(qty)}桶{model}规格{spec_val}"

        number_pattern2 = r"(\d+)\s*桶\s*(\d+)([A-Z]?)\s*规格\s*(\d+)"
        m2 = re.search(number_pattern2, text)
        if m2:
            qty_val = int(m2.group(1))
            model = m2.group(2) + m2.group(3)
            spec_val = int(m2.group(4))
            return f"{qty_val}桶{model}规格{spec_val}"

        return ""

    def _execute_shipment_generate(
        self,
        response_data: dict[str, Any],
        parsed_params: dict[str, Any],
        ai_result: dict[str, Any],
    ) -> dict[str, Any]:
        """执行发货单生成"""
        try:
            from app.application.facades.tools_facade import _parse_order_text
            from app.bootstrap import get_shipment_app_service

            order_text = parsed_params.get("order_text") or ai_result.get("text", "")
            parsed = _parse_order_text(order_text)

            if parsed.get("success"):
                app_service = get_shipment_app_service()
                doc_result = app_service.generate_shipment_document(
                    unit_name=parsed.get("unit_name", ""),
                    products=parsed.get("products") or [],
                    template_name=None,
                )
                response_data["data"]["data"] = {"document": doc_result}

                if doc_result.get("success"):
                    doc_name = doc_result.get("doc_name") or ""
                    response_data["response"] = (
                        f"已生成发货单：{doc_name}" if doc_name else "已生成发货单。"
                    )
                else:
                    response_data["response"] = doc_result.get("message", "生成发货单失败")
            else:
                response_data["response"] = parsed.get("message", "订单解析失败")
        except RECOVERABLE_ERRORS as tool_err:
            logger.error("自动执行 shipment_generate 失败: %s", tool_err, exc_info=True)
            response_data["response"] = f"生成发货单失败：{str(tool_err)}"

        return response_data

    def _execute_shipments_query(self, response_data: dict[str, Any]) -> dict[str, Any]:
        """执行发货记录查询"""
        try:
            from app.bootstrap import get_shipment_app_service

            app_service = get_shipment_app_service()
            orders = app_service.get_orders(10) or []

            lines = ["最新出货/订单记录（最近 10 条）："]
            if not orders:
                lines.append("暂无订单记录。")
            else:
                for o in orders[:10]:
                    order_no = o.get("order_number") or o.get("order_no") or o.get("id") or ""
                    customer = (
                        o.get("customer_name") or o.get("unit_name") or o.get("purchase_unit") or ""
                    )
                    date = o.get("date") or o.get("created_at") or ""
                    amount = (
                        o.get("total_amount") or o.get("total_amount_yuan") or o.get("amount") or 0
                    )
                    status = o.get("status") or "已完成"
                    lines.append(f"- {order_no} | {customer} | {date} | ¥{amount} | {status}")

            response_data["response"] = "\n".join(lines)
            response_data["data"]["data"] = {"orders": orders}
            response_data.pop("toolCall", None)
        except RECOVERABLE_ERRORS as tool_err:
            logger.error("即时执行 shipments 失败：%s", tool_err, exc_info=True)

        return response_data


def get_ai_chat_app_service() -> AIChatApplicationService:
    """获取 AI 聊天应用服务单例"""
    return get_service_registry().ai_chat_application_service
