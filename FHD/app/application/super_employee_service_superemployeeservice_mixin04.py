# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.super_employee_service')

class _SuperEmployeeServicePart04Mixin:

    def _clean_cli_stdout(self, stdout: str) -> str:
        lines = []
        for line in stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped in {self._p.tool_name, 'codex', 'tokens used'}:
                continue
            if _facade().re.fullmatch('[\\d,]+', stripped):
                continue
            lines.append(line)
        return '\n'.join(lines).strip()

    def _compose_direct_chat_reply(self, text: str, context: dict[str, _facade().Any]) -> tuple[str, str]:
        """普通对话直答：FAQ → CLI → 明确不可用提示。"""
        canned = self._direct_reply_body(text)
        if canned:
            return (canned, f'{self._p.tool_name}_direct')
        cli_body = self._cli_reply_body(text, context)
        if cli_body:
            return (cli_body, f'{self._p.tool_name}_cli')
        return (f'{self._p.display_tool} CLI 暂时没有返回内容，请确认本机 {self._p.display_tool} 已登录后重试。', f'{self._p.tool_name}_cli')

    def _direct_reply_body(self, text: str) -> str:
        normalized = _facade().re.sub('[\\s，。！？!?、,.]+', '', text.strip().lower())
        if not normalized:
            return ''
        tool = self._p.display_tool
        name = self._p.employee_name
        identity_prompts = {'你是谁', '你是誰', '你谁', '你是哪个', '你是什么', 'whoareyou', 'whatareyou'}
        help_prompts = {'你能做什么', '你能干什么', '你会什么', '怎么用', '如何使用', '帮助', 'help'}
        greeting_prompts = {'你好', '在吗', '在不在', 'hello', 'hi'}
        slow_prompts = {'为什么这么慢', '为啥这么慢', '为什么出不来', '怎么出不来'}
        if normalized in identity_prompts:
            return f'我是{name}。你在软件里发普通问题时，我会直接回复；你发开发、测试、打包、提交、跨设备协作这类任务时，我会调用可用的 {tool} 工作设备完成。'
        if normalized in help_prompts:
            return '你可以直接给我派开发任务，例如修复某个页面、跑测试、打包移动端、提交代码。如果只是问身份、用法或状态，我会在这里直接回复，不进入多设备派工。'
        if normalized in greeting_prompts:
            return '我在。需要改代码、跑验证或跨设备协作时，直接把任务发给我。'
        if normalized in slow_prompts:
            return '慢是因为这类消息之前被误当成开发任务派到多设备队列，必须等工作设备回传才显示结果。现在身份、帮助和问候类消息会直接回复；真正的开发任务才进入派工。'
        return ''

    def _fetch_para_task(self, task_id: str) -> dict[str, _facade().Any] | None:
        api_url = self._para_api_url()
        if not api_url or not task_id:
            return None
        try:
            with self._http_client_factory() as client:
                token = self._para_token(client, api_url)
                body = self._para_request(client, api_url, token, 'GET', f'/api/tasks/{task_id}')
            task = body.get('task') if isinstance(body, dict) else None
            return task if isinstance(task, dict) else None
        except (_facade().httpx.HTTPError, ValueError, KeyError, TypeError):
            return None

    def _upsert_direct_reply_messages(self, *, user_id: int, rows: list[dict[str, _facade().Any]]) -> bool:
        request_ids_with_reply = {str(item.get('dispatch_request_id') or '') for item in rows if int(item.get('user_id') or 0) == int(user_id) and (str(item.get('kind') or '') in {self._p.direct_kind, self._p.result_kind} or (str(item.get('role') or '') == 'assistant' and str(item.get('kind') or '') != _facade().DISPATCHER_MESSAGE_KIND))}
        changed = False
        cli_backfills = 0
        for item in list(rows):
            if int(item.get('user_id') or 0) != int(user_id):
                continue
            if str(item.get('role') or '') != 'user':
                continue
            request_id = str(item.get('dispatch_request_id') or '')
            if not request_id or request_id in request_ids_with_reply:
                continue
            text = str(item.get('body') or '')
            body = self._direct_reply_body(text)
            if not body and cli_backfills < 1 and self._should_reply_with_cli(text, {}):
                (body, _) = self._compose_direct_chat_reply(text, {})
                cli_backfills += 1
            if not body:
                continue
            rows.append(self._message_row(user_id=int(user_id), role='assistant', body=body, created_at=_facade()._utc_now(), request_id=request_id, status='completed', extra={'kind': self._p.direct_kind}))
            request_ids_with_reply.add(request_id)
            changed = True
        return changed

    def _refresh_dispatcher_row(self, row: dict[str, _facade().Any], task: dict[str, _facade().Any]) -> bool:
        task_id = str(task.get('id') or row.get('task_id') or '')
        task_status = str(task.get('status') or '').strip()
        body = self._para_task_status_reply(task)
        patch = {'body': body, 'status': task_status or str(row.get('status') or ''), 'task_id': task_id, 'task_status': task_status}
        changed = False
        for (key, value) in patch.items():
            if value and row.get(key) != value:
                row[key] = value
                changed = True
        return changed

    def _para_task_status_reply(self, task: dict[str, _facade().Any]) -> str:
        task_id = str(task.get('id') or '').strip()
        status = str(task.get('status') or '').strip()
        tool = self._p.display_tool
        subtasks = self._task_subtasks(task)
        total = len(subtasks)
        completed = sum((1 for item in subtasks if str(item.get('status') or '') == 'completed'))
        failed = sum((1 for item in subtasks if str(item.get('status') or '') == 'failed'))
        progress_values = [int(item.get('progress') or 0) for item in subtasks if isinstance(item.get('progress'), (int, float))]
        progress = round(sum(progress_values) / len(progress_values)) if progress_values else 0
        if status in {'completed', 'merged'}:
            head = f'Para 任务已完成，{tool} 执行结果已回传。'
        elif status in {'failed', 'merge_conflict'} or failed:
            head = f'Para 任务需要处理，{tool} 错误或冲突信息已回传。'
        elif total:
            head = f'Para 任务运行中：{completed}/{total} 个子任务完成，进度 {progress}%。'
        else:
            head = f'Para 任务已创建，等待 {tool} 工作设备回传。'
        return f"{head}{(f'任务 ID：{task_id}' if task_id else '')}"

    def _upsert_result_messages(self, *, user_id: int, dispatch_row: dict[str, _facade().Any], task: dict[str, _facade().Any], rows: list[dict[str, _facade().Any]]) -> bool:
        changed = False
        task_id = str(task.get('id') or dispatch_row.get('task_id') or '')
        for subtask in self._task_subtasks(task):
            status = str(subtask.get('status') or '').strip()
            if status not in {'completed', 'failed'}:
                continue
            body = self._result_body(task, subtask)
            if not body:
                continue
            subtask_id = str(subtask.get('id') or '')
            existing = next((item for item in rows if int(item.get('user_id') or 0) == int(user_id) and str(item.get('kind') or '') == self._p.result_kind and (str(item.get('task_id') or '') == task_id) and (str(item.get('subtask_id') or '') == subtask_id)), None)
            if existing:
                patch = {'body': body, 'status': status, 'task_status': str(task.get('status') or ''), 'device_name': str(subtask.get('device_name') or '')}
                for (key, value) in patch.items():
                    if value and existing.get(key) != value:
                        existing[key] = value
                        changed = True
                continue
            rows.append(self._message_row(user_id=int(user_id), role='assistant', body=body, created_at=str(subtask.get('completed_at') or _facade()._utc_now()), request_id=str(dispatch_row.get('dispatch_request_id') or ''), status=status, extra={'kind': self._p.result_kind, 'task_id': task_id, 'task_status': str(task.get('status') or ''), 'subtask_id': subtask_id, 'device_name': str(subtask.get('device_name') or '')}))
            changed = True
        return changed

    def _task_subtasks(self, task: dict[str, _facade().Any]) -> list[dict[str, _facade().Any]]:
        subtasks = _facade()._coerce_list(task.get('subTasks')) or _facade()._coerce_list(task.get('subtasks'))
        return [item for item in subtasks if isinstance(item, dict)]

    def _result_body(self, task: dict[str, _facade().Any], subtask: dict[str, _facade().Any]) -> str:
        logs = [str(log.get('content') or '').strip() for log in _facade()._coerce_list(subtask.get('logs')) if isinstance(log, dict) and str(log.get('content') or '').strip()]
        meaningful = [item for item in logs if not self._is_dispatcher_log(item)]
        tail = self._dedupe_log_tail(meaningful or logs)
        status = str(subtask.get('status') or '').strip()
        tool = self._p.display_tool
        device_name = str(subtask.get('device_name') or subtask.get('device_id') or '').strip()
        title = str(subtask.get('title') or task.get('title') or '').strip()
        prefix = f'{device_name} / {title}'.strip(' /')
        if tail:
            return f'{prefix}\n\n{tail}'.strip()
        if status == 'completed':
            return f'{prefix}\n\n{tool} 已完成该子任务。'.strip()
        if status == 'failed':
            last_error = str(subtask.get('last_error') or '').strip()
            return f'{prefix}\n\n{tool} 执行失败。{last_error}'.strip()
        return ''

    def _is_dispatcher_log(self, content: str) -> bool:
        prefixes = ('子任务「', '子任务未派发', '链路不可用', '设备连接已断开', '手动')
        return content.startswith(prefixes)

    def _dedupe_log_tail(self, logs: list[str], *, max_items: int=5, max_chars: int=4000) -> str:
        seen: set[str] = set()
        unique: list[str] = []
        for item in logs:
            key = item.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(key)
        return '\n\n'.join(unique[-max_items:])[-max_chars:].strip()

    def _public_message(self, item: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        return self._messages.public_message(item)
