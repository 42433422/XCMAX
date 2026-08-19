# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.super_employee_service')

class _SuperEmployeeServicePart01Mixin:

    def __init__(self, profile: _facade().SuperEmployeeToolProfile, storage_root: str | _facade().Path | None=None, http_client_factory: _facade().Callable[[], _facade().httpx.Client] | None=None, cli_runner: _facade().Callable[..., _facade().subprocess.CompletedProcess[str]] | None=None) -> None:
        self._p = profile
        root = _facade().Path(storage_root) if storage_root is not None else _facade().Path(_facade().get_app_data_dir())
        self._messages = _facade().MessageRepository(root, profile.storage_subdir)
        self._git_mgr = _facade().GitWorkspaceManager(profile.tool_name, profile.employee_name, git_call=lambda cwd, *a, **k: self._git(cwd, *a, **k))
        self._root = self._messages.messages_path.parent
        self._messages_path = self._messages.messages_path
        self._outbox_dir = self._messages.outbox_dir
        self._http_client_factory = http_client_factory or self._default_http_client
        self._cli_runner = cli_runner or _facade().subprocess.run
        self._grant = _facade().CapabilityGrant.product()

    def list_messages(self, *, user_id: int, limit: int=80) -> list[dict[str, _facade().Any]]:
        uid = int(user_id)
        all_rows = self._read_all_message_rows()
        if not all_rows:
            return []
        direct_changed = self._upsert_direct_reply_messages(user_id=uid, rows=all_rows)
        self._sync_para_task_updates(user_id=uid, rows=all_rows)
        if direct_changed:
            self._write_all_message_rows(all_rows)
        rows = [self._public_message(item) for item in all_rows if int(item.get('user_id') or 0) == uid]
        return rows[-max(1, min(int(limit), 200)):]

    def invoke(self, *, user_id: int, message: str, context: dict[str, _facade().Any] | None=None) -> dict[str, _facade().Any]:
        text = (message or '').strip()
        if not text:
            raise ValueError('message 不能为空')
        ctx = context if isinstance(context, dict) else {}
        self._grant = _facade().CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get('force_cli_direct') is True
        token_attempt = bool(str(ctx.get(_facade().CONTEXT_TOKEN_KEY) or '').strip())
        ctx.pop(_facade().CONTEXT_TOKEN_KEY, None)
        if self._grant.is_factory:
            _facade().logger.info('super_employee factory dispatch user=%s workspace=%s tool=%s', user_id, self._grant.workspace_id, self._p.tool_name)
        elif token_attempt:
            _facade().logger.warning('super_employee factory token rejected, downgraded to product user=%s tool=%s', user_id, self._p.tool_name)
        request_id = _facade().uuid.uuid4().hex
        created_at = _facade()._utc_now()
        user_msg = self._message_row(user_id=int(user_id), role='user', body=text, created_at=created_at, request_id=request_id, status='sent')
        if self._should_reply_with_cli(text, ctx):
            (direct_body, direct_dispatcher) = self._compose_direct_chat_reply(text, ctx)
            assistant_msg = self._message_row(user_id=int(user_id), role='assistant', body=direct_body, created_at=_facade()._utc_now(), request_id=request_id, status='completed', extra={'kind': self._p.direct_kind})
            self._append_messages([user_msg, assistant_msg])
            dispatch = {'request_id': request_id, 'status': 'completed', 'accepted': True, 'queued': False, 'para_tier': 1, 'device_scope': 'local_device', 'dispatcher': direct_dispatcher}
            return {'employee': {'id': self._p.employee_id, 'name': self._p.employee_name, 'device_scope': 'all_devices'}, 'dispatch': dispatch, 'message': self._public_message(user_msg), 'assistant_message': self._public_message(assistant_msg), 'messages': self.list_messages(user_id=int(user_id))}
        dispatch_request = self._build_dispatch_request(request_id=request_id, created_at=created_at, user_id=int(user_id), message=text, context=ctx)
        dispatch = self._dispatch(dispatch_request)
        if dispatch.get('accepted') is not True:
            (fallback_body, fallback_dispatcher) = self._compose_direct_chat_reply(text, ctx)
            if fallback_body and (not fallback_body.startswith(f'{self._p.display_tool} CLI 暂时没有返回内容')):
                assistant_msg = self._message_row(user_id=int(user_id), role='assistant', body=fallback_body, created_at=_facade()._utc_now(), request_id=request_id, status='completed', extra={'kind': self._p.direct_kind})
                self._append_messages([user_msg, assistant_msg])
                return {'employee': {'id': self._p.employee_id, 'name': self._p.employee_name, 'device_scope': 'all_devices'}, 'dispatch': {**dispatch, 'status': 'completed', 'para_tier': 1, 'device_scope': 'local_device', 'fallback': fallback_dispatcher}, 'message': self._public_message(user_msg), 'assistant_message': self._public_message(assistant_msg), 'messages': self.list_messages(user_id=int(user_id))}
        dispatcher_msg = self._message_row(user_id=int(user_id), role='system', body=self._dispatch_reply(dispatch), created_at=_facade()._utc_now(), request_id=request_id, status=str(dispatch.get('status') or 'queued'), extra={'kind': _facade().DISPATCHER_MESSAGE_KIND, 'task_id': str(dispatch.get('task_id') or ''), 'task_status': str(dispatch.get('task_status') or ''), 'dispatcher': str(dispatch.get('dispatcher') or ''), 'scope': self._grant.scope.value, 'workspace_id': self._grant.workspace_id or '', 'para_tier': dispatch.get('para_tier'), 'devices': dispatch.get('devices') if isinstance(dispatch.get('devices'), list) else []})
        self._append_messages([user_msg, dispatcher_msg])
        return {'employee': {'id': self._p.employee_id, 'name': self._p.employee_name, 'device_scope': 'all_devices'}, 'dispatch': dispatch, 'message': self._public_message(user_msg), 'assistant_message': self._public_message(dispatcher_msg), 'messages': self.list_messages(user_id=int(user_id))}

    async def invoke_stream(self, *, user_id: int, message: str, context: dict[str, _facade().Any] | None=None) -> _facade().AsyncIterator[dict[str, _facade().Any]]:
        """LAN 模式下的流式直答：跳过 Para 派工，直接本地 CLI 执行并逐事件 yield。

        yield 事件格式：
        - {"type": "status", "text": "..."} — 状态提示（已连接/思考中/执行中）
        - {"type": "token", "text": "..."} — 文本片段（逐字/逐块）
        - {"type": "done", "result": {...}} — 完成，含最终回复
        - {"type": "error", "message": "..."} — 失败
        """
        text = (message or '').strip()
        if not text:
            yield {'type': 'error', 'message': 'message 不能为空'}
            return
        ctx = context if isinstance(context, dict) else {}
        self._grant = _facade().CapabilityGrant.resolve(ctx)
        self._relay_cli_trusted = ctx.get('force_cli_direct') is True
        ctx.pop(_facade().CONTEXT_TOKEN_KEY, None)
        canned = self._direct_reply_body(text)
        if canned:
            yield {'type': 'status', 'text': f'已连接 {self._p.display_tool}'}
            for chunk in _facade()._chunk_text(canned):
                yield {'type': 'token', 'text': chunk}
                await _facade().asyncio.sleep(0.02)
            yield {'type': 'done', 'result': {'response': canned, 'dispatcher': 'faq'}}
            return
        cli_path = self._cli_path()
        if not cli_path:
            (fallback_body, dispatcher) = self._compose_direct_chat_reply(text, ctx)
            yield {'type': 'status', 'text': f'已连接 {self._p.display_tool}'}
            for chunk in _facade()._chunk_text(fallback_body):
                yield {'type': 'token', 'text': chunk}
                await _facade().asyncio.sleep(0.02)
            yield {'type': 'done', 'result': {'response': fallback_body, 'dispatcher': dispatcher}}
            return
        base_cwd = self._cli_workspace(ctx)
        is_task = self._is_task_intent(text, ctx)
        if is_task and self._dev_loop_enabled() and (self._cli_runner is _facade().subprocess.run):
            yield {'type': 'status', 'text': f'{self._p.display_tool} 开始开发任务…'}
            try:
                body = await _facade().asyncio.to_thread(self._run_dev_task_loop, cli_path, text, base_cwd, ctx)
                yield {'type': 'status', 'text': '开发任务完成，正在整理回复…'}
                for chunk in _facade()._chunk_text(body):
                    yield {'type': 'token', 'text': chunk}
                    await _facade().asyncio.sleep(0.03)
                yield {'type': 'done', 'result': {'response': body, 'dispatcher': 'dev_loop'}}
            except _facade().RECOVERABLE_ERRORS as exc:
                _facade().logger.exception('invoke_stream dev_loop failed: %s', exc)
                yield {'type': 'error', 'message': f'开发任务执行失败：{exc}'}
            return
        prompt = self._cli_prompt(text) if not is_task else self._cli_work_prompt(text, base_cwd)
        yield {'type': 'status', 'text': f'{self._p.display_tool} 正在思考…'}
        try:
            final_text = ''
            async for event in self._run_cli_streaming(cli_path, prompt, base_cwd):
                if event['type'] == 'token':
                    final_text += event['text']
                    yield event
                elif event['type'] == 'status':
                    yield event
                elif event['type'] == 'done':
                    final_text = event.get('text', final_text)
                elif event['type'] == 'error':
                    yield event
                    return
            body = final_text.strip()
            if not body:
                body = f'{self._p.display_tool} CLI 暂时没有返回内容，请确认本机 {self._p.display_tool} 已登录后重试。'
            yield {'type': 'done', 'result': {'response': body, 'dispatcher': 'cli_stream'}}
        except _facade().RECOVERABLE_ERRORS as exc:
            _facade().logger.exception('invoke_stream cli failed: %s', exc)
            yield {'type': 'error', 'message': f'{self._p.display_tool} CLI 调用失败：{exc}'}

    async def _run_cli_streaming(self, cli_path: str, prompt: str, cwd: str) -> _facade().AsyncIterator[dict[str, _facade().Any]]:
        """异步执行 CLI，逐行读取 stdout 并 yield 事件。

        - stream-json 工具（claude/cursor/trae）：每行是 JSON 事件，解析出 text token
        - 非 stream-json 工具（codex）：stdout 不是结果，读 output-last-message 文件
        """
        with _facade().tempfile.TemporaryDirectory(prefix=f'xcagi-{self._p.tool_name}-stream-') as tmp:
            output_path = _facade().Path(tmp) / 'last_message.txt'
            cmd = self._apply_scope_to_cmd(self._p.cli_command_builder(cli_path, prompt, output_path, cwd))
            env = self._cli_subprocess_env()
            try:
                proc = await _facade().asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdout=_facade().asyncio.subprocess.PIPE, stderr=_facade().asyncio.subprocess.PIPE, env=env)
            except (OSError, FileNotFoundError) as exc:
                yield {'type': 'error', 'message': f'{self._p.display_tool} CLI 启动失败：{exc}'}
                return
            idle_timeout = self._cli_idle_timeout_seconds()
            hard_cap = self._cli_hard_cap_seconds()
            started = _facade().time.monotonic()
            last_activity = _facade().time.monotonic()
            stream_json = self._p.cli_stream_json
            text_parts: list[str] = []

            async def _read_stderr() -> str:
                if proc.stderr is None:
                    return ''
                try:
                    data = await _facade().asyncio.wait_for(proc.stderr.read(), timeout=2.0)
                    return data.decode('utf-8', errors='replace')
                except TimeoutError:
                    return ''
            while True:
                if proc.stdout is None:
                    break
                try:
                    raw_line = await _facade().asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
                except TimeoutError:
                    now = _facade().time.monotonic()
                    if idle_timeout > 0 and now - last_activity > idle_timeout:
                        proc.kill()
                        yield {'type': 'error', 'message': f'{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无输出，判定卡住。'}
                        return
                    if hard_cap > 0 and now - started > hard_cap:
                        proc.kill()
                        yield {'type': 'error', 'message': f'{self._p.display_tool} CLI 运行超过 {hard_cap:g} 秒，已停止。'}
                        return
                    continue
                if not raw_line:
                    break
                last_activity = _facade().time.monotonic()
                line = raw_line.decode('utf-8', errors='replace').rstrip()
                if not line:
                    continue
                if stream_json and line.startswith('{'):
                    token = self._parse_stream_json_line(line)
                    if token:
                        text_parts.append(token)
                        yield {'type': 'token', 'text': token}
            await proc.wait()
            returncode = int(proc.returncode or 0)
            if stream_json:
                body = ''.join(text_parts).strip()
                if body:
                    yield {'type': 'done', 'text': body}
                    return
                if returncode != 0:
                    stderr_text = await _read_stderr()
                    yield {'type': 'error', 'message': f'{self._p.display_tool} CLI 返回失败（code {returncode}）：{stderr_text[:300]}'}
                    return
                yield {'type': 'done', 'text': ''}
                return
            if self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding='utf-8', errors='replace').strip()
                if body:
                    yield {'type': 'done', 'text': body}
                    return
            if returncode != 0:
                stderr_text = await _read_stderr()
                yield {'type': 'error', 'message': f'{self._p.display_tool} CLI 返回失败（code {returncode}）：{stderr_text[:300]}'}
                return
            yield {'type': 'done', 'text': ''}

    def _parse_stream_json_line(self, line: str) -> str:
        """解析单行 stream-json 事件，返回文本 token（无文本则空串）。"""
        try:
            ev = _facade().json.loads(line)
        except _facade().json.JSONDecodeError:
            return ''
        if not isinstance(ev, dict):
            return ''
        ev_type = ev.get('type')
        if ev_type == 'assistant':
            msg = ev.get('message') if isinstance(ev.get('message'), dict) else {}
            if not isinstance(msg, dict):
                msg = {}
            for blk in msg.get('content') or []:
                if isinstance(blk, dict) and blk.get('type') == 'text':
                    t = str(blk.get('text') or '')
                    if t:
                        return t
        elif ev_type == 'result':
            r = ev.get('result')
            if isinstance(r, str) and r.strip():
                return r
        elif ev_type == 'content_block_delta':
            delta = ev.get('delta') if isinstance(ev.get('delta'), dict) else {}
            if not isinstance(delta, dict):
                delta = {}
            t = str(delta.get('text') or '')
            if t:
                return t
        elif ev_type == 'message_delta':
            t = str(ev.get('text') or '')
            if t:
                return t
        return ''

    def _build_dispatch_request(self, *, request_id: str, created_at: str, user_id: int, message: str, context: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        if self._grant.is_factory:
            workspace_root = self._factory_workspace_root()
        else:
            workspace_root = ''
        raw_source = str(context.get('source') or 'admin_im').strip().lower()
        source = 'xcagi_mobile_im' if raw_source.startswith('mobile') else 'xcagi_admin_im'
        return {'request_id': request_id, 'created_at': created_at, 'source': source, 'employee_id': self._p.employee_id, 'employee_name': self._p.employee_name, 'mode': str(context.get('mode') or 'code'), 'device_scope': 'all_devices', 'target_devices': context.get('target_devices') if isinstance(context.get('target_devices'), list) else ['all'], 'user_id': user_id, 'title': message[:120], 'task': message, 'prompt': message, 'workspace_root': workspace_root, 'scope': self._grant.scope.value, 'workspace_id': self._grant.workspace_id or '', 'raw_context': {k: v for (k, v) in context.items() if k != _facade().CONTEXT_TOKEN_KEY}}

    def _dispatch(self, request: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        mode = (_facade().os.environ.get(f'{self._p.env_super_prefix}_DISPATCH_MODE') or _facade().os.environ.get('MODSTORE_PARA_DISPATCH_MODE') or 'auto').strip().lower()
        if mode in {'auto', 'para', 'devfleet', 'mcp'}:
            (para_dispatch, para_reason) = self._dispatch_to_para(request)
            if para_dispatch is not None:
                return para_dispatch
            if mode != 'auto':
                return self._write_outbox(request, status='queued', accepted=False, reason=para_reason or 'para_dispatcher_unavailable')
        else:
            para_reason = ''
        if mode == 'outbox':
            return self._write_outbox(request, status='queued', accepted=False, reason='dispatch_mode_outbox')
        webhook = (_facade().os.environ.get(f'{self._p.env_super_prefix}_WEBHOOK') or _facade().os.environ.get('MODSTORE_PARA_DELEGATE_WEBHOOK') or '').strip()
        if not webhook:
            return self._write_outbox(request, status='queued', accepted=False, reason=para_reason or f'{self._p.tool_name}_dispatch_webhook_not_configured')
        try:
            with self._http_client_factory() as client:
                resp = client.post(webhook, json=request)
            body: _facade().Any
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {'raw': resp.text[:1000]}
            accepted = resp.status_code < 400 and (body.get('ok') is True or body.get('success') is True or body.get('accepted') is True)
            if accepted:
                return {'request_id': request['request_id'], 'status': 'accepted', 'accepted': True, 'queued': False, 'device_scope': 'all_devices', 'response': body}
            return self._write_outbox(request, status='dispatch_failed', accepted=False, reason=str(body.get('error') or body.get('message') or f'HTTP {resp.status_code}')[:500])
        except _facade().RECOVERABLE_ERRORS as exc:
            return self._write_outbox(request, status='dispatch_error', accepted=False, reason=str(exc)[:500])

    def _dispatch_to_para(self, request: dict[str, _facade().Any]) -> tuple[dict[str, _facade().Any] | None, str]:
        api_url = self._para_api_url()
        if not api_url:
            return (None, 'para_dispatcher_disabled')
        try:
            with self._http_client_factory() as client:
                health = client.get(f'{api_url}/api/health')
                if health.status_code >= 400:
                    return (None, f'para_api_unhealthy_http_{health.status_code}')
                token = self._para_token(client, api_url)
                devices_body = self._para_request(client, api_url, token, 'GET', '/api/devices')
                devices = devices_body.get('devices') if isinstance(devices_body, dict) else []
                (tier, selected) = self._select_devices_by_tier(devices if isinstance(devices, list) else [], request)
                if not selected:
                    return (self._write_outbox(request, status='queued', accepted=False, reason=f'para_no_online_{self._p.tool_name}_device'), f'para_no_online_{self._p.tool_name}_device')
                prepared = []
                for device in selected:
                    prepared.append(self._ensure_para_device(client, api_url, token, device))
                return (self._create_para_task(client, api_url, token, request, prepared, tier=tier), '')
        except (_facade().httpx.TimeoutException, _facade().httpx.ConnectError, _facade().httpx.NetworkError) as exc:
            return (None, f'para_api_unreachable: {exc}')
        except _facade().RECOVERABLE_ERRORS as exc:
            return (self._write_outbox(request, status='dispatch_error', accepted=False, reason=f'para_dispatch_error: {str(exc)[:460]}'), str(exc)[:500])

    def _default_http_client(self) -> _facade().httpx.Client:
        timeout = float(_facade().os.environ.get(f'{self._p.env_tool_prefix}_DISPATCH_TIMEOUT_SEC') or _facade().os.environ.get(f'{self._p.env_tool_prefix}_WEBHOOK_TIMEOUT_SEC') or '30')
        return _facade().httpx.Client(timeout=timeout)

    def _para_api_url(self) -> str:
        value = (_facade().os.environ.get(f'{self._p.env_super_prefix}_PARA_API_URL') or _facade().os.environ.get('MODSTORE_PARA_API_URL') or _facade().os.environ.get('DEVFLEET_API_URL') or _facade().DEFAULT_PARA_API_URL).strip().rstrip('/')
        if value.lower() in {'', '0', 'false', 'off', 'none', 'disabled'}:
            return ''
        return value

    def _para_token(self, client: _facade().httpx.Client, api_url: str) -> str:
        token = (_facade().os.environ.get(f'{self._p.env_super_prefix}_PARA_TOKEN') or _facade().os.environ.get('MODSTORE_PARA_TOKEN') or _facade().os.environ.get('DEVFLEET_TOKEN') or '').strip()
        if token:
            return token
        cache_key = (api_url, self._p.env_super_prefix)
        cached = _facade()._PARA_TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > _facade().time.time():
            return cached[0]
        resp = client.post(f'{api_url}/api/auth/guest', json={})
        body = self._json_response(resp)
        if resp.status_code >= 400:
            _facade()._PARA_TOKEN_CACHE.pop(cache_key, None)
            raise RuntimeError(self._error_message(body, f'Para guest 登录失败 ({resp.status_code})'))
        token = str(body.get('token') or body.get('access_token') or '').strip()
        if not token:
            _facade()._PARA_TOKEN_CACHE.pop(cache_key, None)
            raise RuntimeError('Para guest 登录未返回 token')
        _facade()._PARA_TOKEN_CACHE[cache_key] = (token, _facade().time.time() + _facade()._PARA_TOKEN_TTL)
        return token

    def _para_request(self, client: _facade().httpx.Client, api_url: str, token: str, method: str, path: str, *, json_body: dict[str, _facade().Any] | None=None) -> dict[str, _facade().Any]:
        resp = client.request(method, f'{api_url}{path}', headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, json=json_body)
        body = self._json_response(resp)
        if resp.status_code >= 400:
            raise RuntimeError(self._error_message(body, f'Para API 请求失败 ({resp.status_code})'))
        return body

    def _device_eligible(self, item: _facade().Any) -> bool:
        """单台设备能否承接派工：在线 + 目标工具已装且非占用 + 具备能力。

        一级(本机单设备)与二级(多设备)选择共用此判定；不含 target_devices
        过滤(由各调用方按需另行处理)。
        """
        if not isinstance(item, dict):
            return False
        if str(item.get('status') or '') != 'online':
            return False
        tool = self._device_tool(item, self._p.tool_name)
        if tool and str(tool.get('status') or '') == 'not_installed':
            return False
        if tool and str(tool.get('status') or '') == 'running' and tool.get('currentTask'):
            return False
        capabilities = item.get('capabilities') if isinstance(item.get('capabilities'), dict) else {}
        if not isinstance(capabilities, dict):
            capabilities = {}
        if not tool and capabilities.get(self._p.capability_key) is not True:
            return False
        return True

    def _select_para_devices(self, devices: list[_facade().Any], request: dict[str, _facade().Any]) -> list[dict[str, _facade().Any]]:
        target_devices = request.get('target_devices')
        targets = {str(item).strip() for item in target_devices if str(item).strip()} if isinstance(target_devices, list) else {'all'}
        candidates: list[dict[str, _facade().Any]] = []
        for item in devices:
            if not self._device_eligible(item):
                continue
            if 'all' not in targets and str(item.get('id') or '') not in targets and (str(item.get('name') or '') not in targets):
                continue
            candidates.append(item)
        workers = [item for item in candidates if not item.get('isPrimary')]
        selected = workers or candidates
        max_devices = self._max_para_devices(request)
        return selected[:max_devices]

    def _local_device_id(self) -> str:
        """配置的本机设备 ID(可选)。未配则按 is_primary / 首台合格设备兜底。"""
        return (_facade().os.environ.get(f'{self._p.env_super_prefix}_DEVICE_ID') or _facade().os.environ.get('MODSTORE_PARA_DEVICE_ID') or _facade().os.environ.get('DEVFLEET_DEVICE_ID') or '').strip()
