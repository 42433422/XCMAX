"""Dynamic / agentic workflow helpers for AI chat."""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_utils import resolve_fhd_repo_root

from .helpers import (
    _enrich_confirmation_inner,
    _skip_pro_excel_deterministic_import,
)

logger = logging.getLogger(__name__)


class AIChatWorkflowMixin:
    def _try_handle_multimodal_chat(
        self,
        *,
        user_id: str,
        message: str,
        source: str | None,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """多模态主链路收口：聊天上下文携带真实多模态 artifact 且多模态自治规划器能产出
        计划时，走真正的 orchestrator run（Dataset/RAG 入库+检索/确认写库），替代 legacy 兜底。

        护栏：无 artifact 信号键、或规划器返回 None 时不分流，保持 legacy 主链路不变；
        实测纯文本 / excel_vector / 纯 excel_analysis 上下文均不会分流（最热路径零影响）。
        """
        ctx = context if isinstance(context, dict) else {}
        signal_keys = (
            "multimodal_attachments",
            "attachments",
            "files",
            "artifacts",
            "ocr",
            "ocr_result",
            "file_analysis",
            "generated_document",
            "excel_analysis",
        )
        if not any(ctx.get(key) for key in signal_keys):
            return None
        try:
            from app.application.agent_orchestrator.multimodal_planner import (
                build_multimodal_autonomous_plan,
            )
        except RECOVERABLE_ERRORS:
            return None
        runtime_ctx = dict(ctx)
        runtime_ctx.setdefault("message", message)
        try:
            plan = build_multimodal_autonomous_plan(
                user_id=user_id,
                message=message,
                runtime_context=runtime_ctx,
            )
        except RECOVERABLE_ERRORS:
            logger.debug("multimodal autonomous plan probe skipped", exc_info=True)
            return None
        if plan is None:
            return None
        try:
            return self._start_deterministic_import_agent_run(
                user_id=user_id,
                message=message,
                source=source,
                context=ctx,
                file_context={},
                plan=plan,
                thinking_steps="检测到多模态附件，已转入多模态自治工作流",
            )
        except RECOVERABLE_ERRORS:
            logger.exception("multimodal autonomous run failed; falling back to legacy chat")
            return None

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
        smart_workflow_intent = self._looks_like_smart_workflow_intent(text, context)
        has_pending_workflow = user_id in self._pending_workflows
        if (
            not self._is_pro_source(source)
            and not smart_workflow_intent
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

                    approval_inner = {
                        "plan_id": plan.plan_id,
                        "approval_required": True,
                        "approval_nodes": approval_nodes,
                    }
                    return {
                        "success": True,
                        "message": "处理完成",
                        "response": "已提交审批请求，请等待审批完成后继续。",
                        "data": {
                            "text": "已提交审批请求，请等待审批完成后继续。",
                            "action": "approval_pending",
                            "data": _enrich_confirmation_inner(
                                approval_inner, action="approval_pending"
                            ),
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
        if profile == "normal" and not explicit_workflow_tool_intent and not smart_workflow_intent:
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
            confirm_inner = {
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
            }
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
                    "data": _enrich_confirmation_inner(
                        confirm_inner, action="workflow_confirmation_required"
                    ),
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
            risk_inner = {
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
            }
            payload: dict[str, Any] = {
                "success": True,
                "message": "处理完成",
                "response": response_text,
                "data": {
                    "text": response_text,
                    "action": "workflow_confirmation_required",
                    "data": _enrich_confirmation_inner(
                        risk_inner, action="workflow_confirmation_required"
                    ),
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
