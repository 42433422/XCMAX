# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.agent_orchestrator.orchestrator')

class _AgentOrchestratorPart01Mixin:

    def __init__(self, *, repository: _facade().AgentRunRepository | None=None, tool_executor: _facade().AgentToolExecutor | None=None) -> None:
        self._repo = repository or _facade().get_agent_run_repository()
        self._repository_status = {'mode': 'sqlalchemy' if isinstance(self._repo, _facade().SQLAlchemyAgentRunRepository) else 'memory', 'durable': isinstance(self._repo, _facade().SQLAlchemyAgentRunRepository)}
        self._tool_executor = tool_executor or _facade().AgentToolExecutor()

    @staticmethod
    def _ingest_artifact_to_dataset(run: _facade().AgentRun, artifact: _facade().Any) -> None:
        _facade().ingest_artifact_to_dataset(run, artifact)

    def start_run(self, *, user_id: str, message: str, runtime_context: dict[str, _facade().Any] | None=None, auto_execute: bool=True) -> _facade().AgentRun:
        run = _facade().AgentRun(user_id=str(user_id or ''), message=str(message or ''))
        run.metadata['persistence'] = dict(self._repository_status)
        run.metadata['runtime_context'] = dict(runtime_context or {})
        _facade().apply_task_context(run, runtime_context)
        run.add_event('run.created', 'Agent run 已创建')
        self._repo.save(run)
        try:
            plan = self._plan(run, runtime_context=dict(runtime_context or {}))
            self._apply_plan(run, plan)
            _facade().apply_ai_budget_metadata(run, dict(plan.metadata or {}), dict(runtime_context or {}))
            self._repo.save(run)
            if auto_execute:
                self._execute_with_durable_lease(run, runtime_context=dict(runtime_context or {}))
            return _facade().cast('AgentRun', self._repo.save(run))
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception('agent run start failed')
            run.status = 'failed'
            run.error = _facade()._INTERNAL_RUN_ERROR
            run.add_event('run.failed', 'Agent run 失败', {'error_code': _facade()._INTERNAL_RUN_ERROR})
            return _facade().cast('AgentRun', self._repo.save(run))

    def start_run_from_plan(self, *, user_id: str, message: str, plan: _facade().PlanGraph, runtime_context: dict[str, _facade().Any] | None=None, auto_execute: bool=True) -> _facade().AgentRun:
        run = _facade().AgentRun(user_id=str(user_id or ''), message=str(message or ''))
        run.metadata['persistence'] = dict(self._repository_status)
        run.metadata['runtime_context'] = dict(runtime_context or {})
        _facade().apply_task_context(run, runtime_context)
        run.add_event('run.created', 'Agent run 已创建')
        run.add_event('planner.completed', 'Agent 计划已接管', {'plan_id': plan.plan_id, 'intent': plan.intent, 'nodes': len(plan.nodes), 'source': 'provided_plan'})
        try:
            self._apply_plan(run, plan)
            _facade().apply_ai_budget_metadata(run, dict(plan.metadata or {}), dict(runtime_context or {}))
            self._repo.save(run)
            if auto_execute:
                self._execute_with_durable_lease(run, runtime_context=dict(runtime_context or {}))
            return _facade().cast('AgentRun', self._repo.save(run))
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.exception('agent run from plan failed')
            run.status = 'failed'
            run.error = _facade()._INTERNAL_RUN_ERROR
            run.add_event('run.failed', 'Agent run 失败', {'error_code': _facade()._INTERNAL_RUN_ERROR})
            return _facade().cast('AgentRun', self._repo.save(run))

    def continue_run(self, run_id: str, *, approved_by: str='', approved_step_id: str='', runtime_context: dict[str, _facade().Any] | None=None) -> _facade().AgentRun | None:
        run = self._repo.get(run_id)
        if run is None:
            return None
        waiting_step = self._find_waiting_step(run, approved_step_id=approved_step_id)
        if waiting_step is None and str(approved_step_id or '').strip():
            wanted = str(approved_step_id).strip()
            waiting_step = next((step for step in run.steps if step.status == 'pending' and wanted in {step.step_id, step.node_id}), None)
        if waiting_step is None:
            run.add_event('run.continue_ignored', '没有等待确认的步骤', {'approved_by': approved_by, 'approved_step_id': approved_step_id})
            return _facade().cast('AgentRun | None', self._repo.save(run))
        context = dict(run.metadata.get('runtime_context') or {})
        context.update(dict(runtime_context or {}))
        run.metadata['runtime_context'] = context
        _facade().apply_ai_budget_metadata(run, context)
        waiting_step.status = 'pending'
        run.status = 'running'
        run.error = ''
        run.add_event('step.approved', f'步骤 {waiting_step.node_id} 已确认继续', {'step_id': waiting_step.step_id, 'node_id': waiting_step.node_id, 'tool_id': waiting_step.tool_id, 'action': waiting_step.action, 'approved_by': approved_by})
        self._execute_with_durable_lease(run, runtime_context=context, approved_step_id=waiting_step.step_id)
        return _facade().cast('AgentRun | None', self._repo.save(run))

    def list_runs(self, *, user_id: str | None=None, limit: int=50) -> list[_facade().AgentRun]:
        return _facade().cast('list[AgentRun]', self._repo.list_recent(user_id=user_id, limit=limit))

    def list_events(self, run_id: str, *, after_event_id: str | None=None) -> list[_facade().RunEvent]:
        return _facade().cast('list[RunEvent]', self._repo.list_events(run_id, after_event_id=after_event_id))

    def _plan(self, run: _facade().AgentRun, *, runtime_context: dict[str, _facade().Any]) -> _facade().PlanGraph:
        from app.application.agent_orchestrator.multimodal_planner import build_multimodal_autonomous_plan
        from app.application.workflow.planner import LLMWorkflowPlanner
        from app.services.tools_execution.registry import get_workflow_tool_registry
        run.status = 'planning'
        run.add_event('planner.started', '开始生成 Agent 计划')
        self._repo.save(run)
        context = dict(runtime_context or {})
        context.setdefault('message', run.message)
        multimodal_plan = build_multimodal_autonomous_plan(user_id=run.user_id, message=run.message, runtime_context=context)
        if multimodal_plan is not None:
            run.add_event('planner.completed', '多模态 Artifact 自主计划生成完成', {'plan_id': multimodal_plan.plan_id, 'intent': multimodal_plan.intent, 'nodes': len(multimodal_plan.nodes), 'source': 'multimodal_autonomous_planner', 'artifact_count': multimodal_plan.metadata.get('artifact_count', 0)})
            return multimodal_plan
        planner = LLMWorkflowPlanner()
        plan = planner.plan(run.user_id, run.message, get_workflow_tool_registry(), context)
        run.add_event('planner.completed', 'Agent 计划生成完成', {'plan_id': plan.plan_id, 'intent': plan.intent, 'nodes': len(plan.nodes)})
        return plan

    def _apply_plan(self, run: _facade().AgentRun, plan: _facade().PlanGraph) -> None:
        run.plan_id = plan.plan_id
        run.intent = plan.intent
        run.metadata['plan'] = {'todo_steps': list(plan.todo_steps or []), 'risk_level': plan.risk_level, 'metadata': dict(plan.metadata or {})}
        run.steps = [self._step_from_node(node) for node in plan.nodes]
        self._apply_repair_policy(run, dict(plan.metadata or {}))
        self._attach_artifacts_from_payload(run, getattr(plan, 'metadata', {}) or {}, source='plan.metadata')
        self._refresh_artifact_metadata(run)
        run.status = 'running' if run.steps else 'blocked'
        if not run.steps:
            run.error = 'planner returned no executable steps'
            run.add_event('planner.blocked', '计划没有可执行节点')

    @staticmethod
    def _step_from_node(node: _facade().WorkflowNode) -> _facade().AgentStep:
        spec = _facade().get_tool_action_spec(node.tool_id, node.action)
        return _facade().AgentStep(node_id=node.node_id, tool_id=node.tool_id, action=spec.action if spec is not None else node.action, params=dict(node.params or {}), risk=spec.risk if spec is not None else str(node.risk or 'low'), idempotent=bool(spec.idempotent) if spec is not None else bool(node.idempotent), description=str(node.description or ''), depends_on=list(node.depends_on or []))

    @staticmethod
    def _find_waiting_step(run: _facade().AgentRun, *, approved_step_id: str='') -> _facade().AgentStep | None:
        wanted = str(approved_step_id or '').strip()
        for step in run.steps:
            if step.status != 'waiting_user':
                continue
            if wanted and wanted not in {step.step_id, step.node_id}:
                continue
            return step
        return None

    def _execute_ready_steps(self, run: _facade().AgentRun, *, runtime_context: dict[str, _facade().Any], approved_step_id: str='') -> None:
        approved = str(approved_step_id or '').strip()
        completed_node_ids: set[str] = {step.node_id for step in run.steps if step.status == 'completed'}
        node_outputs: dict[str, _facade().Any] = {step.node_id: dict(step.output or {}) for step in run.steps if step.status == 'completed'}
        for step in run.steps:
            if self._apply_requested_control(run):
                return
            if step.status == 'completed':
                continue
            if any((dep not in completed_node_ids for dep in step.depends_on)):
                run.status = 'blocked'
                step.status = 'skipped'
                step.error = 'dependencies are not completed'
                run.add_event('step.blocked', f'步骤 {step.node_id} 依赖未满足', {'step_id': step.step_id, 'depends_on': step.depends_on})
                return
            step_is_approved = bool(approved and approved in {step.step_id, step.node_id})
            if not self._can_auto_execute(step) and (not step_is_approved):
                step.status = 'waiting_user'
                run.status = 'waiting_user'
                run.add_event('step.waiting_user', f'步骤 {step.node_id} 需要用户确认', {'step_id': step.step_id, 'tool_id': step.tool_id, 'action': step.action, 'risk': step.risk, 'idempotent': step.idempotent})
                return
            while True:
                budget_payload = _facade().budget_exceeded_payload(run, additional_cost_units=self._step_cost_units(step), scope=f'{step.tool_id}.{step.action}')
                if budget_payload is not None:
                    self._mark_budget_exceeded(run, step, budget_payload, node_outputs=node_outputs)
                    return
                self._execute_step(run, step, runtime_context=runtime_context, node_outputs=node_outputs)
                if self._apply_requested_control(run):
                    return
                if step.status == 'completed':
                    break
                if self._prepare_repair_or_retry(run, step, runtime_context=runtime_context):
                    continue
                run.status = 'failed'
                run.error = step.error or f'step {step.node_id} failed'
                self._refresh_run_cost_metadata(run)
                self._refresh_repair_metadata(run)
                run.final_output = {'node_outputs': node_outputs, 'tool_calls': [call.to_dict() for call in run.tool_calls], 'artifacts': [artifact.to_dict() for artifact in run.artifacts], 'cost_units_total': run.metadata['cost_units_total'], 'ai_cost_units_total': run.metadata['ai_cost_units_total'], 'failed_step_id': step.step_id, 'error': run.error, 'repair_count': run.metadata.get('repair_count', 0)}
                self._append_llm_summary_to_final_output(run)
                return
            completed_node_ids.add(step.node_id)
        run.status = 'completed'
        self._refresh_run_cost_metadata(run)
        self._refresh_repair_metadata(run)
        run.final_output = {'node_outputs': node_outputs, 'tool_calls': [call.to_dict() for call in run.tool_calls], 'artifacts': [artifact.to_dict() for artifact in run.artifacts], 'cost_units_total': run.metadata['cost_units_total'], 'ai_cost_units_total': run.metadata['ai_cost_units_total'], 'repair_count': run.metadata.get('repair_count', 0)}
        self._append_llm_summary_to_final_output(run)
        run.add_event('run.completed', 'Agent run 执行完成', run.final_output)

    @staticmethod
    def _can_auto_execute(step: _facade().AgentStep) -> bool:
        return str(step.risk or '').lower() == 'low' and bool(step.idempotent)

    def _execute_step(self, run: _facade().AgentRun, step: _facade().AgentStep, *, runtime_context: dict[str, _facade().Any], node_outputs: dict[str, _facade().Any]) -> None:
        started = _facade().time.perf_counter()
        step.attempt_count += 1
        step.status = 'running'
        step.started_at = _facade().utc_now_iso()
        run.status = 'running'
        attempt_count = step.attempt_count
        spec = _facade().get_tool_action_spec(step.tool_id, step.action)
        tool_call = _facade().ToolCall(step_id=step.step_id, node_id=step.node_id, tool_id=step.tool_id, action=step.action, params=_facade().copy.deepcopy(step.params or {}), cost_units=int(getattr(spec, 'cost_units', 0) or 0), permission=str(getattr(spec, 'permission', '') or ''), metadata={'risk': step.risk, 'idempotent': step.idempotent, 'timeout_seconds': int(getattr(spec, 'timeout_seconds', 0) or 0), 'attempt_count': attempt_count})
        run.tool_calls.append(tool_call)
        self._refresh_run_cost_metadata(run)
        run.add_event('tool.started', f'开始执行 {step.tool_id}.{step.action}', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': tool_call.call_id, 'cost_units': tool_call.cost_units, 'permission': tool_call.permission, 'attempt_count': attempt_count})
        self._repo.save(run)
        ctx = dict(runtime_context or {})
        ctx.update({'run_id': run.run_id, 'step_id': step.step_id, 'node_id': step.node_id, 'message': run.message, 'user_id': run.user_id, 'node_outputs': dict(node_outputs), **_facade().task_execution_context(run, step)})
        tool_call.metadata['idempotency_key'] = ctx['idempotency_key']
        validation = _facade().validate_tool_call(step.tool_id, step.action, step.params)
        if not validation.ok:
            output = {'success': False, 'error_code': validation.error_code, 'message': validation.message, 'tool_id': validation.tool_id, 'action': validation.action}
        elif not self._record_tool_usage_entry(run, tool_call):
            output = {'success': False, 'error_code': 'tool_billing_blocked', 'message': run.error or 'AI tool billing failed', 'tool_id': step.tool_id, 'action': step.action}
        else:
            try:
                output = self._tool_executor.execute(step, runtime_context=ctx)
            except _facade().RECOVERABLE_ERRORS as exc:
                output = {'success': False, 'error_code': 'tool_exception', 'message': str(exc)}
        step.output = dict(output or {})
        step.finished_at = _facade().utc_now_iso()
        step.duration_ms = int((_facade().time.perf_counter() - started) * 1000)
        tool_call.output = _facade().copy.deepcopy(step.output)
        tool_call.finished_at = step.finished_at
        tool_call.duration_ms = step.duration_ms
        self._attach_artifacts_from_payload(run, step.output, source=f'{step.tool_id}.{step.action}', extra_metadata={'step_id': step.step_id, 'call_id': tool_call.call_id})
        success = bool(step.output.get('success', False))
        observation = self._record_observation(run, step, tool_call=tool_call, success=success)
        if success:
            step.status = 'completed'
            tool_call.status = 'completed'
            self._refresh_run_cost_metadata(run)
            node_outputs[step.node_id] = step.output
            run.add_event('tool.completed', f'完成 {step.tool_id}.{step.action}', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': tool_call.call_id, 'duration_ms': step.duration_ms, 'cost_units': tool_call.cost_units, 'attempt_count': attempt_count, 'observation_id': observation.get('observation_id')})
            return
        step.status = 'failed'
        step.error = str(step.output.get('message') or step.output.get('error') or 'tool failed')
        tool_call.status = 'failed'
        tool_call.error = step.error
        if str(step.output.get('error_code') or '') != 'tool_billing_blocked':
            self._record_tool_usage_refund(run, tool_call, reason=step.error)
        self._refresh_run_cost_metadata(run)
        run.add_event('tool.failed', f'{step.tool_id}.{step.action} 执行失败', {'step_id': step.step_id, 'node_id': step.node_id, 'call_id': tool_call.call_id, 'error': step.error, 'duration_ms': step.duration_ms, 'cost_units': tool_call.cost_units, 'attempt_count': attempt_count, 'observation_id': observation.get('observation_id')})

    def _record_tool_usage_entry(self, run: _facade().AgentRun, tool_call: _facade().ToolCall) -> bool:
        if tool_call.cost_units <= 0:
            tool_call.metadata['usage_ledger'] = {'status': 'not_required', 'cost_units': 0}
            return True
        if isinstance(tool_call.metadata.get('usage_ledger'), dict):
            return True
        try:
            from app.infrastructure.billing.model_usage import record_tool_usage
            entry = record_tool_usage(run_id=run.run_id, user_id=run.user_id, tool_id=tool_call.tool_id, action=tool_call.action, call_id=tool_call.call_id, permission=tool_call.permission, status='pre_execution', cost_units=tool_call.cost_units, source='agent_orchestrator.tool_call', usage_key=f'{run.run_id}:{tool_call.call_id}:tool_call', metadata={'step_id': tool_call.step_id, 'node_id': tool_call.node_id, 'attempt_count': tool_call.metadata.get('attempt_count'), 'risk': tool_call.metadata.get('risk'), 'idempotent': tool_call.metadata.get('idempotent')})
        except _facade().RECOVERABLE_ERRORS as exc:
            tool_call.metadata['usage_ledger'] = {'status': 'failed', 'message': str(exc)}
            run.metadata['tool_usage_ledger_status'] = 'failed'
            run.add_event('billing.record_failed', '工具调用用量账本写入失败', {'call_id': tool_call.call_id, 'tool_id': tool_call.tool_id, 'action': tool_call.action, 'cost_units': tool_call.cost_units, 'error': str(exc)})
            return True
        tool_call.metadata['usage_ledger'] = {'usage_id': entry.get('usage_id'), 'usage_key': entry.get('usage_key'), 'entry_type': entry.get('entry_type'), 'status': 'recorded'}
        wallet_debit = entry.get('wallet_debit') if isinstance(entry.get('wallet_debit'), dict) else {}
        if wallet_debit:
            tool_call.metadata['wallet_debit'] = wallet_debit
        tool_call.metadata['billing_status'] = entry.get('billing_status')
        tool_call.metadata['billing_source'] = entry.get('billing_source')
        self._refresh_tool_usage_metadata(run, entry)
        event_payload = {'usage_id': entry.get('usage_id'), 'call_id': tool_call.call_id, 'tool_id': tool_call.tool_id, 'action': tool_call.action, 'cost_units': entry.get('cost_units'), 'billing_status': entry.get('billing_status'), 'billing_source': entry.get('billing_source'), 'wallet_debit': wallet_debit, 'source': 'agent_orchestrator.tool_call'}
        billing_status = str(entry.get('billing_status') or '')
        wallet_payload: dict[str, _facade().Any] = dict(wallet_debit) if isinstance(wallet_debit, dict) else {}
        if billing_status == 'debited':
            self._refresh_wallet_balance_metadata(run, wallet_payload)
            run.add_event('billing.debited', '工具调用用量已从 AI 钱包扣减', event_payload)
            return True
        if billing_status == 'insufficient_balance':
            self._refresh_wallet_balance_metadata(run, wallet_payload)
            run.status = 'failed'
            run.error = 'AI tool wallet balance insufficient'
            run.add_event('billing.insufficient_balance', run.error, event_payload)
            return False
        if billing_status == 'market_debit_failed':
            run.status = 'failed'
            run.error = 'AI tool market wallet debit failed'
            run.add_event('billing.debit_failed', run.error, event_payload)
            return False
        run.add_event('billing.recorded', '工具调用用量已写入 AI 账本', event_payload)
        return True

    def _record_tool_usage_refund(self, run: _facade().AgentRun, tool_call: _facade().ToolCall, *, reason: str) -> None:
        usage_ledger = tool_call.metadata.get('usage_ledger') if isinstance(tool_call.metadata.get('usage_ledger'), dict) else {}
        if not isinstance(usage_ledger, dict):
            usage_ledger = {}
        usage_key = str(usage_ledger.get('usage_key') or '')
        if not usage_key or isinstance(tool_call.metadata.get('wallet_refund'), dict):
            return
        try:
            from app.infrastructure.billing.model_usage import refund_tool_usage
            entry = refund_tool_usage(usage_key=usage_key, refund_key=f'{usage_key}:refund', reason=reason)
        except _facade().RECOVERABLE_ERRORS as exc:
            tool_call.metadata['wallet_refund'] = {'status': 'failed', 'message': str(exc)}
            run.add_event('billing.refund_failed', '工具调用失败补偿记录失败', {'call_id': tool_call.call_id, 'tool_id': tool_call.tool_id, 'action': tool_call.action, 'usage_key': usage_key, 'error': str(exc)})
            return
        refund = entry.get('refund') if isinstance(entry.get('refund'), dict) else {}
        if not refund:
            return
        tool_call.metadata['wallet_refund'] = refund
        self._refresh_tool_refund_metadata(run, refund)
        self._refresh_wallet_balance_metadata(run, refund)
        status = str(refund.get('status') or '')
        event_type = 'billing.refunded' if status == 'refunded' else 'billing.refund_pending' if status == 'refund_pending' else 'billing.refund_recorded'
        run.add_event(event_type, '工具调用失败已记录补偿', {'call_id': tool_call.call_id, 'tool_id': tool_call.tool_id, 'action': tool_call.action, 'usage_key': usage_key, 'refund_status': status, 'cost_units': refund.get('cost_units'), 'wallet_refund': refund})

    @staticmethod
    def _refresh_wallet_balance_metadata(run: _facade().AgentRun, wallet_debit: dict[str, _facade().Any]) -> None:
        if 'balance_after_units' in wallet_debit:
            run.metadata['model_wallet_balance_units'] = wallet_debit.get('balance_after_units', 0)
            run.metadata['ai_wallet_balance_units'] = wallet_debit.get('balance_after_units', 0)
        if 'balance_after_yuan' in wallet_debit:
            run.metadata['model_wallet_balance_yuan'] = wallet_debit.get('balance_after_yuan')
            run.metadata['ai_wallet_balance_yuan'] = wallet_debit.get('balance_after_yuan')

    @staticmethod
    def _refresh_tool_usage_metadata(run: _facade().AgentRun, entry: dict[str, _facade().Any]) -> None:
        run.metadata['tool_usage_entry_count'] = int(run.metadata.get('tool_usage_entry_count') or 0) + 1
        run.metadata['tool_usage_cost_units_total'] = int(run.metadata.get('tool_usage_cost_units_total') or 0) + int(entry.get('cost_units') or 0)
        run.metadata['tool_usage_ledger_status'] = 'recorded'

    @staticmethod
    def _refresh_tool_refund_metadata(run: _facade().AgentRun, refund: dict[str, _facade().Any]) -> None:
        run.metadata['tool_usage_refund_count'] = int(run.metadata.get('tool_usage_refund_count') or 0) + 1
        if str(refund.get('status') or '') == 'refunded':
            run.metadata['tool_usage_refund_cost_units_total'] = int(run.metadata.get('tool_usage_refund_cost_units_total') or 0) + int(refund.get('cost_units') or 0)
        run.metadata['tool_usage_refund_status'] = str(refund.get('status') or '')

    @staticmethod
    def _cost_units_total(run: _facade().AgentRun) -> int:
        return sum((int(call.cost_units or 0) for call in run.tool_calls))

    @staticmethod
    def _step_cost_units(step: _facade().AgentStep) -> int:
        spec = _facade().get_tool_action_spec(step.tool_id, step.action)
        try:
            return int(getattr(spec, 'cost_units', 0) or 0)
        except (TypeError, ValueError):
            return 0

    def _refresh_run_cost_metadata(self, run: _facade().AgentRun) -> None:
        run.metadata['tool_call_count'] = len(run.tool_calls)
        run.metadata['cost_units_total'] = self._cost_units_total(run)
        run.metadata['ai_cost_units_total'] = int(run.metadata['cost_units_total']) + int(run.metadata.get('llm_cost_units_total') or 0)
        _facade().refresh_ai_budget_metadata(run)

    def _mark_budget_exceeded(self, run: _facade().AgentRun, step: _facade().AgentStep, payload: dict[str, _facade().Any], *, node_outputs: dict[str, _facade().Any]) -> None:
        step.status = 'failed'
        step.error = str(payload.get('message') or 'AI cost budget exceeded')
        run.status = 'failed'
        run.error = step.error
        self._refresh_run_cost_metadata(run)
        run.metadata['ai_cost_budget_exceeded'] = True
        self._refresh_repair_metadata(run)
        payload = dict(payload)
        payload['step_id'] = step.step_id
        payload['node_id'] = step.node_id
        payload['tool_id'] = step.tool_id
        payload['action'] = step.action
        run.add_event('budget.exceeded', step.error, payload)
        run.final_output = {'node_outputs': node_outputs, 'tool_calls': [call.to_dict() for call in run.tool_calls], 'artifacts': [artifact.to_dict() for artifact in run.artifacts], 'cost_units_total': run.metadata['cost_units_total'], 'ai_cost_units_total': run.metadata['ai_cost_units_total'], 'ai_cost_budget_units': run.metadata.get('ai_cost_budget_units'), 'ai_cost_budget_remaining_units': run.metadata.get('ai_cost_budget_remaining_units'), 'ai_cost_budget_exceeded': True, 'failed_step_id': step.step_id, 'error': run.error, 'repair_count': run.metadata.get('repair_count', 0)}
        self._append_llm_summary_to_final_output(run)

    def _record_observation(self, run: _facade().AgentRun, step: _facade().AgentStep, *, tool_call: _facade().ToolCall, success: bool) -> dict[str, _facade().Any]:
        output_message = str(step.output.get('message') or '')
        output_error = str(step.output.get('message') or step.output.get('error') or step.output.get('error_code') or '')
        observation = {'observation_id': f'obs_{tool_call.call_id}', 'step_id': step.step_id, 'node_id': step.node_id, 'tool_id': step.tool_id, 'action': step.action, 'call_id': tool_call.call_id, 'attempt_count': step.attempt_count, 'success': success, 'message': output_message, 'error': '' if success else output_error, 'status': 'completed' if success else 'failed'}
        step.observations.append(observation)
        run.metadata['observation_count'] = sum((len(item.observations) for item in run.steps))
        run.add_event('observation.recorded', f'记录 {step.node_id} 执行观察', observation)
        return observation

    @staticmethod
    def _coerce_positive_int(value: _facade().Any) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    def _apply_repair_policy(self, run: _facade().AgentRun, plan_metadata: dict[str, _facade().Any]) -> None:
        repair_policy = plan_metadata.get('repair_policy')
        repair_policy = repair_policy if isinstance(repair_policy, dict) else {}
        global_limit = self._coerce_positive_int(repair_policy.get('max_attempts') or plan_metadata.get('max_repair_attempts'))
        overrides = plan_metadata.get('repair_overrides')
        overrides = overrides if isinstance(overrides, dict) else {}
        for step in run.steps:
            node_policy = repair_policy.get(step.node_id)
            node_policy = node_policy if isinstance(node_policy, dict) else {}
            node_limit = self._coerce_positive_int(node_policy.get('max_attempts'))
            has_override = self._repair_override_for_step(step, overrides) is not None
            has_llm_repair = _facade().is_llm_repair_enabled(run, plan_metadata)
            step.max_repair_attempts = node_limit or global_limit or (1 if has_override or has_llm_repair else 0)

    @staticmethod
    def _repair_override_for_step(step: _facade().AgentStep, overrides: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
        keys = (step.node_id, f'{step.tool_id}.{step.action}', step.tool_id)
        for key in keys:
            candidate = overrides.get(key)
            if isinstance(candidate, dict):
                return candidate
        return None

    def _repair_sources(self, run: _facade().AgentRun, runtime_context: dict[str, _facade().Any]) -> list[tuple[str, dict[str, _facade().Any]]]:
        plan_meta = dict((run.metadata.get('plan') or {}).get('metadata') or {})
        sources: list[tuple[str, dict[str, _facade().Any]]] = []
        for (source_name, container) in (('plan.metadata', plan_meta), ('runtime_context', dict(runtime_context or {}))):
            for key in ('repair_overrides', 'agent_repair_overrides'):
                overrides = container.get(key)
                if isinstance(overrides, dict):
                    sources.append((f'{source_name}.{key}', overrides))
        return sources

    @staticmethod
    def _params_patch_from_repair(override: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        for key in ('params', 'set_params', 'patch_params'):
            candidate = override.get(key)
            if isinstance(candidate, dict):
                return dict(candidate)
        return {}
