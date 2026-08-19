# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.ai_chat_app_service')

class _AIChatApplicationServicePart02Mixin:

    def _try_handle_dynamic_workflow(self, user_id: str, message: str, source: str | None, context: dict[str, _facade().Any], file_context: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
        text = str(message or '').strip()
        if not text:
            return None
        self._sweep_expired_clarifications()
        explicit_workflow_tool_intent = self._looks_like_explicit_workflow_tool_intent(text)
        smart_workflow_intent = self._looks_like_smart_workflow_intent(text, context)
        has_pending_workflow = user_id in self._pending_workflows
        if not self._is_pro_source(source) and (not smart_workflow_intent) and (not has_pending_workflow) and self._is_pure_casual_chat(text):
            return None
        merged_file_ctx: dict[str, _facade().Any] = {}
        if isinstance(context, dict):
            merged_file_ctx.update(context.get('file_analysis') or {})
            merged_file_ctx.update(context.get('file_context') or {})
        if isinstance(file_context, dict):
            merged_file_ctx.update(file_context)
        import_intent = any((k in text for k in ('导入', '入库', '添加到数据库', '写入数据库')))
        if import_intent and merged_file_ctx.get('suggested_use') == 'unit_products_db':
            saved_name = str(merged_file_ctx.get('saved_name') or '').strip()
            unit_name = str(merged_file_ctx.get('unit_name') or merged_file_ctx.get('unit_name_guess') or '').strip()
            if not saved_name:
                payload = {'success': True, 'message': '处理完成', 'response': '已识别导入意图，但缺少源文件上下文。请先上传并分析 .db 文件。', 'data': {'text': '请先上传并分析 .db 文件。', 'action': 'followup', 'data': {}}}
                return self._attach_deterministic_workflow_trace(payload, user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, intent='import_unit_products_db')
            if not unit_name:
                payload = {'success': True, 'message': '处理完成', 'response': '已识别导入意图，请补充客户名称后继续导入。', 'data': {'text': '请补充客户名称后继续导入。', 'action': 'followup', 'data': {'missing_fields': ['unit_name']}}}
                return self._attach_deterministic_workflow_trace(payload, user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, intent='import_unit_products_db')
            todo_lines = ['检查客户是否存在，不存在则自动创建', '读取源库 products 表并映射字段', '按单位+型号/名称去重后导入产品', '返回导入结果（新增/跳过/失败）']
            from app.application.workflow.types import PlanGraph, WorkflowNode
            plan = PlanGraph(plan_id=f'plan_unit_products_import_{_facade().uuid.uuid4().hex[:12]}', intent='import_unit_products_db', todo_steps=todo_lines, nodes=[WorkflowNode(node_id='import_unit_products', tool_id='unit_products_import', action='execute_import', params={'saved_name': saved_name, 'unit_name': unit_name, 'create_purchase_unit': True, 'skip_duplicates': True}, risk='medium', idempotent=False, description='从已分析 .db 文件导入单位和产品')], risk_level='medium', metadata={'source': 'deterministic_file_import', 'artifacts': [{'artifact_type': 'database_file', 'name': saved_name, 'source': 'file_analysis', 'summary': f'unit_products_db 导入源文件，目标客户：{unit_name}', 'fields': [{'name': 'saved_name', 'value': saved_name}, {'name': 'unit_name', 'value': unit_name}, {'name': 'suggested_use', 'value': merged_file_ctx.get('suggested_use')}], 'metadata': {'suggested_use': merged_file_ctx.get('suggested_use'), 'unit_name_guess': merged_file_ctx.get('unit_name_guess')}}]})
            thinking_steps = self._build_workflow_thinking_steps(plan, 'unit_products 导入会写入客户和产品数据库，需用户确认')
            return self._start_deterministic_import_agent_run(user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, plan=plan, thinking_steps=thinking_steps)
        if not self._excel_analysis_payload_present(context) and self._looks_like_short_excel_import_command(text) and (not explicit_workflow_tool_intent):
            payload = {'success': True, 'message': '处理完成', 'response': '未检测到 Excel 分析上下文。请先点击工具栏「分析 Excel」上传并分析表格，再发送「加入数据库」等指令。\n若已分析过，可能是会话切换或页面刷新导致上下文丢失——请重新分析一次。', 'data': {'text': '未检测到 Excel 分析上下文，请先分析 Excel。', 'action': 'followup', 'data': {'intent': 'excel_import_missing_context'}}}
            return self._attach_deterministic_workflow_trace(payload, user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, intent='excel_import_missing_context')
        excel_analysis = (context or {}).get('excel_analysis') if isinstance(context, dict) else None
        if isinstance(excel_analysis, dict) and any((k in text for k in ('数据库', '入库', '导入', '添加到库'))) and (not _facade()._skip_pro_excel_deterministic_import(context)):
            fields = excel_analysis.get('fields') or []
            field_names = []
            for item in fields[:10]:
                if isinstance(item, dict):
                    field_names.append(str(item.get('label') or item.get('name') or '').strip())
                else:
                    field_names.append(str(item).strip())
            field_names = [x for x in field_names if x]
            summary = str(excel_analysis.get('summary') or '').strip()
            todo_lines = ['按内容指纹识别送货单表（标题含送货单+购货单位+产品明细）', '解析抬头客户与明细行', '写入客户、产品，并生成发货单', '返回闭环结果（发货单数/产品数）']
            file_path = str(excel_analysis.get('file_path') or (excel_analysis.get('preview_data') or {} if isinstance(excel_analysis.get('preview_data'), dict) else {}).get('file_path') or '').strip()
            delivery_notes: list = []
            if file_path:
                try:
                    from app.application.shipment_excel_etl_app_service import parse_delivery_notes
                    parsed_notes = parse_delivery_notes(file_path)
                    if parsed_notes.get('success') and parsed_notes.get('notes'):
                        delivery_notes = list(parsed_notes.get('notes') or [])
                except _facade().RECOVERABLE_ERRORS as parse_err:
                    _facade().logger.warning('shipment etl detect failed: %s', parse_err)
            if delivery_notes:
                from app.application.workflow.types import PlanGraph, WorkflowNode
                note_summary = '；'.join((f"{n.get('sheet')}→{n.get('unit_name')}({n.get('item_count')}行)" for n in delivery_notes[:5]))
                plan = PlanGraph(plan_id=f'plan_shipment_etl_{_facade().uuid.uuid4().hex[:12]}', intent='excel_import_to_db', todo_steps=todo_lines, nodes=[WorkflowNode(node_id='import_delivery_notes', tool_id='excel_import', action='import_delivery_notes', params={'file_path': file_path, 'notes': delivery_notes, 'import_products': True, 'import_shipments': True, 'source': 'deterministic_shipment_etl'}, risk='medium', idempotent=False, description='将送货单写入客户/产品/发货单（闭环）')], risk_level='medium', metadata={'source': 'deterministic_shipment_excel_etl', 'artifacts': [{'artifact_type': 'shipment_delivery_notes', 'name': str(excel_analysis.get('file_name') or excel_analysis.get('template_name') or 'shipment_etl'), 'source': 'excel_analysis', 'uri': file_path, 'summary': note_summary or f'送货单 {len(delivery_notes)} 张', 'preview': {'note_count': len(delivery_notes), 'sample_notes': [{'sheet': n.get('sheet'), 'unit_name': n.get('unit_name'), 'item_count': n.get('item_count'), 'total_amount': n.get('total_amount')} for n in delivery_notes[:3]]}, 'metadata': {'import_pipeline': 'shipment_delivery_etl', 'closed_loop': True}}]})
                thinking_steps = self._build_workflow_thinking_steps(plan, '检测到送货单版式，将写入客户/产品/发货单，需用户确认')
                return self._start_deterministic_import_agent_run(user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, plan=plan, thinking_steps=thinking_steps)
            todo_lines = ['解析 Excel 数据并映射单位/产品/型号/价格字段', '检查客户是否存在，不存在则创建', '检查产品是否存在，缺失则创建并绑定单位', '返回导入结果（新增单位/新增产品/跳过重复）']
            (records, extract_err) = self._extract_excel_import_records(excel_analysis, context, user_message=text)
            if extract_err == 'ambiguous_price_columns':
                cols_preview = '、'.join(field_names[:24]) if field_names else '（见上文字段列表）'
                followup_text = f'已检测到多个「价格」相关列（例如同时存在「调价前…价」与「调价后…价」），为避免入错库，已暂停自动写入。\n请在下一条消息中明确指定，例如：「导入数据库，价格用调价前列」或「…单价取调价后那一列」。\n当前识别到的部分列名：{cols_preview}'
                payload = {'success': True, 'message': '处理完成', 'response': followup_text, 'data': {'text': followup_text, 'action': 'followup', 'data': {'intent': 'excel_import_to_db', 'import_pipeline': 'deterministic_shortcut', 'import_pipeline_zh': '服务端规则入库（非本轮大模型端到端决策）', 'thinking_steps': '价格列存在歧义，需用户明确选用调价前或调价后', 'todo': todo_lines, 'blocked_reason': extract_err}}}
                return self._attach_deterministic_workflow_trace(payload, user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, intent='excel_import_to_db')
            if not records:
                followup_text = f"我已读取到 Excel 上下文，但未解析到可入库的单位/产品记录。\n已识别字段: {('、'.join(field_names) if field_names else '未识别到字段')}"
                if summary:
                    followup_text += f'\n上下文摘要:\n{summary[:500]}'
                payload = {'success': True, 'message': '处理完成', 'response': followup_text, 'data': {'text': followup_text, 'action': 'followup', 'data': {'intent': 'excel_import_to_db', 'import_pipeline': 'deterministic_shortcut', 'import_pipeline_zh': '服务端规则入库（非本轮大模型端到端决策）', 'thinking_steps': '已完成字段识别，但记录提取为空', 'todo': todo_lines}}}
                return self._attach_deterministic_workflow_trace(payload, user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, intent='excel_import_to_db')
            from app.application.workflow.types import PlanGraph, WorkflowNode
            plan = PlanGraph(plan_id=f'plan_excel_import_{_facade().uuid.uuid4().hex[:12]}', intent='excel_import_to_db', todo_steps=todo_lines, nodes=[WorkflowNode(node_id='import_excel_records', tool_id='excel_import', action='import_records', params={'records': records, 'source': 'deterministic_shortcut'}, risk='medium', idempotent=False, description='将 Excel 解析记录写入客户和产品数据库')], risk_level='medium', metadata={'source': 'deterministic_excel_import', 'artifacts': [{'artifact_type': 'excel_records', 'name': str(excel_analysis.get('file_name') or excel_analysis.get('template_name') or 'excel_import_records'), 'source': 'excel_analysis', 'uri': str(excel_analysis.get('file_path') or ''), 'summary': summary or f'Excel 入库记录 {len(records)} 条', 'fields': [{'name': name} for name in field_names[:40] if str(name or '').strip()], 'preview': {'record_count': len(records), 'sample_records': records[:3]}, 'metadata': {'import_pipeline': 'deterministic_shortcut', 'sheet_name': excel_analysis.get('sheet_name')}}]})
            thinking_steps = self._build_workflow_thinking_steps(plan, 'Excel 入库会写入客户和产品数据库，需用户确认')
            return self._start_deterministic_import_agent_run(user_id=user_id, message=message, source=source, context=context, file_context=merged_file_ctx, plan=plan, thinking_steps=thinking_steps)
        from app.application.normal_chat_dispatch import build_customers_query_response_dict, build_inventory_alert_response_dict, build_label_print_response_dict, build_product_query_response_dict, resolve_tool_execution_profile, route_normal_mode_message, run_normal_slot_shipment_preview
        profile = resolve_tool_execution_profile(context if isinstance(context, dict) else {})
        if profile == 'normal' and (not explicit_workflow_tool_intent):
            rr = route_normal_mode_message(text)
            if rr.get('intent') == 'product_query':
                pq = build_product_query_response_dict(rr)
                if pq:
                    return pq
            if rr.get('intent') == 'shipment':
                ship = run_normal_slot_shipment_preview(text)
                if ship.get('success'):
                    ship.pop('normal_slot_dispatch', None)
                    return ship
            if rr.get('intent') == 'customers_query':
                cq = build_customers_query_response_dict(rr)
                if cq:
                    return cq
            if rr.get('intent') == 'inventory_alert':
                ia = build_inventory_alert_response_dict(rr)
                if ia:
                    return ia
            if rr.get('intent') == 'label_print':
                lp = build_label_print_response_dict(rr)
                if lp:
                    return lp
            if rr.get('intent') == 'price_list':
                customer_name_match = _facade().re.search('([^\\s，,。]{2,}(?:有限公司|集团有限公司|实业有限公司|公司\\s|单位|客户|厂|店))', text)
                keyword_match = _facade().re.search('[的的]\\s*([^\\s，,。]+)', text)
                slots = {}
                if customer_name_match:
                    slots['customer_name'] = customer_name_match.group(1)
                if keyword_match:
                    slots['keyword'] = keyword_match.group(1)
                if not slots.get('customer_name'):
                    return {'success': False, 'message': '缺少客户名称', 'response': '请告诉我您要生成哪家客户的价格表？例如：「打印某某公司的价格表」'}
                try:
                    fhd_root = _facade().resolve_fhd_repo_root(anchor=_facade().Path(__file__).resolve())
                    from app.application.tools import handle_price_list_export
                    _facade().logger.info('价格表生成 - FHD根目录: %s', fhd_root)
                    result = handle_price_list_export({'customer_name': slots.get('customer_name', ''), 'keyword': slots.get('keyword'), 'export_date': None}, workspace_root=str(fhd_root) if fhd_root else None)
                    _facade().logger.info('价格表生成结果: %s', result)
                    if result.get('success'):
                        product_count = len(result.get('products', []))
                        file_path = result.get('file_path', '')
                        filename = file_path.split('/')[-1].split('\\')[-1] if file_path else '价格表.docx'
                        return {'success': True, 'message': result.get('message', '价格表已生成'), 'response': f"好的，价格表已生成成功！\n\n{result.get('message', '')}\n\n📄 文件名：{filename}\n💡 已在右侧任务面板中添加下载和打印按钮。", 'data': {'file_path': file_path, 'download_url': result.get('download_url'), 'filename': filename, 'product_count': product_count, 'intent': 'price_list', 'action': 'tool_call', 'tool_key': 'price_list'}}
                    else:
                        return {'success': False, 'message': result.get('error', '价格表生成失败'), 'response': f"抱歉，价格表生成失败：{result.get('error', '未知错误')}"}
                except _facade().RECOVERABLE_ERRORS as e:
                    _facade().logger.error('价格表生成异常：%s', e, exc_info=True)
                    return {'success': False, 'message': f'价格表生成异常：{str(e)}', 'response': f'抱歉，价格表生成时出现错误：{str(e)}'}
        confirm_words = {'确认', '是', '好的', '继续', '执行', 'ok', 'yes'}
        cancel_words = {'取消', '否', '不要', '停止', 'no'}
        _resume_msg = (message or '').strip().lower()
        if user_id not in self._pending_workflows and (_resume_msg in {w.lower() for w in confirm_words} or _resume_msg in {w.lower() for w in cancel_words}):
            self._hydrate_pending_workflow(user_id)
        pending = self._pending_workflows.get(user_id)
        if pending:
            if pending.get('kind') == 'clarification':
                continued = self._continue_after_clarification(user_id, pending, message)
                if continued is not None:
                    return continued
                return {'success': True, 'message': '需要澄清', 'response': '仍无法唯一确定操作目标，请回复候选序号或唯一 ID（例如「1」）。', 'data': {'text': '仍无法唯一确定操作目标，请回复候选序号或唯一 ID。', 'action': 'clarification_required', 'data': {'requires_confirmation': True}}}
            if text.lower() in confirm_words or text in confirm_words:
                pending_plan = _facade().cast('PlanGraph | None', pending.get('plan'))
                if pending_plan is None:
                    self._pending_workflows.pop(user_id, None)
                    return None
                runtime_ctx = pending.get('runtime_context', {})
                approval_required = pending.get('approval_required', False)
                approval_nodes = pending.get('approval_nodes', [])
                if approval_required and approval_nodes:
                    approval_request_ids: list[str] = []
                    approval_requests: list[dict[str, _facade().Any]] = []
                    try:
                        from app.application.agent_orchestrator import AgentOrchestrator
                        from app.application.workflow.types import PlanGraph
                        for node_info in approval_nodes:
                            node = None
                            for n in pending_plan.nodes:
                                if n.node_id == node_info.get('node_id'):
                                    node = n
                                    break
                            if node:
                                approved_node = _facade().copy.deepcopy(node)
                                approved_node.depends_on = []
                                approved_node.next = None
                                approved_node.branches = []
                                approved_plan = PlanGraph(plan_id=f'{pending_plan.plan_id}:{node.node_id}', intent=pending_plan.intent, todo_steps=[node.description or f'{node.tool_id}.{node.action}'], nodes=[approved_node], risk_level=node.risk, metadata=dict(pending_plan.metadata or {}))
                                agent_run = AgentOrchestrator().start_run_from_plan(user_id=self._task_owner_id(user_id, runtime_ctx), message=str(runtime_ctx.get('message') or message), plan=approved_plan, runtime_context=runtime_ctx, auto_execute=True)
                                if agent_run.status != 'waiting_user':
                                    raise RuntimeError(f'审批节点未进入安全等待态：{node.node_id} ({agent_run.status})')
                                request = self.approval_service.create_approval_request(plan_id=pending_plan.plan_id, node=node, runtime_context=runtime_ctx, plan=approved_plan, require_persistence=True)
                                request_id = str(request.request_id or '').strip()
                                if not request_id:
                                    raise RuntimeError('审批请求缺少请求号')
                                self.approval_service.attach_pending_agent_run(request_id, agent_run_id=agent_run.run_id, approved_step_id=approved_node.node_id)
                                approval_request_ids.append(request_id)
                                metadata = self.approval_service.get_request_metadata(request_id) or {'request_no': request_id}
                                metadata['agent_run_id'] = agent_run.run_id
                                approval_requests.append(metadata)
                    except RuntimeError as exc:
                        self._pending_workflows.pop(user_id, None)
                        return {'success': False, 'message': '审批请求创建失败', 'response': f'审批请求创建失败，数据库未写入：{exc}', 'data': {'text': f'审批请求创建失败，数据库未写入：{exc}', 'action': 'approval_failed', 'data': {'plan_id': pending_plan.plan_id}}}
                    self._pending_workflows.pop(user_id, None)
                    approval_path = str((approval_requests[0] if approval_requests else {}).get('approval_path') or '/mod/xcagi-approval-bridge/approval-hub/workspace')
                    approval_inner = {'plan_id': pending_plan.plan_id, 'approval_required': True, 'approval_nodes': approval_nodes, 'approval_request_ids': approval_request_ids, 'approval_requests': approval_requests, 'approval_path': approval_path}
                    return {'success': True, 'message': '处理完成', 'response': f"已提交审批请求：{', '.join(approval_request_ids)}。请前往审批工作台逐笔处理。", 'data': {'text': f"已提交审批请求：{', '.join(approval_request_ids)}。请前往审批工作台逐笔处理。", 'action': 'approval_pending', 'data': _facade()._enrich_confirmation_inner(approval_inner, action='approval_pending')}}
                agent_run_id = str(pending.get('agent_run_id') or '').strip()
                if agent_run_id:
                    from app.application.agent_orchestrator import AgentOrchestrator
                    continued_agent_run = AgentOrchestrator().continue_run(agent_run_id, approved_by=user_id, runtime_context=runtime_ctx)
                    self._pending_workflows.pop(user_id, None)
                    if continued_agent_run is not None:
                        return self._format_agent_run_response(pending_plan, continued_agent_run, thinking_steps=str(pending.get('thinking_steps') or ''), user_message=str(runtime_ctx.get('message') or ''))
                (run_result, state_updates) = self._run_workflow_with_state_updates(plan=pending_plan, runtime_context=runtime_ctx, max_retries=1, resume=True)
                self._pending_workflows.pop(user_id, None)
                return self._format_workflow_run_response(pending_plan, run_result, user_message=str(runtime_ctx.get('message') or ''), state_updates=state_updates)
            if text.lower() in cancel_words or text in cancel_words:
                self._pending_workflows.pop(user_id, None)
                return {'success': True, 'message': '处理完成', 'response': '已取消本次工作流执行。', 'data': {'text': '已取消本次工作流执行。', 'action': 'workflow_cancelled', 'data': {}}}
        if profile == 'pro_default':
            rr_pro_ship = route_normal_mode_message(text)
            if rr_pro_ship.get('intent') == 'shipment':
                try:
                    from app.application.facades.tools_facade import _parse_order_text
                    parsed_quick = _parse_order_text(text)
                except _facade().RECOVERABLE_ERRORS:
                    parsed_quick = {'success': False}
                if parsed_quick.get('success'):
                    quick_ai = {'text': '已识别订单，正在生成发货单…', 'action': 'tool_call', 'data': {'tool_key': 'shipment_generate', 'intent': 'shipment_generate', 'slots': {'unit_name': (parsed_quick.get('unit_name') or '').strip(), 'products': parsed_quick.get('products') or []}, 'hints': [], 'habit_suggestion': None}}
                    return self._build_response(quick_ai, source, text)
                return None
        from app.application.facades.tools_facade import get_workflow_tool_registry
        tool_registry = get_workflow_tool_registry()
        planner_message = message
        if '刚才' in str(message or '') and any((token in str(message or '') for token in ('修改', '更新', '改为', '改成', '删除', '移除'))):
            from app.services.tools_workflow_registered import get_recent_business_db_target
            recent_target = get_recent_business_db_target(user_id)
            if recent_target is None:
                return {'success': True, 'message': '需要澄清', 'response': '当前会话没有可安全引用的上一条数据库记录，请提供实体名称和唯一 ID。', 'data': {'text': '当前会话没有可安全引用的上一条数据库记录，请提供实体名称和唯一 ID。', 'action': 'clarification_required', 'data': {'requires_confirmation': True, 'reason': 'missing_recent_database_target', 'field': 'id'}}}
            entity_labels = {'customers': '客户', 'products': '产品', 'materials': '原材料', 'shipment_records': '发货记录'}
            entity = str(recent_target.get('entity') or '')
            planner_message = f"{message}；数据库{entity_labels.get(entity, entity)} ID: {int(recent_target['id'])}"
        plan = self.workflow_planner.plan(user_id=user_id, message=planner_message, tool_registry=tool_registry, context=context)
        from app.application.workflow.types import PlanGraph
        if not isinstance(plan, PlanGraph):
            _facade().logger.warning('工作流规划器返回无效计划类型: %s', type(plan).__name__)
            return None
        decision = self.risk_gate.evaluate(plan=plan, context=context)
        runtime_ctx = self._merge_tool_runtime_context(user_id, message, context)
        runtime_ctx['source'] = str(source or '').strip()
        runtime_ctx['workflow_trace_mode'] = 'agent_orchestrator'
        runtime_ctx['dynamic_workflow'] = True
        thinking_steps = self._build_workflow_thinking_steps(plan=plan, decision_reason=decision.reason)
        if user_id not in self._pending_workflows:
            clarify_result = self._open_clarification_gate(user_id=user_id, plan=plan, tool_registry=tool_registry, runtime_context=runtime_ctx, thinking_steps=thinking_steps, message=message)
            if clarify_result is not None:
                return clarify_result
        approval_required_nodes = self.approval_service.get_approval_required_nodes(plan)
        has_approval_requirement = bool(approval_required_nodes)
        approval_info = ''
        if has_approval_requirement:
            approval_node_names = [f'{n.tool_id}.{n.action}' for n in approval_required_nodes]
            approval_info = '\n以下操作需要审批后执行：' + '、'.join(approval_node_names)
        use_agentic = bool((runtime_ctx.get('excel_analysis') or {}).get('file_path'))
        if not has_approval_requirement and (not use_agentic):
            from app.application.agent_orchestrator import AgentOrchestrator
            agent_run = AgentOrchestrator().start_run_from_plan(user_id=self._task_owner_id(user_id, runtime_ctx), message=message, plan=plan, runtime_context=runtime_ctx, auto_execute=True)
            if agent_run.status != 'waiting_user':
                return self._format_agent_run_response(plan, agent_run, thinking_steps=thinking_steps, user_message=str(message or ''))
            blocking_nodes = [step.node_id for step in getattr(agent_run, 'steps', []) or [] if step.status == 'waiting_user']
            self._pending_workflows[user_id] = {'plan': plan, 'runtime_context': runtime_ctx, 'pending_id': _facade().uuid.uuid4().hex, 'agent_run_id': agent_run.run_id, 'thinking_steps': thinking_steps, 'approval_required': False, 'approval_nodes': []}
            self._persist_plan_state(plan, runtime_ctx, status='pending_awaiting')
            todo_text = '\n'.join((f'- {step}' for step in plan.todo_steps or []))
            reason = decision.reason or '工具策略要求用户确认'
            response_text = f"我已根据语义生成动态工作流计划：\n{thinking_steps}\n\n{todo_text}\n\n检测到需确认步骤（{', '.join(blocking_nodes) or 'workflow'}），回复「确认」继续执行，回复「取消」终止。"
            confirm_inner = {'run_id': agent_run.run_id, 'agent_run_id': agent_run.run_id, 'plan_id': plan.plan_id, 'intent': plan.intent, 'thinking_steps': thinking_steps, 'todo': plan.todo_steps, 'blocking_nodes': blocking_nodes, 'reason': reason, 'approval_required': False, 'approval_nodes': []}
            return {'success': True, 'message': '处理完成', 'response': response_text, 'run_id': agent_run.run_id, 'agent_run_id': agent_run.run_id, 'data': {'text': response_text, 'action': 'workflow_confirmation_required', 'run_id': agent_run.run_id, 'agent_run_id': agent_run.run_id, 'data': _facade()._enrich_confirmation_inner(confirm_inner, action='workflow_confirmation_required')}}
        agent_run_id = ''
        if decision.requires_confirmation and (not has_approval_requirement):
            from app.application.agent_orchestrator import AgentOrchestrator
            agent_run = AgentOrchestrator().start_run_from_plan(user_id=self._task_owner_id(user_id, runtime_ctx), message=message, plan=plan, runtime_context=runtime_ctx, auto_execute=True)
            if agent_run.status != 'waiting_user':
                return self._format_agent_run_response(plan, agent_run, thinking_steps=thinking_steps, user_message=str(message or ''))
            agent_run_id = agent_run.run_id
        if decision.requires_confirmation or has_approval_requirement:
            self._pending_workflows[user_id] = {'plan': plan, 'runtime_context': runtime_ctx, 'pending_id': _facade().uuid.uuid4().hex, 'agent_run_id': agent_run_id, 'thinking_steps': thinking_steps, 'approval_required': has_approval_requirement, 'approval_nodes': [{'node_id': n.node_id, 'tool_id': n.tool_id, 'action': n.action, 'params': n.params} for n in approval_required_nodes]}
            self._persist_plan_state(plan, runtime_ctx, status='pending_awaiting')
            todo_text = '\n'.join((f'- {step}' for step in plan.todo_steps or []))
            response_text = f"我已根据语义生成动态工作流计划：\n{thinking_steps}\n\n{todo_text}\n\n检测到中高风险步骤（{', '.join(decision.blocking_nodes)}），回复「确认」继续执行，回复「取消」终止。{(approval_info if has_approval_requirement else '')}"
            risk_inner = {'plan_id': plan.plan_id, 'intent': plan.intent, 'thinking_steps': thinking_steps, 'todo': plan.todo_steps, 'blocking_nodes': decision.blocking_nodes, 'reason': decision.reason, 'approval_required': has_approval_requirement, 'approval_nodes': [{'node_id': n.node_id, 'tool_id': n.tool_id, 'action': n.action} for n in approval_required_nodes]}
            confirmation_payload: dict[str, _facade().Any] = {'success': True, 'message': '处理完成', 'response': response_text, 'data': {'text': response_text, 'action': 'workflow_confirmation_required', 'data': _facade()._enrich_confirmation_inner(risk_inner, action='workflow_confirmation_required')}}
            if agent_run_id:
                payload_data = confirmation_payload['data']
                assert isinstance(payload_data, dict)
                confirmation_data = payload_data['data']
                assert isinstance(confirmation_data, dict)
                confirmation_payload['run_id'] = agent_run_id
                confirmation_payload['agent_run_id'] = agent_run_id
                payload_data['run_id'] = agent_run_id
                payload_data['agent_run_id'] = agent_run_id
                confirmation_data['run_id'] = agent_run_id
                confirmation_data['agent_run_id'] = agent_run_id
            return confirmation_payload
        agentic_pre_run = None
        if use_agentic:
            try:
                agentic_pre_run = self._start_agentic_workflow_agent_run(user_id=user_id, message=message, plan=plan, runtime_context=runtime_ctx)
                runtime_ctx['run_id'] = agentic_pre_run.run_id
                runtime_ctx['agent_run_id'] = agentic_pre_run.run_id
            except _facade().RECOVERABLE_ERRORS:
                _facade().logger.debug('Agentic workflow AgentRun pre-create skipped', exc_info=True)
        (run_result, state_updates) = self._run_workflow_with_state_updates(plan=plan, runtime_context=runtime_ctx, max_retries=1, agentic_loop=use_agentic, tool_registry=tool_registry, user_id=user_id)
        if use_agentic:
            agent_run = self._bridge_agentic_workflow_result_to_agent_run(user_id=user_id, message=message, plan=plan, run_result=run_result, runtime_context=runtime_ctx, agent_run=agentic_pre_run)
            return self._format_agent_run_response(plan, agent_run, thinking_steps=thinking_steps, user_message=str(message or ''))
        return self._format_workflow_run_response(plan, run_result, thinking_steps=thinking_steps, user_message=str(message or ''), state_updates=state_updates)

    def _build_workflow_thinking_steps(self, plan, decision_reason: str) -> str:
        node_lines = []
        for node in plan.nodes or []:
            deps = ','.join(node.depends_on) if node.depends_on else '无'
            node_lines.append(f'- 节点 {node.node_id}: {node.tool_id}.{node.action} (risk={node.risk}, depends_on={deps})')
        nodes_text = '\n'.join(node_lines) if node_lines else '- 无可执行节点'
        metadata = getattr(plan, 'metadata', {}) or {}
        user_memory_rag_summary = str(metadata.get('user_memory_rag_summary') or '').strip()
        memory_v2_summary = str(metadata.get('memory_v2_summary') or '').strip()
        tool_probe_outputs = metadata.get('tool_probe_outputs') or []
        if not isinstance(tool_probe_outputs, list):
            tool_probe_outputs = []
        probe_lines = []
        for item in tool_probe_outputs[:3]:
            if not isinstance(item, dict):
                continue
            tid = str(item.get('tool_id') or '').strip()
            action = str(item.get('action') or '').strip()
            ok = bool(item.get('success'))
            msg = str(item.get('message') or '').strip()
            preview = str(item.get('data_preview') or '').strip()
            if preview:
                preview = preview[:220] + ('…' if len(preview) > 220 else '')
            probe_lines.append(f'- {tid}.{action}: success={ok}; {msg} {preview}'.strip())
        memory_block = f'3.5) 用户记忆 RAG 概览:\n{user_memory_rag_summary}\n' if user_memory_rag_summary else ''
        memory_v2_block = f'3.6) Memory v2 已确认记忆:\n{memory_v2_summary}\n' if memory_v2_summary else ''
        probe_block = '3.7) 工具探测概览:\n' + ('\n'.join(probe_lines) if probe_lines else '- 无成功探测结果') + '\n'
        return f'思考步骤:\n1) 意图理解: {plan.intent}\n2) 计划生成: 基于工具注册表构建可执行节点图\n3) 风险判断: {decision_reason}\n{memory_block}{memory_v2_block}{probe_block}4) 执行编排: 按依赖顺序执行节点并传递上下文\n5) 节点图:\n{nodes_text}'

    def _workflow_products_float_query(self, plan, run_result, user_message: str) -> str:
        """从产品查询节点参数/结果或用户原话中提取副窗搜索词。"""
        for node in plan.nodes or []:
            if node.tool_id == 'products' and node.action == 'query':
                p = node.params or {}
                q = str(p.get('keyword') or '').strip() or str(p.get('model_number') or '').strip() or str(p.get('product_name') or p.get('name') or '').strip()
                if (q := self._normalize_product_query(q)):
                    return q
        for r in run_result.node_results:
            if not r.success or r.tool_id != 'products' or r.action != 'query':
                continue
            out = r.output or {}
            rows = out.get('data') or []
            if isinstance(rows, list) and rows:
                row = rows[0] if isinstance(rows[0], dict) else {}
                if isinstance(row, dict):
                    m = str(row.get('model_number') or '').strip()
                    n = str(row.get('name') or row.get('product_name') or '').strip()
                    if m:
                        return m
                if n:
                    return n
        return self._normalize_product_query(user_message)

    def _start_agentic_workflow_agent_run(self, *, user_id: str, message: str, plan, runtime_context: dict[str, _facade().Any]):
        from app.application.agent_orchestrator.run_models import AgentRun
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        repository = get_agent_run_repository()
        run = AgentRun(user_id=str(user_id or ''), message=str(message or ''), status='running', plan_id=str(getattr(plan, 'plan_id', '') or ''), intent=str(getattr(plan, 'intent', '') or 'agentic_workflow'), metadata={'runtime_context': dict(runtime_context or {}), 'trace_mode': 'agentic_loop_bridge', 'plan': {'todo_steps': list(getattr(plan, 'todo_steps', []) or []), 'risk_level': str(getattr(plan, 'risk_level', '') or ''), 'metadata': dict(getattr(plan, 'metadata', {}) or {})}})
        run.add_event('run.created', 'Agentic workflow run 已创建')
        run.add_event('planner.completed', 'Agentic workflow 计划已接管', {'plan_id': run.plan_id, 'intent': run.intent, 'source': 'workflow_engine.agentic_loop'})
        run.add_event('agentic_loop.started', 'Agentic workflow loop 开始执行', {'observed': True})
        return repository.save(run)

    def _bridge_agentic_workflow_result_to_agent_run(self, *, user_id: str, message: str, plan, run_result, runtime_context: dict[str, _facade().Any], agent_run=None):
        from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall, artifact_from_dict
        from app.application.agent_orchestrator.run_repository import get_agent_run_repository
        from app.application.agent_orchestrator.tool_spec import get_tool_action_spec
        repository = get_agent_run_repository()
        runtime_ctx = dict(runtime_context or {})
        run = agent_run
        if run is None:
            run = AgentRun(user_id=str(user_id or ''), message=str(message or ''), status='running', plan_id=str(getattr(plan, 'plan_id', '') or ''), intent=str(getattr(plan, 'intent', '') or 'agentic_workflow'), metadata={'runtime_context': dict(runtime_ctx), 'trace_mode': 'agentic_loop_bridge', 'plan': {'todo_steps': list(getattr(plan, 'todo_steps', []) or []), 'risk_level': str(getattr(plan, 'risk_level', '') or ''), 'metadata': dict(getattr(plan, 'metadata', {}) or {})}})
            run.add_event('run.created', 'Agentic workflow run 已创建')
            run.add_event('planner.completed', 'Agentic workflow 计划已接管', {'plan_id': run.plan_id, 'intent': run.intent, 'source': 'workflow_engine.agentic_loop'})
            run.add_event('agentic_loop.started', 'Agentic workflow loop 开始执行', {'observed': True})
        run.metadata['runtime_context'] = dict(runtime_ctx)
        run.metadata['trace_mode'] = 'agentic_loop_bridge'
        run.add_event('agentic_loop.completed', str(getattr(run_result, 'message', '') or 'AgenticLoop 已完成'), {'observed': True})
        node_outputs: dict[str, _facade().Any] = {}
        for result in getattr(run_result, 'node_results', []) or []:
            spec = get_tool_action_spec(result.tool_id, result.action)
            status: _facade().Literal['completed', 'failed'] = 'completed' if bool(getattr(result, 'success', False)) else 'failed'
            step = AgentStep(node_id=str(result.node_id or f'agent_{result.tool_id}_{result.action}'), tool_id=str(result.tool_id or ''), action=str(getattr(spec, 'action', '') or result.action or ''), params=dict(getattr(result, 'params', {}) or {}), risk=str(getattr(spec, 'risk', '') or 'medium'), idempotent=bool(getattr(spec, 'idempotent', False)), description='agentic loop observed tool execution', status=status, output=dict(getattr(result, 'output', {}) or {}), error=str(getattr(result, 'error', '') or ''), started_at=str(getattr(result, 'started_at', '') or ''), finished_at=str(getattr(result, 'finished_at', '') or ''), duration_ms=int(getattr(result, 'duration_ms', 0) or 0))
            if status == 'failed' and (not step.error):
                step.error = self._workflow_output_message(step.output) or 'tool failed'
            call = ToolCall(step_id=step.step_id, node_id=step.node_id, tool_id=step.tool_id, action=step.action, params=dict(step.params or {}), status='completed' if status == 'completed' else 'failed', output=dict(step.output or {}), error=step.error, cost_units=int(getattr(spec, 'cost_units', 0) or 0), permission=str(getattr(spec, 'permission', '') or ''), started_at=step.started_at or '', finished_at=step.finished_at or '', duration_ms=step.duration_ms, metadata={'observed': True, 'trace_mode': 'agentic_loop_bridge', 'retryable': bool(getattr(result, 'retryable', True)), 'retries': int(getattr(result, 'retries', 0) or 0), 'recovery_hint': str(getattr(result, 'recovery_hint', '') or '')})
            run.steps.append(step)
            run.tool_calls.append(call)
            node_outputs[step.node_id] = step.output
            run.add_event('tool.started', f'观察到 agentic 工具 {step.tool_id}.{step.action}', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': call.call_id, 'cost_units': call.cost_units, 'permission': call.permission, 'observed': True})
            run.add_event('tool.completed' if status == 'completed' else 'tool.failed', f'记录 agentic 工具 {step.tool_id}.{step.action}', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': call.call_id, 'duration_ms': step.duration_ms, 'cost_units': call.cost_units, 'observed': True, 'error': step.error})
            for artifact_payload in self._iter_agentic_artifact_payloads(step.output):
                artifact = artifact_from_dict(artifact_payload)
                if not artifact.artifact_type:
                    continue
                artifact.source = artifact.source or f'{step.tool_id}.{step.action}'
                artifact.metadata = {**dict(artifact.metadata or {}), 'step_id': step.step_id, 'call_id': call.call_id, 'trace_mode': 'agentic_loop_bridge'}
                run.artifacts.append(artifact)
                run.add_event('artifact.attached', f'Artifact 已附加: {artifact.artifact_type}', {'artifact_id': artifact.artifact_id, 'artifact_type': artifact.artifact_type, 'name': artifact.name, 'source': artifact.source})
        cost_units_total = sum((int(call.cost_units or 0) for call in run.tool_calls))
        run.metadata['tool_call_count'] = len(run.tool_calls)
        run.metadata['cost_units_total'] = cost_units_total
        run.metadata['artifact_count'] = len(run.artifacts)
        run.final_output = {'node_outputs': node_outputs, 'tool_calls': [call.to_dict() for call in run.tool_calls], 'artifacts': [artifact.to_dict() for artifact in run.artifacts], 'cost_units_total': cost_units_total, 'workflow_result': {'success': bool(getattr(run_result, 'success', False)), 'message': str(getattr(run_result, 'message', '') or ''), 'workflow_status': dict((getattr(run_result, 'final_context', {}) or {}).get('workflow_status') or {})}}
        run.status = 'completed' if bool(getattr(run_result, 'success', False)) else 'failed'
        if run.status == 'failed':
            run.error = str(getattr(run_result, 'message', '') or 'Agentic workflow failed')
            run.add_event('run.failed', run.error, run.final_output)
        else:
            run.add_event('run.completed', 'Agentic workflow run 执行完成', run.final_output)
        return repository.save(run)
