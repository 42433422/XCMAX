# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.workflow.engine')

class _WorkflowEnginePart01Mixin:

    def __init__(self, tool_dispatcher, state_event_callback: _facade().Any | None=None) -> None:
        self._dispatch = tool_dispatcher
        self._default_state_schema = _facade().DEFAULT_STATE_SCHEMA
        self._state_event_callback = state_event_callback

    def run(self, plan: _facade().PlanGraph, runtime_context: dict[str, _facade().Any] | None=None, max_retries: int=1, agentic_loop: bool=False, tool_registry: dict[str, _facade().Any] | None=None, user_id: str | None=None, state_schema: _facade().StateSchema | None=None, parallel: bool=True, checkpointer: _facade().Any | None=None, state_event_callback: _facade().Any | None=None) -> _facade().WorkflowRunResult:
        previous_callback = self._state_event_callback
        if state_event_callback is not None:
            self._state_event_callback = state_event_callback
        try:
            if agentic_loop and tool_registry:
                return self._run_agentic_loop(plan, runtime_context, max_retries, tool_registry, user_id, state_schema)
            return self._run_batch(plan, runtime_context, max_retries, state_schema, parallel, checkpointer=checkpointer)
        finally:
            self._state_event_callback = previous_callback

    def _run_batch(self, plan: _facade().PlanGraph, runtime_context: dict[str, _facade().Any] | None=None, max_retries: int=1, state_schema: _facade().StateSchema | None=None, parallel: bool=True, checkpointer: _facade().Any | None=None, resume_state: dict[str, _facade().Any] | None=None) -> _facade().WorkflowRunResult:
        if resume_state is not None:
            runtime_context = dict(resume_state.get('runtime_context') or {})
            executed: set[str] = set(resume_state.get('executed', set()))
            blocked: set[str] = set(resume_state.get('blocked', set()))
        else:
            runtime_context = dict(runtime_context or {})
            executed = set()
            blocked = set()
        schema = state_schema or self._default_state_schema
        node_results: list[_facade().NodeExecutionResult] = []
        pending: dict[str, _facade().WorkflowNode] = {node.node_id: node for node in plan.nodes if node.node_id not in executed}
        stalled_rounds = 0

        def _is_write_node(node: _facade().WorkflowNode) -> bool:
            return node.risk == 'high' or not node.idempotent

        def _ready(node: _facade().WorkflowNode) -> bool:
            return node.node_id not in blocked and all((dep in executed for dep in node.depends_on))
        while pending:
            stalled = True
            progressed = False
            while True:
                ready_routers = [node for node in pending.values() if (node.branches or node.next is not None) and _ready(node)]
                if not ready_routers:
                    break
                stalled = False
                progressed = True
                for node in ready_routers:
                    result = self._run_node(node, runtime_context, max_retries=max_retries)
                    self._record_result(result, runtime_context, schema, node_results, executed, pending)
                    if not result.success:
                        return self._fail_run(plan, node_results, runtime_context, result)
                    self._advance_router(node, result.output, pending, blocked)
            ready_non_routers = [node for node in pending.values() if not (node.branches or node.next is not None) and _ready(node)]
            if ready_non_routers:
                stalled = False
                progressed = True
                read_nodes = [n for n in ready_non_routers if not _is_write_node(n)]
                write_nodes = [n for n in ready_non_routers if _is_write_node(n)]
                failed = self._run_ready_batch(read_nodes, write_nodes, runtime_context, max_retries, parallel, schema, node_results, executed, pending)
                if failed is not None:
                    return self._fail_run(plan, node_results, runtime_context, failed)
            if progressed:
                self._maybe_checkpoint(checkpointer, plan, runtime_context, executed, blocked)
            if stalled:
                stalled_rounds += 1
                if stalled_rounds > 1:
                    unresolved = ','.join(pending.keys())
                    runtime_context['workflow_status'] = {'state': 'blocked', 'unresolved_nodes': list(pending.keys()), 'message': f'工作流依赖无法继续解析: {unresolved}'}
                    return _facade().WorkflowRunResult(plan_id=plan.plan_id, success=False, node_results=node_results, final_context=runtime_context, message=f'工作流依赖无法继续解析: {unresolved}')
            else:
                stalled_rounds = 0
        runtime_context['workflow_status'] = {'state': 'completed', 'executed_nodes': list(executed), 'message': '工作流执行完成'}
        self._maybe_checkpoint(checkpointer, plan, runtime_context, executed, blocked)
        return _facade().WorkflowRunResult(plan_id=plan.plan_id, success=True, node_results=node_results, final_context=runtime_context, message='工作流执行完成')

    @staticmethod
    def _maybe_checkpoint(checkpointer: _facade().Any, plan: _facade().PlanGraph, runtime_context: dict[str, _facade().Any], executed: set[str], blocked: set[str]) -> str | None:
        """若提供了 checkpointer，记录一次 checkpoint；否则返回 None。"""
        if checkpointer is None:
            return None
        checkpoint_id = checkpointer.save_checkpoint(plan.plan_id, len(executed), runtime_context, sorted(executed), blocked=sorted(blocked))
        return str(checkpoint_id) if checkpoint_id is not None else None

    def resume_run(self, plan: _facade().PlanGraph, checkpoint_id: str, *, checkpointer: _facade().Any, max_retries: int=1, state_schema: _facade().StateSchema | None=None, parallel: bool=True) -> _facade().WorkflowRunResult:
        """从指定 checkpoint 断点续跑。

        恢复 ``runtime_context`` 与 ``executed_nodes``，只执行尚未完成的节点，
        不重复执行已完成节点。
        """
        if checkpointer is None:
            return _facade().WorkflowRunResult(plan_id=plan.plan_id, success=False, message='resume_run 需要 checkpointer')
        checkpoint = checkpointer.get_checkpoint(plan.plan_id, checkpoint_id)
        if checkpoint is None:
            return _facade().WorkflowRunResult(plan_id=plan.plan_id, success=False, message=f'checkpoint 不存在: {checkpoint_id}')
        resume_state: dict[str, _facade().Any] = {'runtime_context': checkpoint.get('runtime_context') or {}, 'executed': list(checkpoint.get('executed_nodes') or []), 'blocked': list(checkpoint.get('blocked') or [])}
        return self._run_batch(plan, max_retries=max_retries, state_schema=state_schema, parallel=parallel, checkpointer=checkpointer, resume_state=resume_state)

    def replay_run(self, plan_id: str, checkpoint_id: str | None=None, *, checkpointer: _facade().Any) -> _facade().WorkflowRunResult:
        """只读重放 checkpoint 中已执行节点的输出历史（不真正再执行工具）。

        用于审计/回归：重放结果（node_results + final_context）与原始运行一致。
        未指定 ``checkpoint_id`` 时使用最新 checkpoint。
        """
        if checkpointer is None:
            return _facade().WorkflowRunResult(plan_id=plan_id, success=False, message='replay_run 需要 checkpointer')
        if checkpoint_id is not None:
            checkpoint = checkpointer.get_checkpoint(plan_id, checkpoint_id)
        else:
            checkpoint = getattr(checkpointer, 'latest_checkpoint', lambda p: None)(plan_id)
        if checkpoint is None:
            return _facade().WorkflowRunResult(plan_id=plan_id, success=False, message='checkpoint 不存在，无法重放')
        rc = checkpoint.get('runtime_context') or {}
        traces = rc.get('workflow_trace') or []
        outputs = rc.get('node_outputs') or {}
        node_results: list[_facade().NodeExecutionResult] = []
        for tr in traces:
            node_id = str(tr.get('node_id', ''))
            output = outputs.get(node_id, {})
            node_results.append(_facade().NodeExecutionResult(node_id=node_id, success=bool(tr.get('success')), tool_id=str(tr.get('tool_id', '')), action=str(tr.get('action', '')), output=output if isinstance(output, dict) else {}, error=str(tr.get('error', '')), retries=int(tr.get('retries', 0)), retryable=bool(tr.get('retryable')), recovery_hint=str(tr.get('recovery_hint', '')), duration_ms=int(tr.get('duration_ms', 0))))
        workflow_status = rc.get('workflow_status') or {}
        success = bool(node_results) and workflow_status.get('state') == 'completed'
        return _facade().WorkflowRunResult(plan_id=plan_id, success=success, node_results=node_results, final_context=dict(rc), message='重放自 checkpoint')

    def _run_ready_batch(self, read_nodes: list[_facade().WorkflowNode], write_nodes: list[_facade().WorkflowNode], runtime_context: dict[str, _facade().Any], max_retries: int, parallel: bool, schema: _facade().StateSchema, node_results: list[_facade().NodeExecutionResult], executed: set[str], pending: dict[str, _facade().WorkflowNode]) -> _facade().NodeExecutionResult | None:
        """并发/串行执行就绪节点并归并上下文；返回首个失败节点结果，全部成功返回 None。"""
        batch_results: list[_facade().NodeExecutionResult] = []
        if read_nodes and parallel:
            try:
                requested_workers = int(runtime_context.get('max_parallel_workers') or 4)
            except (TypeError, ValueError):
                requested_workers = 4
            max_workers = max(1, min(requested_workers, 8, len(read_nodes)))
            if len(read_nodes) > 1:
                runtime_context.setdefault('parallel_batches', []).append({'node_ids': [node.node_id for node in read_nodes], 'max_workers': max_workers})
            with _facade().ThreadPoolExecutor(max_workers=max_workers) as executor:
                read_map = {node.node_id: node for node in read_nodes}
                future_map = {node_id: executor.submit(self._run_node, node, runtime_context, max_retries=max_retries) for (node_id, node) in read_map.items()}
                for node in read_nodes:
                    batch_results.append(future_map[node.node_id].result())
        else:
            for node in read_nodes:
                batch_results.append(self._run_node(node, runtime_context, max_retries=max_retries))
        for node in write_nodes:
            batch_results.append(self._run_node(node, runtime_context, max_retries=max_retries))
        for result in batch_results:
            self._record_result(result, runtime_context, schema, node_results, executed, pending)
            if not result.success:
                return result
        return None

    def _record_result(self, result: _facade().NodeExecutionResult, runtime_context: dict[str, _facade().Any], schema: _facade().StateSchema, node_results: list[_facade().NodeExecutionResult], executed: set[str], pending: dict[str, _facade().WorkflowNode]) -> None:
        """记录节点结果并归并上下文（主线程统一执行，避免并发写冲突）。"""
        node_results.append(result)
        executed.add(result.node_id)
        pending.pop(result.node_id, None)
        runtime_context.setdefault('node_outputs', {})
        runtime_context['node_outputs'][result.node_id] = result.output
        self._append_node_trace(runtime_context, result)
        self._merge_state_schema(runtime_context, result, schema)
        self._emit_state_update(result)

    def _emit_state_update(self, result: _facade().NodeExecutionResult) -> None:
        """节点完成后回调 ``state.update`` 事件（成功与失败均触发；回调异常不影响主流程）。"""
        callback = self._state_event_callback
        if callback is None:
            return
        try:
            callback({'type': 'state.update', 'node_id': result.node_id, 'status': 'succeeded' if result.success else 'failed', 'output_summary': self._summarize_output(result.output)})
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning('state_event_callback failed node=%s', result.node_id, exc_info=True)

    @staticmethod
    def _fail_run(plan: _facade().PlanGraph, node_results: list[_facade().NodeExecutionResult], runtime_context: dict[str, _facade().Any], result: _facade().NodeExecutionResult) -> _facade().WorkflowRunResult:
        runtime_context['workflow_status'] = {'state': 'failed', 'failed_node_id': result.node_id, 'message': result.error, 'recovery_hint': result.recovery_hint}
        return _facade().WorkflowRunResult(plan_id=plan.plan_id, success=False, node_results=node_results, final_context=runtime_context, message=f'节点 {result.node_id} 执行失败: {result.error}')

    def _advance_router(self, node: _facade().WorkflowNode, output: dict[str, _facade().Any], pending: dict[str, _facade().WorkflowNode], blocked: set[str]) -> str | None:
        """按 output 决定条件边后继，并屏蔽未选中的分支目标；返回选中的 target node_id。

        优先匹配 branches[].condition；无匹配则用 next；next 为空返回 None（正常结束）。
        """
        chosen = self._resolve_successor(node, output)
        candidates = self._branch_candidates(node)
        for cand in candidates:
            if cand != chosen:
                blocked.add(cand)
                pending.pop(cand, None)
        return chosen

    @staticmethod
    def _resolve_successor(node: _facade().WorkflowNode, output: dict[str, _facade().Any]) -> str | None:
        target = _facade().WorkflowEngine.evaluate_branch(node, output)
        if target is not None:
            return target
        return node.next

    @staticmethod
    def evaluate_branch(node: _facade().WorkflowNode, output: dict[str, _facade().Any]) -> str | None:
        """按 output 匹配 node.branches 中第一条成功的 condition，返回 target node_id；无匹配返回 None。"""
        if not isinstance(output, dict):
            output = {}
        for branch in node.branches:
            if _facade().WorkflowEngine._condition_matches(branch.condition, output):
                return branch.target
        return None

    @staticmethod
    def _condition_matches(condition: dict[str, _facade().Any], output: dict[str, _facade().Any]) -> bool:
        if not isinstance(condition, dict):
            return False
        key = condition.get('key')
        if key is None or not isinstance(key, str):
            return False
        expected = condition.get('equals', condition.get('value'))
        return output.get(key) == expected

    @staticmethod
    def _branch_candidates(node: _facade().WorkflowNode) -> list[str]:
        cands: list[str] = []
        if node.next is not None:
            cands.append(node.next)
        for branch in node.branches:
            cands.append(branch.target)
        return cands

    def _run_agentic_loop(self, plan: _facade().PlanGraph, runtime_context: dict[str, _facade().Any] | None, max_retries: int, tool_registry: dict[str, _facade().Any], user_id: str | None, state_schema: _facade().StateSchema | None=None) -> _facade().WorkflowRunResult:
        from .agent_loop import run_agentic_loop
        return run_agentic_loop(self, _facade().logger, plan, runtime_context, max_retries, tool_registry, user_id, state_schema)

    def _llm_decide_next_step(self, user_message: str, tool_registry: dict[str, _facade().Any], runtime_context: dict[str, _facade().Any], agent_history: list[dict[str, _facade().Any]], user_id: str | None) -> dict[str, _facade().Any] | None:
        """
        询问 LLM：下一步做什么（单步决策）。
        返回 {"action": "done"} 表示结束，或 {"tool_id": "...", "action": "...", "params": {...}, "reasoning": "..."}
        """
        ai_service = _facade().get_ai_conversation_service()
        api_key = getattr(ai_service, 'api_key', '') or ''
        if not api_key:
            _facade().logger.warning('AgenticLoop 缺少 API_KEY，跳过')
            return None
        tool_specs = []
        for (tid, spec) in tool_registry.items():
            if not isinstance(spec, dict):
                continue
            actions = spec.get('actions') or {}
            action_list = []
            for (aname, ameta) in actions.items():
                if not isinstance(ameta, dict):
                    continue
                action_list.append({'action': aname, 'risk': ameta.get('risk', 'low'), 'idempotent': bool(ameta.get('idempotent', False)), 'required_params': ameta.get('required_params', [])})
            tool_specs.append({'tool_id': tid, 'description': spec.get('description', ''), 'actions': action_list})
        history_lines = []
        for h in agent_history[-8:]:
            role = h.get('role', '')
            if role == 'done':
                history_lines.append('Assistant: 已完成任务')
            elif role == 'assistant':
                history_lines.append(f"Assistant: 决定执行 {h.get('tool_id')}.{h.get('action')} (reasoning: {h.get('reasoning', '')[:80]})")
            else:
                history_lines.append(f"System: {h.get('content', '')[:200]}")
        excel_analysis = runtime_context.get('excel_analysis')
        excel_info = ''
        if isinstance(excel_analysis, dict):
            fp = excel_analysis.get('file_path', '')
            excel_info = f'\n当前 Excel 文件: {fp}'
        prompt = {'task': '作为 Agent，决定下一步动作。', 'rules': ['如果任务已完成，返回 {"action": "done"}。', '如果需要执行工具，返回 {"tool_id": "...", "action": "...", "params": {...}, "reasoning": "..."}。', 'params 必须填写所有 required_params（不能留空）。', '优先使用低风险、幂等工具。', '只决定下一步，不要一次决定多步。'], 'user_message': user_message, 'excel_context': excel_info, 'recent_history': '\n'.join(history_lines) if history_lines else '(首步决策)', 'tool_registry': tool_specs, 'output_schema': {'action': 'done | execute', 'tool_id': 'string (当 action=execute 时)', 'action_name': 'string (当 action=execute 时)', 'params': '{} (当 action=execute 时)', 'reasoning': 'string'}}
        messages = [{'role': 'system', 'content': '你是工作流 Agent，只输出 JSON。'}, {'role': 'user', 'content': _facade().json.dumps(prompt, ensure_ascii=False)}]
        try:
            from app.infrastructure.llm.providers.credentials import default_chat_completions_url
            api_url = getattr(ai_service, 'api_url', '') or default_chat_completions_url()
            model = getattr(ai_service, 'model', '') or 'deepseek-chat'
            response = _facade()._get_sync_http_client().post(api_url, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}, json={'model': model, 'messages': messages, 'temperature': 0.1, 'max_tokens': 600})
            if response.status_code >= 400:
                _facade().logger.warning('AgenticLoop LLM 调用失败: status=%d', response.status_code)
                return None
            raw = (response.json().get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
            raw = raw.removeprefix('```json').removeprefix('```').removesuffix('```').strip()
            if not raw:
                return None
            parsed = _facade().json.loads(raw)
            action = str(parsed.get('action') or '').strip().lower()
            if action == 'done':
                return {'action': 'done'}
            tool_id = str(parsed.get('tool_id') or '').strip()
            action_name = str(parsed.get('action_name') or parsed.get('tool_action') or ('' if action == 'execute' else action)).strip()
            params = parsed.get('params') if isinstance(parsed.get('params'), dict) else {}
            reasoning = str(parsed.get('reasoning') or '').strip()
            if not tool_id or not action_name:
                return None
            return {'action': 'execute', 'tool_id': tool_id, 'action_name': action_name, 'params': params, 'reasoning': reasoning}
        except _facade().RECOVERABLE_ERRORS as e:
            _facade().logger.warning('AgenticLoop LLM 决策失败: %s', e, exc_info=True)
            return None

    @staticmethod
    def _summarize_output(output: dict[str, _facade().Any]) -> str:
        if not isinstance(output, dict):
            return str(output)[:200]
        if output.get('success') is True:
            msg = str(output.get('message') or output.get('answer') or '').strip()
            if msg:
                return msg[:200]
            data = output.get('data')
            if data is not None:
                if isinstance(data, list):
                    return f'返回 {len(data)} 条数据'
                return str(data)[:200]
        err = str(output.get('error') or output.get('message') or '').strip()
        if err:
            return f'错误: {err[:100]}'
        return str(output)[:200]

    def _run_single_tool(self, tool_id: str, action: str, params: dict[str, _facade().Any], runtime_context: dict[str, _facade().Any], max_retries: int, retryable: bool=True) -> _facade().NodeExecutionResult:
        merged_params = dict(params or {})
        merged_params['_runtime_context'] = runtime_context
        retries = 0
        last_error = ''
        started_at = _facade().datetime.now(_facade().UTC).isoformat()
        started_perf = _facade().time.perf_counter()
        attempts: list[dict[str, _facade().Any]] = []
        last_output: dict[str, _facade().Any] = {}
        effective_max_retries = max_retries if retryable else 0
        while retries <= effective_max_retries:
            attempt_started = _facade().time.perf_counter()
            try:
                output = self._dispatch(tool_id=tool_id, action=action, params=merged_params)
                if isinstance(output, dict):
                    last_output = output
                if output.get('success', False):
                    finished_at = _facade().datetime.now(_facade().UTC).isoformat()
                    return _facade().NodeExecutionResult(node_id=f'agent_{tool_id}_{action}', success=True, tool_id=tool_id, action=action, params=dict(params or {}), output=output, retries=retries, retryable=retryable, started_at=started_at, finished_at=finished_at, duration_ms=self._elapsed_ms(started_perf), attempts=attempts + [self._attempt_summary(retries + 1, True, '', attempt_started)])
                last_error = str(output.get('message') or output.get('error') or 'unknown error')
                attempts.append(self._attempt_summary(retries + 1, False, last_error, attempt_started))
            except _facade().RECOVERABLE_ERRORS as err:
                last_error = str(err)
                attempts.append(self._attempt_summary(retries + 1, False, last_error, attempt_started))
                _facade().logger.warning('AgenticLoop 工具执行失败 %s.%s: %s', tool_id, action, err, exc_info=True)
            retries += 1
        finished_at = _facade().datetime.now(_facade().UTC).isoformat()
        return _facade().NodeExecutionResult(node_id=f'agent_{tool_id}_{action}', success=False, tool_id=tool_id, action=action, params=dict(params or {}), output=last_output, error=last_error, retries=max(0, retries - 1), retryable=retryable, recovery_hint=self._recovery_hint(tool_id=tool_id, action=action, error=last_error, output=last_output, retryable=retryable), started_at=started_at, finished_at=finished_at, duration_ms=self._elapsed_ms(started_perf), attempts=attempts)

    @staticmethod
    def _has_non_empty_param(params: dict[str, _facade().Any], keys: tuple[str, ...]) -> bool:
        for k in keys:
            v = params.get(k)
            if v is not None and str(v).strip():
                return True
        return False

    def _merge_runtime_fallback_params(self, node: _facade().WorkflowNode, merged_params: dict[str, _facade().Any], runtime_context: dict[str, _facade().Any]) -> None:
        user_msg = str(runtime_context.get('message') or '').strip()
        if not user_msg:
            return
        if node.tool_id == 'products' and node.action == 'query':
            if not self._has_non_empty_param(merged_params, ('keyword', 'model_number', 'product_name', 'name', 'unit_name')):
                keyword = _facade().inject_product_query_fallback(merged_params, user_msg)
                _facade().logger.info('工作流 products.query %s', f'注入有效检索词: {keyword[:80]}' if keyword else '按全量列表请求执行')
        elif node.tool_id == 'customers' and node.action == 'query':
            if not self._has_non_empty_param(merged_params, ('keyword', 'unit_name', 'customer_name', 'name')):
                merged_params.pop('keyword', None)
                _facade().logger.info('工作流 customers.query 无检索词，按全量列表执行（不注入用户原话）')

    @staticmethod
    def _elapsed_ms(started_perf: float) -> int:
        return max(0, int((_facade().time.perf_counter() - started_perf) * 1000))

    @staticmethod
    def _attempt_summary(attempt: int, success: bool, error: str, started_perf: float) -> dict[str, _facade().Any]:
        return {'attempt': attempt, 'success': bool(success), 'error': str(error or '')[:240], 'duration_ms': _facade().WorkflowEngine._elapsed_ms(started_perf)}

    @staticmethod
    def _node_allows_auto_retry(node: _facade().WorkflowNode) -> bool:
        return bool(node.idempotent) or node.risk == 'low'

    @staticmethod
    def _agentic_tool_allows_auto_retry(tool_registry: dict[str, _facade().Any], tool_id: str, action: str) -> bool:
        spec = tool_registry.get(tool_id) if isinstance(tool_registry, dict) else None
        if not isinstance(spec, dict):
            return True
        actions = spec.get('actions') if isinstance(spec.get('actions'), dict) else {}
        meta = actions.get(action) if isinstance(actions, dict) else None
        if not isinstance(meta, dict):
            return True
        return bool(meta.get('idempotent')) or str(meta.get('risk') or 'low') == 'low'

    @staticmethod
    def _recovery_hint(*, tool_id: str, action: str, error: str, output: dict[str, _facade().Any] | None, retryable: bool) -> str:
        out = output if isinstance(output, dict) else {}
        message = str(error or out.get('message') or out.get('error') or '').strip()
        if out.get('pending_approval') or out.get('approval_required'):
            return '写操作已进入审批流；在审批工作台通过后重试或继续执行。'
        if out.get('requires_token'):
            token_name = str(out.get('token_name') or 'DB_WRITE_TOKEN').strip()
            return f'缺少写库令牌 {token_name}；配置令牌或在受信任工作区内重试。'
        if out.get('available_employee_ids'):
            return '请从返回的 available_employee_ids 中选择员工 ID 后重新执行。'
        if '缺少 employee_id' in message:
            return '先执行 employee.list 查看可用员工，再带 employee_id 调用 employee.execute。'
        if '缺少' in message or 'required' in message.lower():
            return '补齐提示中的必填参数后重新执行。'
        if not retryable:
            return '该节点可能产生副作用，系统未自动重试；请核对员工空间或数据库状态后手动重试。'
        if tool_id == 'business_db' and action == 'write':
            return '数据库写入失败；确认 entity/operation/payload 后重试，避免重复写入。'
        if message:
            return '可重试节点已耗尽自动重试；请检查参数、外部服务连接或稍后重试。'
        return ''

    @staticmethod
    def _merge_state_schema(runtime_context: dict[str, _facade().Any], result: _facade().NodeExecutionResult, schema: _facade().StateSchema) -> None:
        """用 StateSchema 校验/归并 runtime_context；校验失败记录到节点结果，不中断执行。"""
        try:
            _facade().apply_state_schema(runtime_context, schema)
        except ValueError as exc:
            msg = str(exc)
            result.error = (result.error + '; ' if result.error else '') + msg
            _facade().logger.warning('StateSchema 校验失败 node=%s: %s', result.node_id, msg)
