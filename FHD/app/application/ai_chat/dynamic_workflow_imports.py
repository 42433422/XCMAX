"""Deterministic DB and Excel import branches for dynamic chat workflows."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from app.application.ai_chat.excel_import_policy import (
    _skip_pro_excel_deterministic_import,
)

logger = logging.getLogger(__name__)


class AIChatDynamicImportUseCases:
    def __init__(
        self,
        *,
        excel_import: Any,
        build_workflow_thinking_steps: Callable[..., str],
    ) -> None:
        self._excel = excel_import
        self._build_workflow_thinking_steps = build_workflow_thinking_steps

    def try_unit_products_import(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        merged_file_ctx: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None:
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
                return self._excel._attach_deterministic_workflow_trace(
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
                return self._excel._attach_deterministic_workflow_trace(
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
            return self._excel._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                plan=plan,
                thinking_steps=thinking_steps,
            )

    def try_missing_excel_context(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        merged_file_ctx: dict[str, Any],
        text: str,
        explicit_workflow_tool_intent: bool,
    ) -> dict[str, Any] | None:
        # 无分析结果时短指令勿走 LLM（混合 normal 画像下否则会长时间阻塞在 DeepSeek）
        if (
            not self._excel._excel_analysis_payload_present(context)
            and self._excel._looks_like_short_excel_import_command(text)
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
            return self._excel._attach_deterministic_workflow_trace(
                payload,
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                intent="excel_import_missing_context",
            )

    def try_excel_import(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
        merged_file_ctx: dict[str, Any],
        text: str,
    ) -> dict[str, Any] | None:
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
            records, extract_err = self._excel._extract_excel_import_records(
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
                return self._excel._attach_deterministic_workflow_trace(
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
                return self._excel._attach_deterministic_workflow_trace(
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
            return self._excel._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=context,
                file_context=merged_file_ctx,
                plan=plan,
                thinking_steps=thinking_steps,
            )


__all__ = ["AIChatDynamicImportUseCases"]
