# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.workflow.planner')

class _LLMWorkflowPlannerPart01Mixin:

    def __init__(self) -> None:
        self._ai_service = _facade().get_ai_conversation_service()

    def plan(self, user_id: str, message: str, tool_registry: dict[str, _facade().Any], context: dict[str, _facade().Any] | None=None) -> _facade().PlanGraph:
        context = dict(context or {})
        session_key = str(context.get('session_id') or context.get('conversation_id') or '').strip()
        plan_id = f'wp-{session_key}-{_facade().uuid.uuid4().hex[:8]}' if session_key else f'wp-{_facade().uuid.uuid4().hex}'
        from app.application.normal_chat_dispatch import resolve_tool_execution_profile
        profile = resolve_tool_execution_profile(context)
        registry_for_plan = _facade()._filter_tool_registry_for_profile(tool_registry, profile)
        from app.application.normal_chat_dispatch import route_normal_mode_message
        _route = route_normal_mode_message(str(message or ''))
        if 'sales' in registry_for_plan and str(_route.get('intent') or '') == 'sales_write' and (str(_route.get('action') or '') == 'execute_closed_loop') and isinstance(_route.get('payload'), dict) and bool(_route.get('payload')):
            from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph
            return _facade().cast('PlanGraph', finalize_planned_graph(self._decorate_plan(self._fallback_plan(plan_id, message, registry_for_plan), message, registry_for_plan), plan_id=plan_id, context=context, validate=_facade().validate_plan_graph, fallback_factory=lambda : self._fallback_plan(plan_id, message, registry_for_plan), warn=_facade().logger.warning))
        try:
            from app.application import get_user_memory_rag_app_service
            rag = get_user_memory_rag_app_service()
            rag_res = rag.query(user_id=user_id, query_text=message, top_k=3)
            hits = (rag_res or {}).get('hits') if isinstance(rag_res, dict) else None
            if isinstance(hits, list) and hits:
                summary = rag.format_for_prompt(user_id=user_id, query_text=message, hits=hits, max_hits=4)
                context['user_memory_rag'] = {'summary': summary}
        except ImportError:
            _facade().logger.debug('用户记忆 RAG 服务不可用（不阻断主流程）')
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning('用户记忆 RAG 不可用（不阻断主流程）: %s', e)
        try:
            from app.services.user_memory_service import get_user_memory_service
            memory_v2_summary = get_user_memory_service().format_memory_v2_for_prompt(user_id=user_id, max_items=6)
            if '无已确认记忆' not in memory_v2_summary:
                context['memory_v2'] = {'summary': memory_v2_summary}
        except ImportError:
            _facade().logger.debug('Memory v2 服务不可用（不阻断主流程）')
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning('Memory v2 不可用（不阻断主流程）: %s', e)
        from app.domain.neuro.cognition.plan_graph_hooks import finalize_planned_graph
        planned = None
        if _facade()._looks_like_business_db_write(message, message.lower()) and 'business_db' in registry_for_plan:
            deterministic = self._fallback_plan(plan_id, message, registry_for_plan)
            if deterministic.intent == 'business_db_write' and deterministic.nodes:
                planned = deterministic
        if planned is None:
            planned = self._plan_with_react_multiagent(plan_id, user_id, message, registry_for_plan, context)
        return _facade().cast('PlanGraph', finalize_planned_graph(self._decorate_plan(planned, message, registry_for_plan), plan_id=plan_id, context=context, validate=_facade().validate_plan_graph, fallback_factory=lambda : self._fallback_plan(plan_id, message, registry_for_plan), warn=_facade().logger.warning))

    def _decorate_plan(self, plan: _facade().PlanGraph | None, message: str, tool_registry: dict[str, _facade().Any]) -> _facade().PlanGraph | None:
        """对规划产出的 PlanGraph 追加确定性条件边与反问澄清节点。

        不强行依赖 LLM 输出：条件边/反问节点由规则派生，保证行为可测、向后兼容。
        """
        if plan is None:
            return None
        plan = self._apply_conditional_edge_rules(plan, message, tool_registry)
        plan = self._apply_clarify_rules(plan, tool_registry)
        return plan

    def _apply_conditional_edge_rules(self, plan: _facade().PlanGraph, message: str, tool_registry: dict[str, _facade().Any]) -> _facade().PlanGraph:
        """确定性条件边规则：把"检查/查询 + 后续决策"表达为 branches。

        当前规则：计划含库存检查（query/read/check_stock）且消息带采购意图时，
        为检查节点挂上 ``{"key": "low_stock", "equals": true}`` → 采购节点 的条件边。
        """
        if any((k in message for k in ('库存', 'stock', 'Stock'))):
            check_nodes = [n for n in plan.nodes if str(n.action or '').lower() in ('query', 'read', 'check', 'check_stock') and 'stock' in str(n.tool_id or '').lower()]
            purchase_nodes = [n for n in plan.nodes if 'purchase' in str(n.tool_id or '').lower() or '采购' in (n.description or '')]
            if check_nodes and purchase_nodes:
                check = check_nodes[0]
                if not check.branches:
                    check.branches.append(_facade().Branch(target=purchase_nodes[0].node_id, condition={'key': 'low_stock', 'equals': True}))
        return plan

    def _apply_clarify_rules(self, plan: _facade().PlanGraph, tool_registry: dict[str, _facade().Any]) -> _facade().PlanGraph:
        """确定性反问规则：写/高风险节点存在关键参数缺失或多候选歧义时，在图首部插入 clarify 节点。

        复用 ``clarification_node.needs_clarification`` 检测，并用 ``build_clarify_node``
        生成反问节点，其 ``branches`` 依据用户确认结果路由回原操作节点。
        """
        items = _facade().needs_clarification(plan, tool_registry)
        from .clarification_node import detect_erp_clarification
        items = list(items) + detect_erp_clarification(plan)
        if not items:
            return plan
        inserted: list[_facade().WorkflowNode] = []
        for item in items:
            clarify = _facade().build_clarify_node(item['question'], ambient={'target_node_id': item['node_id']})
            plan.nodes.insert(0, clarify)
            inserted.append(clarify)
        if _facade().validate_plan_graph(plan) is not None:
            for clarify in inserted:
                if clarify in plan.nodes:
                    plan.nodes.remove(clarify)
        return plan

    def _plan_with_react_multiagent(self, plan_id: str, user_id: str, message: str, tool_registry: dict[str, _facade().Any], context: dict[str, _facade().Any]) -> _facade().PlanGraph | None:
        """
        多步 ReAct/CoT 风格规划（简化实现）：
        1) 先用 LLM 生成候选 PlanGraph（DecomposerAgent）。
        2) 基于候选 PlanGraph 抽取低风险只读节点做 ToolProbe（真实工具调用）。
        3) 将探测结果注入 prompt 再次规划得到最终 PlanGraph（PlanComposerAgent）。
        4) validate_plan_graph；失败则降级 fallback（CriticAgent）。
        """
        candidate = self._plan_with_llm(plan_id=plan_id, user_id=user_id, message=message, tool_registry=tool_registry, context=context)
        if candidate is None:
            return None
        runtime_context_for_probe = dict(context or {})
        runtime_context_for_probe['message'] = str(message or '')
        probe_requests: list[dict[str, _facade().Any]] = []
        for node in candidate.nodes or []:
            tid = str(node.tool_id or '').strip()
            act = str(node.action or '').strip()
            if not tid or not act:
                continue
            tool_spec = tool_registry.get(tid)
            if not isinstance(tool_spec, dict):
                continue
            actions = tool_spec.get('actions') or {}
            if not isinstance(actions, dict):
                continue
            meta = actions.get(act)
            if not isinstance(meta, dict):
                continue
            risk = str(meta.get('risk') or '').strip().lower()
            idempotent = bool(meta.get('idempotent', False))
            if risk != 'low' or not idempotent:
                continue
            if act not in ('query', 'exists', 'list', 'read', 'view', 'preview', 'decompose', 'extract', 'refresh_contact_cache', 'refresh_messages_cache'):
                continue
            probe_requests.append({'tool_id': tid, 'action': act, 'params': node.params or {}})
        probe_requests = probe_requests[:3]
        probe_outputs: list[dict[str, _facade().Any]] = []
        task_agent = None
        try:
            from app.services.task_agent import TaskAgent
            task_agent = TaskAgent()
        except ImportError:
            _facade().logger.debug('TaskAgent 服务不可用')
            task_agent = None
        except RuntimeError as e:
            _facade().logger.warning('TaskAgent 初始化失败: %s', e)
            task_agent = None
        for pr in probe_requests:
            try:
                tool_id = str(pr.get('tool_id') or '').strip()
                action = str(pr.get('action') or '').strip()
                raw_params = pr.get('params')
                params: dict[str, _facade().Any] = dict(raw_params) if isinstance(raw_params, dict) else {}
                tool_spec = tool_registry.get(tool_id) or {}
                actions = tool_spec.get('actions') or {}
                action_meta = actions.get(action) if isinstance(actions, dict) else None
                if not isinstance(action_meta, dict):
                    continue
                risk = str(action_meta.get('risk') or '').strip().lower()
                idempotent = bool(action_meta.get('idempotent', False))
                if risk != 'low' or not idempotent:
                    continue
                required_params = action_meta.get('required_params') or []
                if not isinstance(required_params, list):
                    required_params = []
                missing_required = []
                for k in required_params:
                    if k not in (params or {}) or params.get(k) is None or str(params.get(k)).strip() == '':
                        missing_required.append(k)
                if missing_required:
                    continue
                if tool_id == 'products' and action == 'query':
                    if not ((params or {}).get('keyword') or (params or {}).get('model_number') or (params or {}).get('unit_name')):
                        try:
                            from app.application.normal_chat_dispatch import route_normal_mode_message
                            rr = route_normal_mode_message(message)
                            if rr.get('intent') == 'product_query':
                                slots = rr.get('slots') or {}
                                (params or {}).update({'keyword': slots.get('keyword') or (params or {}).get('keyword') or '', 'model_number': slots.get('model_number') or (params or {}).get('model_number') or '', 'unit_name': slots.get('unit_name') or (params or {}).get('unit_name') or ''})
                        except (ImportError, RuntimeError):
                            if not (params or {}).get('keyword'):
                                params['keyword'] = str(message or '').strip()[:80]
                if tool_id == 'customers' and action == 'query':
                    if not ((params or {}).get('keyword') or params.get('customer_name')) and task_agent is not None:
                        try:
                            cust_slots = task_agent._extract_customer_query_slots(str(message or ''))
                            if isinstance(cust_slots, dict):
                                extracted_kw = str(cust_slots.get('keyword') or cust_slots.get('customer_name') or '').strip()
                                msg_trim = str(message or '').strip()
                                if extracted_kw and extracted_kw != msg_trim:
                                    params['keyword'] = extracted_kw
                        except (ImportError, RuntimeError):
                            (params or {}).pop('keyword', None)
                from app.application.facades.tools_facade import execute_registered_workflow_tool
                merged_params = dict(params or {})
                merged_params['_runtime_context'] = dict(runtime_context_for_probe)
                out = execute_registered_workflow_tool(tool_id=tool_id, action=action, params=merged_params)
                data_preview = ''
                if isinstance(out, dict):
                    data_value = out.get('data')
                    if isinstance(data_value, list):
                        data_preview = str(data_value[:3])[:600]
                    elif data_value is not None:
                        data_preview = str(data_value)[:600]
                    elif out.get('raw') is not None:
                        data_preview = str(out.get('raw'))[:600]
                    else:
                        data_preview = str(out)[:600]
                if isinstance(out, dict) and out.get('success') is True:
                    probe_outputs.append({'tool_id': tool_id, 'action': action, 'success': True, 'message': str((out or {}).get('message') or (out or {}).get('error') or ''), 'data_preview': data_preview})
            except (ValueError, TypeError) as e:
                _facade().logger.debug('ToolProbe 参数错误（将跳过注入）: %s', e)
                continue
            except RuntimeError as e:
                _facade().logger.warning('ToolProbe 运行时错误（将跳过注入）: %s', e)
                continue
        context_for_compose = dict(context or {})
        if probe_outputs:
            context_for_compose['tool_probe_outputs'] = probe_outputs
        final_plan = self._plan_with_llm(plan_id=plan_id, user_id=user_id, message=message, tool_registry=tool_registry, context=context_for_compose)
        if final_plan is None:
            return None
        err = _facade().validate_plan_graph(final_plan)
        if err is None:
            err = self._validate_required_params(final_plan, tool_registry)
        if err is None:
            return final_plan
        _facade().logger.warning('CriticAgent 校验失败，尝试 LLM 修复（最多 1 次）: %s', err)
        repaired = self._critic_repair_with_llm(plan_id=plan_id, user_id=user_id, message=message, tool_registry=tool_registry, context=context_for_compose, error=err, invalid_plan=final_plan)
        if repaired is not None:
            err2 = _facade().validate_plan_graph(repaired)
            if err2 is None:
                err2 = self._validate_required_params(repaired, tool_registry)
            if err2 is None:
                return repaired
        _facade().logger.warning('CriticAgent 修复失败（回退 fallback）: %s', err)
        return None

    @staticmethod
    def _validate_required_params(plan: _facade().PlanGraph, tool_registry: dict[str, _facade().Any]) -> str | None:
        """检查节点 params 是否满足 tool_registry 的 required_params。"""
        for node in plan.nodes or []:
            tool_spec = (tool_registry or {}).get(str(node.tool_id) or '')
            if not isinstance(tool_spec, dict):
                continue
            actions = tool_spec.get('actions') or {}
            if not isinstance(actions, dict):
                continue
            action_meta = actions.get(str(node.action) or '')
            if not isinstance(action_meta, dict):
                continue
            required_params = action_meta.get('required_params') or []
            if not isinstance(required_params, list):
                required_params = []
            params = node.params or {}
            for key in required_params:
                if key not in params or params.get(key) is None or str(params.get(key)).strip() == '':
                    return f'节点 {node.node_id} 缺少 required_params: {key}'
        return None

    def _critic_repair_with_llm(self, plan_id: str, user_id: str, message: str, tool_registry: dict[str, _facade().Any], context: dict[str, _facade().Any], error: str, invalid_plan: _facade().PlanGraph) -> _facade().PlanGraph | None:
        """CriticAgent：LLM 修复无效 PlanGraph（只重试一次）。"""
        api_key = getattr(self._ai_service, 'api_key', '') or ''
        if not api_key:
            return None
        try:
            tool_specs = []
            for (tool_id, spec) in tool_registry.items():
                actions = spec.get('actions') or {}
                action_specs = []
                for (action_name, action_meta) in actions.items():
                    if not isinstance(action_meta, dict):
                        continue
                    action_specs.append({'action': action_name, 'risk': action_meta.get('risk', 'low'), 'idempotent': bool(action_meta.get('idempotent', False)), 'required_params': action_meta.get('required_params', [])})
                tool_specs.append({'tool_id': tool_id, 'description': spec.get('description', ''), 'actions': action_specs})
            invalid_dict = {'plan_id': invalid_plan.plan_id, 'intent': invalid_plan.intent, 'todo_steps': invalid_plan.todo_steps, 'risk_level': invalid_plan.risk_level, 'nodes': [{'node_id': n.node_id, 'tool_id': n.tool_id, 'action': n.action, 'params': n.params, 'risk': n.risk, 'idempotent': n.idempotent, 'description': n.description, 'depends_on': n.depends_on} for n in invalid_plan.nodes or []]}
            prompt = {'task': '修复一个无效的工作流 PlanGraph JSON，使其满足 validate_plan_graph 规则且满足 required_params 约束。', 'rules': ['只输出 JSON，不要 markdown。', 'node_id 必须唯一且非空。', '所有 nodes 项必须包含 tool_id/action/params/risk/idempotent/description/depends_on 结构字段。', '对于 required_params：必须在 params 中提供非空值（若无法从 user_message 推断，仍需给出最合理的非空占位/默认值，保证结构字段不缺失）。', '员工相关意图优先使用 employee.list/employee.execute；不知道 employee_id 时先 list，不要伪造员工 ID。', '数据库读写必须使用 business_db.read/write 的 entity/operation/payload 结构，不得生成 sql/raw_sql/query_sql。', 'business_db.write 只在用户明确要求新增/添加/写入/入库/删除/更新时使用；普通查询使用 business_db.read。'], 'validation_error': error, 'invalid_plan': invalid_dict, 'user_message': message, 'context': context, 'tool_registry': tool_specs, 'output_schema': {'intent': 'string', 'todo_steps': ['string'], 'risk_level': 'low|medium|high', 'nodes': [{'node_id': 'string', 'tool_id': 'string', 'action': 'string', 'params': {}, 'risk': 'low|medium|high', 'idempotent': 'bool', 'description': 'string', 'depends_on': ['node_id']}]}}
            messages = [{'role': 'system', 'content': '你是工作流计划修复器，只输出可执行 JSON。'}, {'role': 'user', 'content': _facade().json.dumps(prompt, ensure_ascii=False)}]
            from app.infrastructure.llm.providers.credentials import default_chat_completions_url
            api_url = getattr(self._ai_service, 'api_url', '') or default_chat_completions_url()
            response = _facade()._get_planner_http_client().post(api_url, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}, json={'model': getattr(self._ai_service, 'model', '') or 'deepseek-chat', 'messages': messages, 'temperature': 0.2, 'max_tokens': 1000})
            if response.status_code >= 400:
                return None
            response_data = response.json()
            raw = (response_data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
            if not raw:
                return None
            raw = raw.removeprefix('```json').removeprefix('```').removesuffix('```').strip()
            parsed = _facade().json.loads(raw)
            nodes: list[_facade().WorkflowNode] = []
            for (idx, node) in enumerate(parsed.get('nodes', []), start=1):
                nodes.append(_facade().WorkflowNode(node_id=str(node.get('node_id') or f'node_{idx}'), tool_id=str(node.get('tool_id') or ''), action=str(node.get('action') or ''), params=node.get('params') or {}, risk=_facade().normalize_workflow_risk(str(node.get('risk') or 'low')), idempotent=bool(node.get('idempotent', False)), description=str(node.get('description') or ''), depends_on=[str(x) for x in node.get('depends_on') or []]))
            return _facade().PlanGraph(plan_id=plan_id, intent=str(parsed.get('intent') or invalid_plan.intent or 'dynamic_workflow'), todo_steps=[str(x) for x in parsed.get('todo_steps') or invalid_plan.todo_steps or []], nodes=nodes, risk_level=_facade().normalize_workflow_risk(str(parsed.get('risk_level') or invalid_plan.risk_level or 'low')), metadata={'planner': 'critic_repair', 'message': message})
        except (ValueError, TypeError) as e:
            _facade().logger.debug('CriticAgent 修复参数错误: %s', e)
            return None
        except RuntimeError as e:
            _facade().logger.warning('CriticAgent 修复运行时错误: %s', e)
            return None

    def _plan_with_llm(self, plan_id: str, user_id: str, message: str, tool_registry: dict[str, _facade().Any], context: dict[str, _facade().Any]) -> _facade().PlanGraph | None:
        try:
            tool_specs = []
            for (tool_id, spec) in tool_registry.items():
                actions = spec.get('actions', {})
                action_specs = []
                for (action_name, action_meta) in actions.items():
                    action_specs.append({'action': action_name, 'risk': action_meta.get('risk', 'low'), 'idempotent': bool(action_meta.get('idempotent', False)), 'required_params': action_meta.get('required_params', [])})
                tool_specs.append({'tool_id': tool_id, 'description': spec.get('description', ''), 'actions': action_specs})
            recent_messages = []
            conv_ctx = self._ai_service.get_context(user_id)
            if conv_ctx and conv_ctx.conversation_history:
                recent_messages = conv_ctx.conversation_history[-6:]
            prompt = {'task': '根据用户意图生成可执行工作流计划（JSON）。', 'rules': ['只输出 JSON，不要 markdown。', '优先使用 tool_registry 中已有工具与 action。', '如果步骤有依赖，写到 depends_on。', 'todo_steps 要贴合用户语义，不要模板化。', 'risk_level 按节点最高风险确定。', '员工相关意图：若用户只是问有哪些员工，使用 employee.list；若明确指定 employee_id/pack_id 并要求执行，使用 employee.execute 并填写 task；不知道员工 ID 时先 list，不要编造。', '数据库相关意图：读数据库/查库使用 business_db.read，并填写 entity；写入/新增/更新/删除/入库才使用 business_db.write，并填写 entity、operation、payload。', 'business_db 只能访问 customers/products/materials/shipment_records；禁止生成 sql/raw_sql/query_sql 或任意 SQL。', '对 products.query：必须在 params 填入 keyword 或 model_number 等检索词；对 customers.query：列表/计数问法可不填 keyword（空=全部客户）；指名查询再填 keyword，从用户话中提取（如「七彩乐园的9803」→ keyword 含单位+型号），禁止留空对象 {}。', '如果 context 中包含 tool_probe_outputs 且其中 success=true，请优先使用其中 data_preview 的信息来补全 nodes.params。', '如果 context 中包含 memory_v2.summary，只能把其中已确认 active 记忆用于补全偏好、客户别名、产品习惯或任务上下文；禁止使用未确认候选或编造记忆。', '若 context 中 tool_execution_profile 为 normal 或 ui_surface 为 normal 且 intent_channel 为 pro：仅可使用 availability 为 shared 或 normal_only 的工具；产品查询优先 normal_slot_dispatch.product_query 或 products.query。', '若 context 为全专业链路（未带上述混合标记）：仅使用 shared 或 pro_only，勿选 normal_only。'], 'user_message': message, 'recent_messages': recent_messages, 'context': context, 'tool_probe_outputs': (context or {}).get('tool_probe_outputs') if isinstance(context, dict) else [], 'tool_registry': tool_specs, 'output_schema': {'intent': 'string', 'todo_steps': ['string'], 'risk_level': 'low|medium|high', 'nodes': [{'node_id': 'string', 'tool_id': 'string', 'action': 'string', 'params': {}, 'risk': 'low|medium|high', 'idempotent': 'bool', 'description': 'string', 'depends_on': ['node_id']}]}}
            messages = [{'role': 'system', 'content': '你是工作流规划器，只输出可执行 JSON。'}, {'role': 'user', 'content': _facade().json.dumps(prompt, ensure_ascii=False)}]
            response_data = _facade().request_planner_completion(ai_service=self._ai_service, context=context, messages=messages, http_client_factory=_facade()._get_planner_http_client)
            if response_data is None:
                return None
            raw = (response_data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
            if not raw:
                return None
            raw = raw.removeprefix('```json').removeprefix('```').removesuffix('```').strip()
            parsed = _facade().json.loads(raw)
            nodes: list[_facade().WorkflowNode] = []
            for (idx, node) in enumerate(parsed.get('nodes', []), start=1):
                nodes.append(_facade().WorkflowNode(node_id=str(node.get('node_id') or f'node_{idx}'), tool_id=str(node.get('tool_id') or ''), action=str(node.get('action') or ''), params=node.get('params') or {}, risk=_facade().normalize_workflow_risk(str(node.get('risk') or 'low')), idempotent=bool(node.get('idempotent', False)), description=str(node.get('description') or ''), depends_on=[str(x) for x in node.get('depends_on') or []]))
            tool_probe_outputs: list[dict[str, _facade().Any]] = []
            user_memory_rag_summary = ''
            memory_v2_summary = ''
            try:
                if isinstance(context, dict):
                    user_memory_rag = context.get('user_memory_rag')
                    if isinstance(user_memory_rag, dict):
                        user_memory_rag_summary = str(user_memory_rag.get('summary') or '').strip()
                    memory_v2 = context.get('memory_v2')
                    if isinstance(memory_v2, dict):
                        memory_v2_summary = str(memory_v2.get('summary') or '').strip()
                    tpo = context.get('tool_probe_outputs')
                    if isinstance(tpo, list):
                        tool_probe_outputs = []
                        for item in tpo[:2]:
                            if not isinstance(item, dict):
                                continue
                            tool_probe_outputs.append({'tool_id': item.get('tool_id'), 'action': item.get('action'), 'success': bool(item.get('success')), 'message': str(item.get('message') or '').strip()[:120], 'data_preview': str(item.get('data_preview') or '').strip()[:160]})
            except (ImportError, RuntimeError):
                tool_probe_outputs = []
                user_memory_rag_summary = ''
                memory_v2_summary = ''
            return _facade().PlanGraph(plan_id=plan_id, intent=str(parsed.get('intent') or 'dynamic_workflow'), todo_steps=[str(x) for x in parsed.get('todo_steps') or []], nodes=nodes, risk_level=_facade().normalize_workflow_risk(str(parsed.get('risk_level') or 'low')), metadata={'planner': 'llm', 'message': message, 'user_memory_rag_summary': user_memory_rag_summary, 'memory_v2_summary': memory_v2_summary, 'tool_probe_outputs': tool_probe_outputs})
        except (ValueError, TypeError) as err:
            _facade().logger.debug('LLM 规划参数错误，回退规则规划: %s', err)
            return None
        except RuntimeError as err:
            _facade().logger.warning('LLM 规划运行时错误，回退规则规划: %s', err)
            return None
