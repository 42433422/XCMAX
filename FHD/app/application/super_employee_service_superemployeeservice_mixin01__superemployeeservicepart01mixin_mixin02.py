# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


class __SuperEmployeeServicePart01MixinPart02Mixin:
    async def _run_cli_streaming(
        self, cli_path: str, prompt: str, cwd: str
    ) -> _facade().AsyncIterator[dict[str, _facade().Any]]:
        """异步执行 CLI，逐行读取 stdout 并 yield 事件。

        - stream-json 工具（claude/cursor/trae）：每行是 JSON 事件，解析出 text token
        - 非 stream-json 工具（codex）：stdout 不是结果，读 output-last-message 文件
        """
        with _facade().tempfile.TemporaryDirectory(
            prefix=f"xcagi-{self._p.tool_name}-stream-"
        ) as tmp:
            output_path = _facade().Path(tmp) / "last_message.txt"
            cmd = self._apply_scope_to_cmd(
                self._p.cli_command_builder(cli_path, prompt, output_path, cwd)
            )
            env = self._cli_subprocess_env()
            try:
                proc = await _facade().asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=cwd,
                    stdout=_facade().asyncio.subprocess.PIPE,
                    stderr=_facade().asyncio.subprocess.PIPE,
                    env=env,
                )
            except (OSError, FileNotFoundError) as exc:
                yield {"type": "error", "message": f"{self._p.display_tool} CLI 启动失败：{exc}"}
                return
            idle_timeout = self._cli_idle_timeout_seconds()
            hard_cap = self._cli_hard_cap_seconds()
            started = _facade().time.monotonic()
            last_activity = _facade().time.monotonic()
            stream_json = self._p.cli_stream_json
            text_parts: list[str] = []

            async def _read_stderr() -> str:
                if proc.stderr is None:
                    return ""
                try:
                    data = await _facade().asyncio.wait_for(proc.stderr.read(), timeout=2.0)
                    return data.decode("utf-8", errors="replace")
                except TimeoutError:
                    return ""

            while True:
                if proc.stdout is None:
                    break
                try:
                    raw_line = await _facade().asyncio.wait_for(proc.stdout.readline(), timeout=3.0)
                except TimeoutError:
                    now = _facade().time.monotonic()
                    if idle_timeout > 0 and now - last_activity > idle_timeout:
                        proc.kill()
                        yield {
                            "type": "error",
                            "message": f"{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无输出，判定卡住。",
                        }
                        return
                    if hard_cap > 0 and now - started > hard_cap:
                        proc.kill()
                        yield {
                            "type": "error",
                            "message": f"{self._p.display_tool} CLI 运行超过 {hard_cap:g} 秒，已停止。",
                        }
                        return
                    continue
                if not raw_line:
                    break
                last_activity = _facade().time.monotonic()
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                if stream_json and line.startswith("{"):
                    token = self._parse_stream_json_line(line)
                    if token:
                        text_parts.append(token)
                        yield {"type": "token", "text": token}
            await proc.wait()
            returncode = int(proc.returncode or 0)
            if stream_json:
                body = "".join(text_parts).strip()
                if body:
                    yield {"type": "done", "text": body}
                    return
                if returncode != 0:
                    stderr_text = await _read_stderr()
                    yield {
                        "type": "error",
                        "message": f"{self._p.display_tool} CLI 返回失败（code {returncode}）：{stderr_text[:300]}",
                    }
                    return
                yield {"type": "done", "text": ""}
                return
            if self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding="utf-8", errors="replace").strip()
                if body:
                    yield {"type": "done", "text": body}
                    return
            if returncode != 0:
                stderr_text = await _read_stderr()
                yield {
                    "type": "error",
                    "message": f"{self._p.display_tool} CLI 返回失败（code {returncode}）：{stderr_text[:300]}",
                }
                return
            yield {"type": "done", "text": ""}

    def _parse_stream_json_line(self, line: str) -> str:
        """解析单行 stream-json 事件，返回文本 token（无文本则空串）。"""
        try:
            ev = _facade().json.loads(line)
        except _facade().json.JSONDecodeError:
            return ""
        if not isinstance(ev, dict):
            return ""
        ev_type = ev.get("type")
        if ev_type == "assistant":
            msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
            if not isinstance(msg, dict):
                msg = {}
            for blk in msg.get("content") or []:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    t = str(blk.get("text") or "")
                    if t:
                        return t
        elif ev_type == "result":
            r = ev.get("result")
            if isinstance(r, str) and r.strip():
                return r
        elif ev_type == "content_block_delta":
            delta = ev.get("delta") if isinstance(ev.get("delta"), dict) else {}
            if not isinstance(delta, dict):
                delta = {}
            t = str(delta.get("text") or "")
            if t:
                return t
        elif ev_type == "message_delta":
            t = str(ev.get("text") or "")
            if t:
                return t
        return ""

    def _build_dispatch_request(
        self,
        *,
        request_id: str,
        created_at: str,
        user_id: int,
        message: str,
        context: dict[str, _facade().Any],
    ) -> dict[str, _facade().Any]:
        if self._grant.is_factory:
            workspace_root = self._factory_workspace_root()
        else:
            workspace_root = ""
        raw_source = str(context.get("source") or "admin_im").strip().lower()
        source = "xcagi_mobile_im" if raw_source.startswith("mobile") else "xcagi_admin_im"
        return {
            "request_id": request_id,
            "created_at": created_at,
            "source": source,
            "employee_id": self._p.employee_id,
            "employee_name": self._p.employee_name,
            "mode": str(context.get("mode") or "code"),
            "device_scope": "all_devices",
            "target_devices": context.get("target_devices")
            if isinstance(context.get("target_devices"), list)
            else ["all"],
            "user_id": user_id,
            "title": message[:120],
            "task": message,
            "prompt": message,
            "workspace_root": workspace_root,
            "scope": self._grant.scope.value,
            "workspace_id": self._grant.workspace_id or "",
            "raw_context": {k: v for k, v in context.items() if k != _facade().CONTEXT_TOKEN_KEY},
        }

    def _dispatch(self, request: dict[str, _facade().Any]) -> dict[str, _facade().Any]:
        mode = (
            (
                _facade().os.environ.get(f"{self._p.env_super_prefix}_DISPATCH_MODE")
                or _facade().os.environ.get("MODSTORE_PARA_DISPATCH_MODE")
                or "auto"
            )
            .strip()
            .lower()
        )
        if mode in {"auto", "para", "devfleet", "mcp"}:
            para_dispatch, para_reason = self._dispatch_to_para(request)
            if para_dispatch is not None:
                return para_dispatch
            if mode != "auto":
                return self._write_outbox(
                    request,
                    status="queued",
                    accepted=False,
                    reason=para_reason or "para_dispatcher_unavailable",
                )
        else:
            para_reason = ""
        if mode == "outbox":
            return self._write_outbox(
                request, status="queued", accepted=False, reason="dispatch_mode_outbox"
            )
        webhook = (
            _facade().os.environ.get(f"{self._p.env_super_prefix}_WEBHOOK")
            or _facade().os.environ.get("MODSTORE_PARA_DELEGATE_WEBHOOK")
            or ""
        ).strip()
        if not webhook:
            return self._write_outbox(
                request,
                status="queued",
                accepted=False,
                reason=para_reason or f"{self._p.tool_name}_dispatch_webhook_not_configured",
            )
        try:
            with self._http_client_factory() as client:
                resp = client.post(webhook, json=request)
            body: _facade().Any
            try:
                body = resp.json() if resp.content else {}
            except ValueError:
                body = {"raw": resp.text[:1000]}
            accepted = resp.status_code < 400 and (
                body.get("ok") is True
                or body.get("success") is True
                or body.get("accepted") is True
            )
            if accepted:
                return {
                    "request_id": request["request_id"],
                    "status": "accepted",
                    "accepted": True,
                    "queued": False,
                    "device_scope": "all_devices",
                    "response": body,
                }
            return self._write_outbox(
                request,
                status="dispatch_failed",
                accepted=False,
                reason=str(body.get("error") or body.get("message") or f"HTTP {resp.status_code}")[
                    :500
                ],
            )
        except _facade().RECOVERABLE_ERRORS as exc:
            return self._write_outbox(
                request, status="dispatch_error", accepted=False, reason=str(exc)[:500]
            )

    def _dispatch_to_para(
        self, request: dict[str, _facade().Any]
    ) -> tuple[dict[str, _facade().Any] | None, str]:
        api_url = self._para_api_url()
        if not api_url:
            return (None, "para_dispatcher_disabled")
        try:
            with self._http_client_factory() as client:
                health = client.get(f"{api_url}/api/health")
                if health.status_code >= 400:
                    return (None, f"para_api_unhealthy_http_{health.status_code}")
                token = self._para_token(client, api_url)
                devices_body = self._para_request(client, api_url, token, "GET", "/api/devices")
                devices = devices_body.get("devices") if isinstance(devices_body, dict) else []
                tier, selected = self._select_devices_by_tier(
                    devices if isinstance(devices, list) else [], request
                )
                if not selected:
                    return (
                        self._write_outbox(
                            request,
                            status="queued",
                            accepted=False,
                            reason=f"para_no_online_{self._p.tool_name}_device",
                        ),
                        f"para_no_online_{self._p.tool_name}_device",
                    )
                prepared = []
                for device in selected:
                    prepared.append(self._ensure_para_device(client, api_url, token, device))
                return (
                    self._create_para_task(client, api_url, token, request, prepared, tier=tier),
                    "",
                )
        except (
            _facade().httpx.TimeoutException,
            _facade().httpx.ConnectError,
            _facade().httpx.NetworkError,
        ) as exc:
            return (None, f"para_api_unreachable: {exc}")
        except _facade().RECOVERABLE_ERRORS as exc:
            return (
                self._write_outbox(
                    request,
                    status="dispatch_error",
                    accepted=False,
                    reason=f"para_dispatch_error: {str(exc)[:460]}",
                ),
                str(exc)[:500],
            )

    def _default_http_client(self) -> _facade().httpx.Client:
        timeout = float(
            _facade().os.environ.get(f"{self._p.env_tool_prefix}_DISPATCH_TIMEOUT_SEC")
            or _facade().os.environ.get(f"{self._p.env_tool_prefix}_WEBHOOK_TIMEOUT_SEC")
            or "30"
        )
        return _facade().httpx.Client(timeout=timeout)

    def _para_api_url(self) -> str:
        value = (
            (
                _facade().os.environ.get(f"{self._p.env_super_prefix}_PARA_API_URL")
                or _facade().os.environ.get("MODSTORE_PARA_API_URL")
                or _facade().os.environ.get("DEVFLEET_API_URL")
                or _facade().DEFAULT_PARA_API_URL
            )
            .strip()
            .rstrip("/")
        )
        if value.lower() in {"", "0", "false", "off", "none", "disabled"}:
            return ""
        return value

    def _para_token(self, client: _facade().httpx.Client, api_url: str) -> str:
        token = (
            _facade().os.environ.get(f"{self._p.env_super_prefix}_PARA_TOKEN")
            or _facade().os.environ.get("MODSTORE_PARA_TOKEN")
            or _facade().os.environ.get("DEVFLEET_TOKEN")
            or ""
        ).strip()
        if token:
            return token
        cache_key = (api_url, self._p.env_super_prefix)
        cached = _facade()._PARA_TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > _facade().time.time():
            return cached[0]
        resp = client.post(f"{api_url}/api/auth/guest", json={})
        body = self._json_response(resp)
        if resp.status_code >= 400:
            _facade()._PARA_TOKEN_CACHE.pop(cache_key, None)
            raise RuntimeError(
                self._error_message(body, f"Para guest 登录失败 ({resp.status_code})")
            )
        token = str(body.get("token") or body.get("access_token") or "").strip()
        if not token:
            _facade()._PARA_TOKEN_CACHE.pop(cache_key, None)
            raise RuntimeError("Para guest 登录未返回 token")
        _facade()._PARA_TOKEN_CACHE[cache_key] = (
            token,
            _facade().time.time() + _facade()._PARA_TOKEN_TTL,
        )
        return token
