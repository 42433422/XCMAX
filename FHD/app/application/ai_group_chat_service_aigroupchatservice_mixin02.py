# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.ai_group_chat_service')

class _AiGroupChatServicePart02Mixin:

    def _sync_super_employee_progress_for_group(self, *, user_id: int, group_id: str) -> None:
        """Mirror Codex/Cursor/Claude DevFleet results back into the group chat."""
        rows = [row for row in self._read_messages() if int(row.get('user_id') or 0) == int(user_id) and str(row.get('group_id') or '') == str(group_id)]
        if not rows:
            return
        final_task_ids = {self._report_relay_task_id(row) for row in rows if str(row.get('kind') or '') == 'relay_work_report'}
        pending_reports = [row for row in rows if str(row.get('kind') or '') == 'work_report' and str(row.get('sender_id') or '') in _facade()._SUPER_EMPLOYEE_IDS and self._report_relay_task_id(row) and (self._report_relay_task_id(row) not in final_task_ids)]
        if not pending_reports:
            return
        progress_rows = [row for row in rows if str(row.get('kind') or '') == 'work_progress']
        messages_by_employee: dict[str, list[dict[str, _facade().Any]]] = {}
        for report in pending_reports:
            employee_id = str(report.get('sender_id') or '').strip()
            task_id = self._report_relay_task_id(report)
            if not employee_id or not task_id:
                continue
            if employee_id not in messages_by_employee:
                try:
                    messages_by_employee[employee_id] = self._super_employee_service(employee_id).list_messages(user_id=int(user_id), limit=200)
                except _facade().RECOVERABLE_ERRORS:
                    messages_by_employee[employee_id] = []
            employee_messages = messages_by_employee[employee_id]
            result_msg = self._super_employee_result_message_for_task(employee_messages, task_id)
            if result_msg is not None:
                self.append_relay_work_report(task=self._super_employee_result_task(user_id=user_id, group_id=group_id, report=report, result_msg=result_msg))
                continue
            status_msg = self._super_employee_dispatch_message_for_task(employee_messages, task_id)
            status = self._super_employee_task_status(status_msg)
            if status in {'completed', 'done', 'merged', 'failed', 'blocked', 'cancelled'}:
                self.append_relay_work_report(task=self._super_employee_result_task(user_id=user_id, group_id=group_id, report=report, result_msg=status_msg or {}))
                continue
            if status not in {'queued', 'accepted', 'assigned', 'running', 'processing', 'in_progress'}:
                continue
            last = self._latest_progress_row(progress_rows, task_id)
            if not self._should_append_progress(last=last, status=status):
                continue
            progress = self._message_row(user_id=user_id, group_id=group_id, role='ai', sender_id=employee_id, sender_name=str(report.get('sender_name') or '负责人'), sender_avatar=str(report.get('sender_avatar') or ''), body=self._format_relay_progress_message(report=report, task={'task_id': task_id, 'kind': 'super_employee'}, status=status), kind='work_progress', status=status, work_order_id=str(report.get('work_order_id') or ''), payload={'work_order_id': str(report.get('work_order_id') or ''), 'employee_id': employee_id, 'employee_name': str(report.get('sender_name') or ''), 'status': status, 'summary': self._relay_progress_summary(status, task_id), 'raw': {'task_id': task_id, 'kind': 'super_employee'}})
            self._append_messages([progress])
            progress_rows.append(progress)

    @staticmethod
    def _super_employee_result_message_for_task(messages: list[dict[str, _facade().Any]], task_id: str) -> dict[str, _facade().Any] | None:
        for item in reversed(messages):
            if str(item.get('task_id') or '') != str(task_id):
                continue
            kind = str(item.get('kind') or '')
            if kind in {'codex_result', 'cursor_result', 'claude_result'}:
                return item
            if str(item.get('role') or '') == 'assistant' and kind != 'dispatcher' and str(item.get('body') or '').strip():
                return item
        return None

    @staticmethod
    def _super_employee_dispatch_message_for_task(messages: list[dict[str, _facade().Any]], task_id: str) -> dict[str, _facade().Any] | None:
        for item in reversed(messages):
            if str(item.get('task_id') or '') == str(task_id) and str(item.get('kind') or '') == 'dispatcher':
                return item
        return None

    @staticmethod
    def _super_employee_task_status(message: dict[str, _facade().Any] | None) -> str:
        if not isinstance(message, dict):
            return ''
        status = str(message.get('task_status') or message.get('status') or '').strip().lower()
        if status == 'merged':
            return 'completed'
        return status

    def _super_employee_result_task(self, *, user_id: int, group_id: str, report: dict[str, _facade().Any], result_msg: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        payload = report.get('payload') if isinstance(report.get('payload'), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        raw = payload.get('raw') if isinstance(payload.get('raw'), dict) else {}
        task_id = self._report_relay_task_id(report)
        status = self._super_employee_task_status(result_msg) or 'completed'
        body = str(result_msg.get('body') or '').strip()
        if not isinstance(raw, dict):
            raw = {}
        if not isinstance(report, dict):
            report = {}
        return {'created_by_user_id': int(user_id), 'task_id': task_id, 'relay_id': 'super_employee', 'kind': str(raw.get('kind') or raw.get('dispatcher') or 'super_employee'), 'status': status, 'payload': {'message': str(payload.get('task') or payload.get('original_task') or ''), 'context': {'source': 'mobile_ai_group', 'group_id': group_id, 'work_order_id': str(report.get('work_order_id') or payload.get('work_order_id') or ''), 'employee_id': str(payload.get('employee_id') or report.get('sender_id') or ''), 'assignment_focus': str(payload.get('assignment_focus') or ''), 'original_task': str(payload.get('original_task') or payload.get('task') or ''), 'branch': str(payload.get('branch_context') or payload.get('branch') or '')}}, 'result': {'summary': body, 'dispatcher': str(raw.get('dispatcher') or 'super_employee'), 'status': status, 'assistant_message': {'body': body}}}

    @staticmethod
    def _latest_progress_row(rows: list[dict[str, _facade().Any]], task_id: str) -> dict[str, _facade().Any] | None:
        for row in reversed(rows):
            if _facade().AiGroupChatService._report_relay_task_id(row) == task_id:
                return row
        return None

    @staticmethod
    def _should_append_progress(*, last: dict[str, _facade().Any] | None, status: str) -> bool:
        if last is None:
            return True
        last_status = str(last.get('status') or '').strip().lower()
        if last_status and last_status != status:
            return True
        last_at = _facade().AiGroupChatService._parse_created_at(str(last.get('created_at') or ''))
        if last_at is None:
            return True
        elapsed = (_facade().datetime.now(_facade().UTC) - last_at).total_seconds()
        return elapsed >= _facade().RELAY_PROGRESS_MIN_INTERVAL_SEC

    @staticmethod
    def _parse_created_at(value: str) -> _facade().datetime | None:
        raw = str(value or '').strip()
        if not raw:
            return None
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        try:
            parsed = _facade().datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=_facade().UTC)
        return parsed.astimezone(_facade().UTC)

    @staticmethod
    def _relay_progress_summary(status: str, task_id: str) -> str:
        label = {'queued': '还在服务器队列中', 'accepted': '执行端已接单', 'assigned': '执行端已接单', 'running': '电脑执行端正在处理', 'processing': '电脑执行端正在处理', 'in_progress': '电脑执行端正在处理'}.get(status, '还在处理中')
        return f'{label}，任务号：{task_id[:8]}。'

    @classmethod
    def _format_relay_progress_message(cls, *, report: dict[str, _facade().Any], task: dict[str, _facade().Any], status: str) -> str:
        name = str(report.get('sender_name') or '负责人')
        payload = report.get('payload') if isinstance(report.get('payload'), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        focus = str(payload.get('assignment_focus') or '').strip()
        branch = str(payload.get('branch_context') or payload.get('branch') or '').strip()
        task_id = str(task.get('task_id') or cls._report_relay_task_id(report))
        status_label = {'queued': '排队中', 'accepted': '已接单', 'assigned': '已接单', 'running': '执行中', 'processing': '执行中', 'in_progress': '执行中'}.get(status, '处理中')
        focus_line = f'负责：{focus}\n' if focus else ''
        branch_line = f'分支：{branch}\n' if branch else ''
        return f'【{name} 进度回访】\n状态：{status_label}\n{focus_line}{branch_line}结果：{cls._relay_progress_summary(status, task_id)}我会继续等执行端回写，不需要你退出重进。\n风险：暂无新的阻塞；如果执行端超时，群里会保留这条任务号方便追踪。\n下一步：继续执行，完成后自动发员工回报并交给小C验收。'

    def delete_message(self, *, user_id: int, group_id: str, message_id: str) -> dict[str, _facade().Any]:
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        msg_id = str(message_id or '').strip()
        if not msg_id:
            raise ValueError('消息不存在')
        rows = self._read_messages()
        target = next((r for r in rows if int(r.get('user_id') or 0) == int(user_id) and str(r.get('group_id')) == str(group_id) and (str(r.get('id')) == msg_id)), None)
        if target is None:
            raise ValueError('消息不存在')
        if str(target.get('role') or '') != 'user' or str(target.get('sender_id') or '') != 'user':
            raise ValueError('只能删除自己发送的消息')
        self._rewrite_messages([r for r in rows if str(r.get('id')) != msg_id])
        return {'deleted': True, 'id': msg_id}

    def append_relay_work_report(self, *, task: dict[str, _facade().Any]) -> dict[str, _facade().Any] | None:
        payload = task.get('payload') if isinstance(task.get('payload'), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        context = payload.get('context') if isinstance(payload.get('context'), dict) else {}
        if not isinstance(context, dict):
            context = {}
        if str(context.get('source') or '') != 'mobile_ai_group':
            return None
        user_id = int(task.get('created_by_user_id') or 0)
        group_id = str(context.get('group_id') or '').strip()
        employee_id = str(context.get('employee_id') or '').strip()
        task_id = str(task.get('task_id') or '').strip()
        if user_id <= 0 or not group_id or (not employee_id) or (not task_id):
            return None
        group = self._find(self._user_groups(user_id), group_id)
        if group is None:
            return None
        work_order_id = str(context.get('work_order_id') or '')
        existing = self._relay_report_message(user_id=user_id, group_id=group_id, task_id=task_id)
        if existing is not None:
            self._append_work_acceptance_if_ready(user_id=user_id, group_id=group_id, work_order_id=work_order_id)
            return self._public_message(existing)
        members = [m for m in group.get('members', []) if isinstance(m, dict)]
        member = next((m for m in members if str(m.get('employee_id') or '') == employee_id), {'employee_id': employee_id, 'name': employee_id, 'avatar': ''})
        report = self._relay_task_report(task=task, member=member)
        row = self._message_row(user_id=user_id, group_id=group_id, role='ai', sender_id=employee_id, sender_name=str(member.get('name') or employee_id), sender_avatar=str(member.get('avatar') or ''), body=self._format_work_report_message(member, report), kind='relay_work_report', status=str(report.get('status') or ''), work_order_id=work_order_id, payload=report)
        self._append_messages([row])
        self._append_work_acceptance_if_ready(user_id=user_id, group_id=group_id, work_order_id=work_order_id)
        return self._public_message(row)

    async def post_message(self, *, user_id: int, group_id: str, text: str, sender_name: str='我', mentions: list[str] | None=None, dispatch: bool=False, branch_context: str='', context: dict[str, _facade().Any] | None=None) -> dict[str, _facade().Any]:
        body = (text or '').strip()
        if not body:
            raise ValueError('message 不能为空')
        action_context = context if isinstance(context, dict) else {}
        tool_action = str(action_context.get('tool_action') or '').strip()
        branch_context = _facade()._normalize_branch_context(branch_context)
        group_id = self._resolve_group_id(user_id=user_id, group_id=group_id)
        groups = self._user_groups(user_id)
        group = self._find(groups, group_id)
        if group is None:
            raise ValueError('群不存在')
        members = _facade()._with_required_group_members([m for m in group.get('members', []) if isinstance(m, dict)])
        if members != group.get('members', []):
            group['members'] = members
            self._rewrite_groups(self._replace(self._all_groups(), group))
        user_msg = self._message_row(user_id=user_id, group_id=group_id, role='user', sender_id='user', sender_name=sender_name or '我', sender_avatar='', body=body, payload={'branch_context': branch_context} if dispatch and branch_context else None)
        new_messages = [user_msg]
        self._append_messages([user_msg])
        if tool_action == 'acceptance_followup':
            followup = self._append_acceptance_followup(user_id=user_id, group_id=group_id)
            if followup is not None:
                new_messages.append(followup)
            previews = self._latest_previews(user_id)
            return {'group': self._public_group(group, previews.get(str(group.get('id')))), 'messages': [self._public_message(m) for m in new_messages]}
        members = [m for m in group.get('members', []) if isinstance(m, dict)]
        history = self.get_messages(user_id=user_id, group_id=group_id, limit=_facade().CONTEXT_TURNS)
        work_orders: list[dict[str, _facade().Any]] = []
        if dispatch:
            responders = self._pick_dispatch_targets(members, body, mentions)
            discussion_messages: list[dict[str, _facade().Any]] = []
            if self._should_run_super_discussion(responders):
                (discussion_messages, responders) = await self._run_super_discussion_then_route(group=group, task=body, candidates=responders, user_id=user_id, history=history, mentions=mentions, persist=True)
                new_messages.extend(discussion_messages)
            (dispatch_messages, work_orders) = await self._dispatch_work(group=group, members=responders, task=body, user_id=user_id, sender_name=sender_name or '我', branch_context=branch_context, persist=True)
            new_messages.extend(dispatch_messages)
        else:
            responders = self._pick_responders(members, body, mentions)
            for member in responders:
                reply = await self._ai_reply(group, member, history, user_id=user_id)
                ai_msg = self._message_row(user_id=user_id, group_id=group_id, role='ai', sender_id=str(member.get('employee_id')), sender_name=str(member.get('name') or member.get('employee_id')), sender_avatar=str(member.get('avatar') or ''), body=reply)
                new_messages.append(ai_msg)
                self._append_messages([ai_msg])
                history = history + [self._public_message(ai_msg)]
        previews = self._latest_previews(user_id)
        result: dict[str, _facade().Any] = {'group': self._public_group(group, previews.get(str(group.get('id')))), 'messages': [self._public_message(m) for m in new_messages]}
        if dispatch:
            result['work_orders'] = work_orders
        return result

    def _append_acceptance_followup(self, *, user_id: int, group_id: str) -> dict[str, _facade().Any] | None:
        self._sync_relay_progress_for_group(user_id=user_id, group_id=group_id)
        self._sync_super_employee_progress_for_group(user_id=user_id, group_id=group_id)
        rows = [row for row in self._read_messages() if int(row.get('user_id') or 0) == int(user_id) and str(row.get('group_id') or '') == str(group_id)]
        work_orders = [row for row in rows if str(row.get('kind') or '') == 'work_order']
        if not work_orders:
            row = self._message_row(user_id=user_id, group_id=group_id, role='ai', sender_id=_facade()._XIAOC_ASSISTANT_ID, sender_name='小C助理', sender_avatar='', body='【小C回访】还没有可回访的派工单。\n先输入任务后点“任务派工”，我会在群里派负责人并收口验收。', kind='work_followup', status='empty')
            self._append_messages([row])
            return _facade().cast('dict[str, Any] | None', row)
        work_order = max(work_orders, key=lambda row: str(row.get('created_at') or ''))
        work_order_id = str(work_order.get('work_order_id') or '')
        had_acceptance = any((str(row.get('kind') or '') == 'work_acceptance' and str(row.get('work_order_id') or '') == work_order_id for row in rows))
        acceptance = self._append_work_acceptance_if_ready(user_id=user_id, group_id=group_id, work_order_id=work_order_id)
        if acceptance is not None and (not had_acceptance):
            return next((row for row in self._read_messages() if str(row.get('id') or '') == str(acceptance.get('id') or '')), None)
        body = self._format_acceptance_followup_message(work_order=work_order, rows=[row for row in self._read_messages() if str(row.get('work_order_id') or '') == work_order_id], had_acceptance=bool(acceptance))
        row = self._message_row(user_id=user_id, group_id=group_id, role='ai', sender_id=_facade()._XIAOC_ASSISTANT_ID, sender_name='小C助理', sender_avatar='', body=body, kind='work_followup', status='completed' if acceptance is not None else 'in_progress', work_order_id=work_order_id)
        self._append_messages([row])
        return _facade().cast('dict[str, Any] | None', row)

    @classmethod
    def _format_acceptance_followup_message(cls, *, work_order: dict[str, _facade().Any], rows: list[dict[str, _facade().Any]], had_acceptance: bool) -> str:
        payload = work_order.get('payload') if isinstance(work_order.get('payload'), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        task = str(payload.get('task') or '').strip() or cls._strip_label_from_body(str(work_order.get('body') or ''), '【小C派单】')
        if had_acceptance:
            return f'【小C回访】最新派工已有验收结论。\n任务：{task[:80]}\n你可以继续补充问题，或直接派下一步。'
        reports = [row for row in rows if str(row.get('kind') or '') in {'work_report', 'work_progress', 'relay_work_report'}]
        if not reports:
            return f'【小C回访】最新派工已发出，正在等待负责人接单或回报。\n任务：{task[:80]}\n我会继续把进度同步到群里。'
        latest_by_task: dict[str, dict[str, _facade().Any]] = {}
        for row in reports:
            task_id = cls._report_relay_task_id(row) or str(row.get('id') or '')
            old = latest_by_task.get(task_id)
            if old is None or str(row.get('created_at') or '') >= str(old.get('created_at') or ''):
                latest_by_task[task_id] = row
        lines = []
        for row in list(latest_by_task.values())[:6]:
            name = str(row.get('sender_name') or '负责人')
            status = cls._public_status_label(cls._effective_report_status(row))
            summary = cls._chat_friendly_summary(str(row.get('body') or ''), limit=54, include_detail_note=False)
            lines.append(f'- {name}：{status}。{summary}')
        return f'【小C回访】最新派工还在处理中。\n任务：{task[:80]}\n' + ('进度：\n' + '\n'.join(lines) + '\n' if lines else '') + '结论：暂未达到自动验收条件。'

    async def _execute_employee_work(self, *, group: dict[str, _facade().Any], member: dict[str, _facade().Any], task: str, assigned_task: str, assignment_focus: str, work_order_id: str, user_id: int, sender_name: str, branch_context: str='') -> dict[str, _facade().Any]:
        employee_id = str(member.get('employee_id') or '').strip()
        employee_name = str(member.get('name') or employee_id).strip()
        input_data = {'source': 'ai_group_chat', 'client_surface': 'ai_group', 'invoke_mode': 'group_dispatch', 'trigger': 'ai_group_dispatch', 'allow_medium_risk': True, 'group_id': str(group.get('id') or ''), 'group_name': str(group.get('name') or ''), 'work_order_id': work_order_id, 'employee_id': employee_id, 'employee_name': employee_name, 'original_task': task, 'assigned_task': assigned_task, 'assignment_focus': assignment_focus, 'sender_name': sender_name}
        if branch_context:
            input_data['branch'] = branch_context
            input_data['branch_context'] = branch_context
        try:
            if employee_id in _facade()._SUPER_EMPLOYEE_IDS and (not self._has_custom_employee_executor):
                raw = await _facade().asyncio.to_thread(self._invoke_super_employee_task, employee_id=employee_id, task=assigned_task, input_data=input_data, user_id=int(user_id))
            else:
                executor_result = self._employee_executor_fn(employee_id, assigned_task, input_data, int(user_id))
                raw = await executor_result if _facade().isawaitable(executor_result) else executor_result
            result = raw if isinstance(raw, dict) else {'success': False, 'status': 'failed', 'message': str(raw)}
            success = bool(result.get('success'))
            summary = self._execution_summary(result)
            result_status = str(result.get('status') or '').strip().lower()
            missing_evidence = success and (not self._has_custom_employee_executor) and (result_status in {'completed', 'done'}) and self._completed_report_lacks_required_evidence(assigned_task or task, summary, result)
            if success and self._summary_indicates_unfinished(summary):
                success = False
            if missing_evidence:
                success = False
            reassigned_from = ''
            if not success and employee_id in _facade()._SUPER_EMPLOYEE_IDS and (employee_id != 'claude-super-employee') and (not self._has_custom_employee_executor) and self._summary_indicates_unfinished(summary):
                claude_raw = await _facade().asyncio.to_thread(self._invoke_super_employee_task, employee_id='claude-super-employee', task=assigned_task, input_data={**input_data, 'reassigned_from': employee_id}, user_id=int(user_id))
                claude_result = claude_raw if isinstance(claude_raw, dict) else {'success': False}
                claude_summary = self._execution_summary(claude_result)
                claude_missing_evidence = self._completed_report_lacks_required_evidence(assigned_task or task, claude_summary, claude_result)
                claude_ok = bool(claude_result.get('success')) and (not self._summary_indicates_unfinished(claude_summary)) and (not claude_missing_evidence)
                if claude_ok:
                    reassigned_from = employee_id
                    (result, success, summary) = (claude_result, True, claude_summary)
                    (employee_id, employee_name) = ('claude-super-employee', 'Claude 超级员工')
                    missing_evidence = False
            status = str(result.get('status') or '').strip().lower()
            if not status or (status in {'completed', 'done'} and (not success)):
                status = 'done' if success else 'failed' if self._summary_indicates_failed(summary) else 'blocked'
            report = {'work_order_id': work_order_id, 'employee_id': employee_id, 'employee_name': employee_name, 'task': assigned_task, 'original_task': task, 'assignment_focus': assignment_focus, 'branch_context': branch_context, 'status': status, 'success': success, 'summary': summary, 'risk': '回报缺少改动文件、命令、测试、构建或安装证据，不能自动验收。' if missing_evidence else self._execution_risk(result, success), 'raw': self._compact_result(result)}
            if reassigned_from:
                report['reassigned_from'] = reassigned_from
            return report
        except _facade().RECOVERABLE_ERRORS as exc:
            return {'work_order_id': work_order_id, 'employee_id': employee_id, 'employee_name': employee_name, 'task': assigned_task, 'original_task': task, 'assignment_focus': assignment_focus, 'branch_context': branch_context, 'status': 'failed', 'success': False, 'summary': str(exc)[:500], 'risk': '执行入口异常，需要重试或改派。', 'raw': {'error': str(exc)[:500]}}

    def _invoke_super_employee_task(self, *, employee_id: str, task: str, input_data: dict[str, _facade().Any], user_id: int) -> dict[str, _facade().Any]:
        relay_result = self._create_super_employee_relay_task(employee_id=employee_id, task=task, input_data=input_data, user_id=user_id)
        if relay_result is not None:
            return relay_result
        service = self._super_employee_service(employee_id)
        branch_context = str(input_data.get('branch_context') or input_data.get('branch') or '')
        result = service.invoke(user_id=int(user_id), message=task, context={'mode': 'task', 'source': 'mobile_ai_group', 'group_id': input_data.get('group_id'), 'group_name': input_data.get('group_name'), 'work_order_id': input_data.get('work_order_id'), 'original_task': input_data.get('original_task') or task, 'assigned_task': input_data.get('assigned_task') or task, 'assignment_focus': input_data.get('assignment_focus') or '', **({'branch': branch_context} if branch_context else {})})
        dispatch = result.get('dispatch') if isinstance(result.get('dispatch'), dict) else {}
        assistant = result.get('assistant_message') if isinstance(result.get('assistant_message'), dict) else {}
        status = str(dispatch.get('status') or assistant.get('status') or 'queued').strip()
        accepted = dispatch.get('accepted') is True or status in {'queued', 'accepted', 'assigned', 'running', 'completed', 'done'}
        summary = str(assistant.get('body') or '').strip()
        if not summary:
            summary = '已进入超级员工执行队列。'
        return {'success': accepted, 'status': status or ('queued' if accepted else 'failed'), 'summary': summary, 'risk': '执行已交给对应超级员工；完成状态以该超级员工会话和派工回执为准。' if accepted else str(dispatch.get('reason') or '超级员工执行入口未接受任务'), 'dispatch_request_id': str(dispatch.get('request_id') or ''), 'task_id': str(dispatch.get('task_id') or ''), 'dispatcher': str(dispatch.get('dispatcher') or ''), 'branch_context': branch_context}

    def _create_super_employee_relay_task(self, *, employee_id: str, task: str, input_data: dict[str, _facade().Any], user_id: int) -> dict[str, _facade().Any] | None:
        kind = _facade()._SUPER_EMPLOYEE_RELAY_KINDS.get(employee_id)
        if not kind:
            return None
        try:
            relay = self._mobile_relay_service()
            desktop = self._latest_relay_desktop(relay.list_desktops(user_id=int(user_id)))
            relay_id = str((desktop or {}).get('relay_id') or '').strip()
            if not relay_id:
                return None
            relay_task = relay.create_task(user_id=int(user_id), relay_id=relay_id, kind=kind, payload={'message': task, **({'branch': input_data.get('branch_context') or input_data.get('branch')} if input_data.get('branch_context') or input_data.get('branch') else {}), 'context': {'source': 'mobile_ai_group', 'client_surface': 'ai_group', 'mode': 'code', 'group_id': input_data.get('group_id'), 'group_name': input_data.get('group_name'), 'work_order_id': input_data.get('work_order_id'), 'employee_id': employee_id, 'original_task': input_data.get('original_task') or task, 'assigned_task': input_data.get('assigned_task') or task, 'assignment_focus': input_data.get('assignment_focus') or '', **({'branch': input_data.get('branch_context') or input_data.get('branch')} if input_data.get('branch_context') or input_data.get('branch') else {})}})
        except _facade().RECOVERABLE_ERRORS:
            return None
        if not isinstance(relay_task, dict):
            return None
        relay_task_id = str(relay_task.get('task_id') or '').strip()
        if not relay_task_id:
            return None
        return {'success': True, 'status': str(relay_task.get('status') or 'queued'), 'summary': f'已接单，正在电脑执行端处理。任务号：{relay_task_id[:8]}。', 'risk': '暂无阻塞；执行完成后会自动回到群里汇报。', 'dispatch_request_id': relay_task_id, 'task_id': relay_task_id, 'dispatcher': 'mobile_relay', 'relay_id': relay_id, 'branch_context': str(input_data.get('branch_context') or input_data.get('branch') or '')}

    @staticmethod
    def _latest_relay_desktop(desktops: list[dict[str, _facade().Any]]) -> dict[str, _facade().Any] | None:
        candidates = [item for item in desktops if isinstance(item, dict) and str(item.get('relay_id') or '').strip() and (str(item.get('status') or '').strip().lower() == 'paired')]
        if not candidates:
            return None

        def sort_key(item: dict[str, _facade().Any]) -> str:
            return str(item.get('last_seen_at') or '').strip() or str(item.get('updated_at') or '').strip() or str(item.get('paired_at') or '').strip() or str(item.get('created_at') or '').strip()
        return max(candidates, key=sort_key)

    @staticmethod
    def _mobile_relay_service():
        from app.services.mobile_relay_service import MobileRelayService
        return MobileRelayService()

    @staticmethod
    def _super_employee_service(employee_id: str):
        from app.application.claude_super_employee_service import ClaudeSuperEmployeeService
        from app.application.codex_super_employee_service import CodexSuperEmployeeService
        from app.application.cursor_super_employee_service import CursorSuperEmployeeService
        from app.application.trae_super_employee_service import TraeSuperEmployeeService
        if employee_id == 'codex-super-employee':
            return CodexSuperEmployeeService()
        if employee_id == 'cursor-super-employee':
            return CursorSuperEmployeeService()
        if employee_id == 'trae-super-employee':
            return TraeSuperEmployeeService()
        return ClaudeSuperEmployeeService()

    @staticmethod
    def _format_work_order_message(task: str, target_names: list[str], *, assignments: list[dict[str, _facade().Any]] | None=None, branch_context: str='') -> str:
        if not target_names:
            return f'【派工失败】没有可派工成员。\n任务：{task}'
        owners = '、'.join((name for name in target_names if name)) or '群成员'
        assignment_lines = []
        for item in assignments or []:
            name = str(item.get('name') or item.get('employee_id') or '负责人')
            focus = str(item.get('assignment_focus') or '').strip()
            if focus and focus != '主负责人':
                assignment_lines.append(f'- {name}：{focus}')
        assignment_block = '\n分工：\n' + '\n'.join(assignment_lines) if assignment_lines else ''
        branch_line = f'工作分支：{branch_context}\n' if branch_context else '工作分支：自动隔离分支\n'
        return f'【小C派单】{task}\n负责人：{owners}\n{branch_line}{assignment_block}\n流程：接单 → 执行 → 回报 → 小C验收。\n你不用翻执行端，我会把最终结果收口到这条群聊里。'
