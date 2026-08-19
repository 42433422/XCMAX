# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.workflow.engine')

class _WorkflowEnginePart02Mixin:

    @staticmethod
    def _append_node_trace(runtime_context: dict[str, _facade().Any], result: _facade().NodeExecutionResult) -> None:
        runtime_context.setdefault('workflow_trace', [])
        trace = runtime_context['workflow_trace']
        if not isinstance(trace, list):
            runtime_context['workflow_trace'] = trace = []
        trace.append({'node_id': result.node_id, 'tool_id': result.tool_id, 'action': result.action, 'success': result.success, 'retries': result.retries, 'retryable': result.retryable, 'duration_ms': result.duration_ms, 'error': result.error, 'recovery_hint': result.recovery_hint})

    def _run_node(self, node: _facade().WorkflowNode, runtime_context: dict[str, _facade().Any], max_retries: int=1) -> _facade().NodeExecutionResult:
        retries = 0
        last_error = ''
        retryable = self._node_allows_auto_retry(node)
        effective_max_retries = max_retries if retryable else 0
        started_at = _facade().datetime.now(_facade().UTC).isoformat()
        started_perf = _facade().time.perf_counter()
        attempts: list[dict[str, _facade().Any]] = []
        last_output: dict[str, _facade().Any] = {}
        if node.tool_id == 'clarify':
            return self._run_clarify_node(node, runtime_context)
        while retries <= effective_max_retries:
            attempt_started = _facade().time.perf_counter()
            try:
                merged_params = dict(node.params or {})
                merged_params['_runtime_context'] = runtime_context
                self._merge_runtime_fallback_params(node, merged_params, runtime_context)
                output = self._dispatch(tool_id=node.tool_id, action=node.action, params=merged_params)
                if isinstance(output, dict):
                    last_output = output
                if output.get('success', False):
                    finished_at = _facade().datetime.now(_facade().UTC).isoformat()
                    return _facade().NodeExecutionResult(node_id=node.node_id, success=True, tool_id=node.tool_id, action=node.action, params=dict(node.params or {}), output=output, retries=retries, retryable=retryable, started_at=started_at, finished_at=finished_at, duration_ms=self._elapsed_ms(started_perf), attempts=attempts + [self._attempt_summary(retries + 1, True, '', attempt_started)])
                last_error = str(output.get('message') or output.get('error') or 'unknown error')
                attempts.append(self._attempt_summary(retries + 1, False, last_error, attempt_started))
            except _facade().RECOVERABLE_ERRORS as err:
                last_error = str(err)
                attempts.append(self._attempt_summary(retries + 1, False, last_error, attempt_started))
                _facade().logger.warning('执行节点失败 node=%s err=%s', node.node_id, err, exc_info=True)
            retries += 1
        finished_at = _facade().datetime.now(_facade().UTC).isoformat()
        return _facade().NodeExecutionResult(node_id=node.node_id, success=False, tool_id=node.tool_id, action=node.action, params=dict(node.params or {}), output=last_output, error=last_error, retries=max(0, retries - 1), retryable=retryable, recovery_hint=self._recovery_hint(tool_id=node.tool_id, action=node.action, error=last_error, output=last_output, retryable=retryable), started_at=started_at, finished_at=finished_at, duration_ms=self._elapsed_ms(started_perf), attempts=attempts)

    def _run_clarify_node(self, node: _facade().WorkflowNode, runtime_context: dict[str, _facade().Any]) -> _facade().NodeExecutionResult:
        """反问澄清节点执行：不调用业务工具。

        - 若 runtime_context 中已注入该节点的确认答案（``_clarify_answers[node.node_id]``），
          则产出 ``answer_confirmed``，供条件边（branches）路由到原操作节点继续执行。
        - 否则产出 ``requires_confirmation=true`` + ``question``，暂停工作流（interrupt），
          且不路由到写节点（写节点被 block）。
        """
        started_at = _facade().datetime.now(_facade().UTC).isoformat()
        started_perf = _facade().time.perf_counter()
        params = node.params or {}
        question = str(params.get('question') or '').strip()
        answer_key = str(params.get('answer_key') or 'confirmed').strip() or 'confirmed'
        target_node_id = str(params.get('target_node_id') or '').strip()
        answers = runtime_context.get('_clarify_answers') or {}
        if not isinstance(answers, dict):
            answers = {}
        my_answer = answers.get(node.node_id)
        if isinstance(my_answer, dict) and my_answer.get('confirmed') is not None:
            output = {'success': True, 'answer_confirmed': bool(my_answer.get('confirmed')), 'answer_key': answer_key}
        else:
            output = {'success': True, 'requires_confirmation': True, 'answer_key': answer_key, 'question': question, 'target_node_id': target_node_id}
        finished_at = _facade().datetime.now(_facade().UTC).isoformat()
        return _facade().NodeExecutionResult(node_id=node.node_id, success=True, tool_id='clarify', action='ask', params=dict(params), output=output, started_at=started_at, finished_at=finished_at, duration_ms=self._elapsed_ms(started_perf), retryable=True)
