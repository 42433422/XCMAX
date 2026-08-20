# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.ai_chat_app_service")


class __AIChatApplicationServicePart02MixinPart02Mixin:
    def _try_handle_dynamic_workflow(
        self,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, _facade().Any],
        file_context: dict[str, _facade().Any],
    ) -> dict[str, _facade().Any] | None:
        text = str(message or "").strip()
        if not text:
            return None
        self._sweep_expired_clarifications()
        explicit_workflow_tool_intent = self._looks_like_explicit_workflow_tool_intent(text)
        smart_workflow_intent = self._looks_like_smart_workflow_intent(text, context)
        has_pending_workflow = user_id in self._pending_workflows
        if (
            not self._is_pro_source(source)
            and (not smart_workflow_intent)
            and (not has_pending_workflow)
            and self._is_pure_casual_chat(text)
        ):
            return None
        merged_file_ctx: dict[str, _facade().Any] = {}
        if isinstance(context, dict):
            merged_file_ctx.update(context.get("file_analysis") or {})
            merged_file_ctx.update(context.get("file_context") or {})
        if isinstance(file_context, dict):
            merged_file_ctx.update(file_context)
        import_intent = any(k in text for k in ("导入", "入库", "添加到数据库", "写入数据库"))
        if import_intent and merged_file_ctx.get("suggested_use") == "unit_products_db":
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
                plan_id=f"plan_unit_products_import_{_facade().uuid.uuid4().hex[:12]}",
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
                plan, "unit_products 导入会写入客户和产品数据库，需用户确认"
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
        if (
            not self._excel_analysis_payload_present(context)
            and self._looks_like_short_excel_import_command(text)
            and (not explicit_workflow_tool_intent)
        ):
            payload = {
                "success": True,
                "message": "处理完成",
                "response": "未检测到 Excel 分析上下文。请先点击工具栏「分析 Excel」上传并分析表格，再发送「加入数据库」等指令。\n若已分析过，可能是会话切换或页面刷新导致上下文丢失——请重新分析一次。",
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
        excel_analysis = (
            (context or {}).get("excel_analysis") if isinstance(context, dict) else None
        )
        if (
            isinstance(excel_analysis, dict)
            and any(k in text for k in ("数据库", "入库", "导入", "添加到库"))
            and (not _facade()._skip_pro_excel_deterministic_import(context))
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
                "按内容指纹识别送货单表（标题含送货单+购货单位+产品明细）",
                "解析抬头客户与明细行",
                "写入客户、产品，并生成发货单",
                "返回闭环结果（发货单数/产品数）",
            ]
            file_path = str(
                excel_analysis.get("file_path")
                or (
                    excel_analysis.get("preview_data") or {}
                    if isinstance(excel_analysis.get("preview_data"), dict)
                    else {}
                ).get("file_path")
                or ""
            ).strip()
            delivery_notes: list = []
            if file_path:
                try:
                    from app.application.shipment_excel_etl_app_service import parse_delivery_notes

                    parsed_notes = parse_delivery_notes(file_path)
                    if parsed_notes.get("success") and parsed_notes.get("notes"):
                        delivery_notes = list(parsed_notes.get("notes") or [])
                except _facade().RECOVERABLE_ERRORS as parse_err:
                    _facade().logger.warning("shipment etl detect failed: %s", parse_err)
            if delivery_notes:
                from app.application.workflow.types import PlanGraph, WorkflowNode

                note_summary = "；".join(
                    f"{n.get('sheet')}→{n.get('unit_name')}({n.get('item_count')}行)"
                    for n in delivery_notes[:5]
                )
                plan = PlanGraph(
                    plan_id=f"plan_shipment_etl_{_facade().uuid.uuid4().hex[:12]}",
                    intent="excel_import_to_db",
                    todo_steps=todo_lines,
                    nodes=[
                        WorkflowNode(
                            node_id="import_delivery_notes",
                            tool_id="excel_import",
                            action="import_delivery_notes",
                            params={
                                "file_path": file_path,
                                "notes": delivery_notes,
                                "import_products": True,
                                "import_shipments": True,
                                "source": "deterministic_shipment_etl",
                            },
                            risk="medium",
                            idempotent=False,
                            description="将送货单写入客户/产品/发货单（闭环）",
                        )
                    ],
                    risk_level="medium",
                    metadata={
                        "source": "deterministic_shipment_excel_etl",
                        "artifacts": [
                            {
                                "artifact_type": "shipment_delivery_notes",
                                "name": str(
                                    excel_analysis.get("file_name")
                                    or excel_analysis.get("template_name")
                                    or "shipment_etl"
                                ),
                                "source": "excel_analysis",
                                "uri": file_path,
                                "summary": note_summary or f"送货单 {len(delivery_notes)} 张",
                                "preview": {
                                    "note_count": len(delivery_notes),
                                    "sample_notes": [
                                        {
                                            "sheet": n.get("sheet"),
                                            "unit_name": n.get("unit_name"),
                                            "item_count": n.get("item_count"),
                                            "total_amount": n.get("total_amount"),
                                        }
                                        for n in delivery_notes[:3]
                                    ],
                                },
                                "metadata": {
                                    "import_pipeline": "shipment_delivery_etl",
                                    "closed_loop": True,
                                },
                            }
                        ],
                    },
                )
                thinking_steps = self._build_workflow_thinking_steps(
                    plan, "检测到送货单版式，将写入客户/产品/发货单，需用户确认"
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
            todo_lines = [
                "解析 Excel 数据并映射单位/产品/型号/价格字段",
                "检查客户是否存在，不存在则创建",
                "检查产品是否存在，缺失则创建并绑定单位",
                "返回导入结果（新增单位/新增产品/跳过重复）",
            ]
            (records, extract_err) = self._extract_excel_import_records(
                excel_analysis, context, user_message=text
            )
            if extract_err == "ambiguous_price_columns":
                cols_preview = "、".join(field_names[:24]) if field_names else "（见上文字段列表）"
                followup_text = f"已检测到多个「价格」相关列（例如同时存在「调价前…价」与「调价后…价」），为避免入错库，已暂停自动写入。\n请在下一条消息中明确指定，例如：「导入数据库，价格用调价前列」或「…单价取调价后那一列」。\n当前识别到的部分列名：{cols_preview}"
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
                followup_text = f"我已读取到 Excel 上下文，但未解析到可入库的单位/产品记录。\n已识别字段: {('、'.join(field_names) if field_names else '未识别到字段')}"
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
                plan_id=f"plan_excel_import_{_facade().uuid.uuid4().hex[:12]}",
                intent="excel_import_to_db",
                todo_steps=todo_lines,
                nodes=[
                    WorkflowNode(
                        node_id="import_excel_records",
                        tool_id="excel_import",
                        action="import_records",
                        params={"records": records, "source": "deterministic_shortcut"},
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
                plan, "Excel 入库会写入客户和产品数据库，需用户确认"
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
        return self._try_handle_dynamic_workflow_after_excel(
            user_id=user_id,
            message=message,
            source=source,
            context=context,
            text=text,
            explicit_workflow_tool_intent=explicit_workflow_tool_intent,
        )
