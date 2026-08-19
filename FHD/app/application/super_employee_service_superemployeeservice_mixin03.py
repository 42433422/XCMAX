# ruff: noqa
# mypy: ignore-errors
"""Behavior mixin extracted from the public facade class."""
from __future__ import annotations
import importlib

def _facade():
    return importlib.import_module('app.application.super_employee_service')

class _SuperEmployeeServicePart03Mixin:

    def _run_cli_once(self, cli_path: str, prompt: str, cwd: str) -> str:
        """运行一次 CLI 取最终回复文本（coding/闲聊共用；含测试注入与 idle-timeout 两路）。"""
        idle_timeout = self._cli_idle_timeout_seconds()
        hard_cap = self._cli_hard_cap_seconds()
        with _facade().tempfile.TemporaryDirectory(prefix=f'xcagi-{self._p.tool_name}-cli-') as tmp:
            output_path = _facade().Path(tmp) / 'last_message.txt'
            cmd = self._apply_scope_to_cmd(self._p.cli_command_builder(cli_path, prompt, output_path, cwd))
            if self._cli_runner is not _facade().subprocess.run:
                try:
                    proc = self._cli_runner(cmd, text=True, capture_output=True, cwd=cwd)
                except (OSError, _facade().subprocess.SubprocessError) as exc:
                    return f'{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}'
                returncode = int(getattr(proc, 'returncode', 0) or 0)
                stdout = str(getattr(proc, 'stdout', '') or '')
                stderr = str(getattr(proc, 'stderr', '') or '')
                killed_reason = ''
            else:
                try:
                    (returncode, stdout, stderr, killed_reason) = self._run_cli_idle(cmd, cwd, idle_timeout, hard_cap)
                except (OSError, _facade().subprocess.SubprocessError) as exc:
                    return f'{self._p.display_tool} CLI 调用失败：{str(exc)[:300]}'
            if killed_reason.startswith('idle'):
                return f'{self._p.display_tool} CLI 静默 {idle_timeout:g} 秒无任何输出，判定卡住已结束。可能是网络或工具挂起，请重试。'
            if killed_reason.startswith('hardcap'):
                return f'{self._p.display_tool} CLI 运行超过上限 {hard_cap:g} 秒仍未结束，已停止。请把任务拆小一点再试。'
            if self._p.cli_stream_json:
                body = self._parse_claude_stream_json(stdout)
                if body:
                    return body
                if returncode != 0:
                    detail = (stderr.strip() or stdout.strip())[:500]
                    return f'{self._p.display_tool} CLI 已接入，但本次返回失败（code {returncode}）：{detail}'
                return ''
            if self._p.cli_reads_output_file and output_path.exists():
                body = output_path.read_text(encoding='utf-8', errors='replace').strip()
                if body:
                    return body
            cleaned = self._clean_cli_stdout(stdout.strip())
            if cleaned:
                return cleaned
            if returncode != 0:
                return f'{self._p.display_tool} CLI 已接入，但本次返回失败（code {returncode}）：{stderr.strip()[:500]}'
        return ''

    def _cli_path(self) -> str:
        candidates = [_facade().os.environ.get(f'{self._p.env_tool_prefix}_CLI_PATH', ''), _facade().shutil.which(self._p.cli_binary) or '', *self._p.cli_extra_candidates]
        for item in candidates:
            value = str(item or '').strip()
            if value and _facade().Path(value).is_file():
                return value
        return ''

    def _cli_workspace(self, context: dict[str, _facade().Any]) -> str:
        """解析本地 CLI 的工作目录，按执行域分流（信任墙第 3 层：工作区层）。

        - 工厂域：经 Workspace 注册表解析（含 P2 的 worktree 隔离）。
        - 产品域：**绝不采信客户提供的宿主路径**（防 path-injection / 越权读盘），一律用本档
          隔离的临时区。客户请求体里的 ``workspace_root`` 对产品域完全无效。
        """
        if self._grant.is_factory:
            try:
                reg = _facade().get_workspace_registry()
                ws = reg.get(self._grant.workspace_id)
                return str(reg.checkout(ws, task_id=str(context.get('request_id') or 'task')))
            except _facade().WorkspaceError:
                return str(_facade().get_workspace_registry().get(None).root)
        relay_repo = self._relay_real_workspace(context)
        if relay_repo:
            return relay_repo
        return self._product_ephemeral_workspace()

    def _relay_real_workspace(self, context: dict[str, _facade().Any]) -> str:
        ctx = context if isinstance(context, dict) else {}
        source = str(ctx.get('source') or '').strip().lower()
        is_relay = ctx.get('force_cli_direct') is True or source == 'mobile_relay'
        if not is_relay:
            return ''
        return _facade().resolve_verified_relay_workspace_root(ctx)

    def _factory_workspace_root(self) -> str:
        """工厂派工请求里写给远端设备的工作区根路径（不含 worktree 隔离，远端自理）。"""
        try:
            return str(_facade().get_workspace_registry().get(self._grant.workspace_id).root)
        except _facade().WorkspaceError:
            return ''

    def _product_ephemeral_workspace(self) -> str:
        """产品域 CLI 的隔离临时工作目录。

        放在系统临时区（而非 app data / 存储根），保证开发态与生产态都**在任何工程树之外**
        —— 规避 ``get_app_data_dir()`` 在源码运行时回落到 FHD 仓库根的已知陷阱。
        """
        base = _facade().Path(_facade().tempfile.gettempdir()) / 'xcmax_product_scratch' / self._p.storage_subdir
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _cli_timeout_seconds(self) -> float:
        """Backward-compat alias for _cli_idle_timeout_seconds (used by tests)."""
        return self._cli_idle_timeout_seconds()

    def _cli_idle_timeout_seconds(self) -> float:
        raw = _facade().os.environ.get(f'{self._p.env_tool_prefix}_CLI_IDLE_TIMEOUT_SEC') or _facade().os.environ.get(f'{self._p.env_tool_prefix}_CLI_TIMEOUT_SEC') or '180'
        try:
            return max(15.0, float(raw))
        except (TypeError, ValueError):
            return 180.0

    def _cli_hard_cap_seconds(self) -> float:
        raw = _facade().os.environ.get(f'{self._p.env_tool_prefix}_CLI_HARD_CAP_SEC') or '3600'
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 3600.0

    def _cli_subprocess_env(self) -> dict[str, str] | None:
        """构造 CLI 子进程环境。两件事：

        1. 差异化代理：FHD 直连自有云端 xiu-ci.com（代理会断 SSL），但 claude/codex 调
           api.anthropic.com 等需走代理（直连被 403）。仅当 XCMAX_CLI_PROXY 设了才注入。
        2. 信任墙第 2 层：**产品域**剥掉平台工厂令牌与 git 凭证，客户驱动的子进程永远拿不到
           平台机密（防被注入后偷令牌/推代码）。

        工厂域且无代理：返回 None（继承当前环境，与历史行为一致，零回归）。
        """
        proxy = str(_facade().os.environ.get('XCMAX_CLI_PROXY') or '').strip()
        product = not (self._grant.is_factory or getattr(self, '_relay_cli_trusted', False))
        if not proxy and (not product):
            return None
        env = _facade().os.environ.copy()
        if proxy:
            for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
                env[k] = proxy
        if product:
            for k in list(env.keys()):
                if k == _facade().FACTORY_TOKEN_ENV or k.startswith('XCMAX_FACTORY') or k in ('GITHUB_TOKEN', 'GH_TOKEN', 'GIT_ASKPASS', 'GIT_TOKEN'):
                    env.pop(k, None)
        return env

    def _run_cli_idle(self, cmd: list[str], cwd: str, idle_timeout: float, hard_cap: float) -> tuple[int, str, str, str]:
        """跑 cmd，只在「持续 idle_timeout 秒无输出」(卡住)或超 hard_cap 时才 kill；
        只要还在产出就不杀。返回 (returncode, stdout, stderr, killed_reason)。"""
        import threading
        proc = _facade().subprocess.Popen(cmd, cwd=cwd, text=True, bufsize=1, stdout=_facade().subprocess.PIPE, stderr=_facade().subprocess.PIPE, env=self._cli_subprocess_env())
        out_parts: list[str] = []
        err_parts: list[str] = []
        last_activity = [_facade().time.monotonic()]
        lock = threading.Lock()

        def _pump(stream, sink: list[str]) -> None:
            try:
                for line in iter(stream.readline, ''):
                    with lock:
                        sink.append(line)
                        last_activity[0] = _facade().time.monotonic()
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass
        t_out = threading.Thread(target=_pump, args=(proc.stdout, out_parts), daemon=True)
        t_err = threading.Thread(target=_pump, args=(proc.stderr, err_parts), daemon=True)
        t_out.start()
        t_err.start()
        started = _facade().time.monotonic()
        killed_reason = ''
        while True:
            try:
                proc.wait(timeout=3)
                break
            except _facade().subprocess.TimeoutExpired:
                pass
            now = _facade().time.monotonic()
            with lock:
                idle = now - last_activity[0]
            if idle_timeout > 0 and idle > idle_timeout:
                killed_reason = f'idle:{idle_timeout:g}'
            elif hard_cap > 0 and now - started > hard_cap:
                killed_reason = f'hardcap:{hard_cap:g}'
            if killed_reason:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except _facade().subprocess.TimeoutExpired:
                    pass
                break
        t_out.join(timeout=2)
        t_err.join(timeout=2)
        return (int(proc.returncode or 0), ''.join(out_parts), ''.join(err_parts), killed_reason)

    def _parse_claude_stream_json(self, out: str) -> str:
        """从 claude --output-format stream-json 的事件流里取最终回复。"""
        result = ''
        texts: list[str] = []
        for line in out.splitlines():
            s = line.strip()
            if not s.startswith('{'):
                continue
            try:
                ev = _facade().json.loads(s)
            except _facade().json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get('type') == 'result':
                r = ev.get('result')
                if isinstance(r, str) and r.strip():
                    result = r.strip()
            elif ev.get('type') == 'assistant':
                msg = ev.get('message') if isinstance(ev.get('message'), dict) else {}
                if not isinstance(msg, dict):
                    msg = {}
                for blk in msg.get('content') or []:
                    if isinstance(blk, dict) and blk.get('type') == 'text':
                        t = str(blk.get('text') or '').strip()
                        if t:
                            texts.append(t)
        return result or '\n'.join(texts).strip()

    def _cli_prompt(self, text: str) -> str:
        return f'你是 XCMAX 软件内的{self._p.employee_name}。请直接回答用户的问题。这是普通对话通道：不要执行命令，不要修改文件，不要调用工具。如果用户询问额度、账户余额、订阅或实时账户状态，而你无法从当前会话读取真实账户数据，请明确说明不能查看，不要编造数字。\n\n用户问题：{text.strip()}'

    def _is_task_intent(self, text: str, context: dict[str, _facade().Any]) -> bool:
        """是否为开发任务（需要真改代码），与 force-direct 无关，仅看 mode/关键词。"""
        raw_mode = str(context.get('mode') or '').strip().lower()
        if raw_mode in {'chat', 'qa', 'direct', f'{self._p.tool_name}_cli'}:
            return False
        if raw_mode in {'code', 'task', 'dispatch', 'dev', 'develop'}:
            return True
        normalized = _facade().re.sub('\\s+', '', text.strip().lower())
        if not normalized:
            return False
        return any((marker in normalized for marker in _facade()._TASK_MARKERS))

    def _cli_work_prompt(self, text: str, cwd: str) -> str:
        """开发任务 prompt：授权 Claude 真正读写/修改工作区文件（配合 --permission-mode acceptEdits）。"""
        return f'你是 XCMAX 软件内的{self._p.employee_name}，运行在项目工作区，拥有完整的文件读写与代码修改能力。请直接动手完成下面的开发任务：按需读取、创建、修改工作区内的文件来实现需求；不要只给建议或只解释，要真正改代码。完成后用一两句话总结你改了哪些文件、做了什么。\n\n工作区根目录：{cwd}\n\n开发任务：\n{text.strip()}'

    def _dev_loop_enabled(self) -> bool:
        raw = str(_facade().os.environ.get(f'{self._p.env_tool_prefix}_DEV_LOOP') or _facade().os.environ.get('XCMAX_CLAUDE_DEV_LOOP') or '1').strip().lower()
        return raw not in {'0', 'false', 'off', 'disabled'}

    def _git(self, cwd: str, *args: str, timeout: float=60.0) -> _facade().subprocess.CompletedProcess:
        env = _facade().os.environ.copy()
        env.setdefault('GIT_TERMINAL_PROMPT', '0')
        env.setdefault('GIT_ASKPASS', 'true')
        return _facade().subprocess.run(['git', '-C', cwd, *args], capture_output=True, text=True, timeout=timeout, env=env)

    def _is_git_repo(self, cwd: str) -> bool:
        return self._git_mgr.is_git_repo(cwd)

    @staticmethod
    def _safe_branch_name(raw: _facade().Any) -> str:
        return _facade().GitWorkspaceManager.safe_branch_name(raw)

    @classmethod
    def _safe_context_branch(cls, context: dict[str, _facade().Any] | None) -> str:
        return _facade().GitWorkspaceManager.safe_context_branch(context)

    def _resolve_branch_ref(self, base_cwd: str, branch: str) -> str:
        return self._git_mgr.resolve_branch_ref(base_cwd, branch)

    def _prepare_worktree(self, base_cwd: str, text: str, branch_hint: str='') -> tuple[str, str] | None:
        """建独立 worktree；有 branch_hint 时基于现有分支写回，否则自动新建任务分支。"""
        if not self._is_git_repo(base_cwd):
            return None
        slug = _facade().re.sub('[^a-z0-9]+', '-', text.strip().lower())[:24].strip('-') or 'task'
        uniq = f"{_facade().os.getpid()}-{int.from_bytes(_facade().os.urandom(3), 'big'):x}"
        selected_branch = self._safe_branch_name(branch_hint)
        branch = selected_branch or f'super-employee/{self._p.tool_name}/{slug}-{uniq}'
        persistent = self._relay_persistent_worktree_path()
        if persistent and (not selected_branch):
            return self._prepare_persistent_worktree(base_cwd, persistent, branch)
        wt_path = str(_facade().Path(_facade().tempfile.gettempdir()) / f'xcagi-wt-{self._p.tool_name}-{uniq}')
        try:
            if selected_branch:
                ref = self._resolve_branch_ref(base_cwd, selected_branch)
                if not ref:
                    _facade().logger.warning('选中的工作分支不存在: %s', selected_branch)
                    return None
                r = self._git(base_cwd, 'worktree', 'add', '--detach', wt_path, ref, timeout=180)
            else:
                r = self._git(base_cwd, 'worktree', 'add', '-b', branch, wt_path, 'HEAD', timeout=180)
            if r.returncode != 0:
                _facade().logger.warning('worktree add 失败: %s', (r.stderr or r.stdout)[:300])
                return None
            return (wt_path, branch)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning('worktree add 异常', exc_info=True)
            return None

    def _remove_worktree(self, base_cwd: str, wt_path: str) -> None:
        self._git_mgr.remove_worktree(base_cwd, wt_path)

    def _relay_persistent_worktree_path(self) -> str:
        return self._git_mgr.relay_persistent_worktree_path()

    def _prepare_persistent_worktree(self, base_cwd: str, wt_path: str, branch: str) -> tuple[str, str] | None:
        """复用同一个 worktree：重置为 base 干净基线 + 开新任务分支；不存在则建一次。"""
        try:
            head = self._git(base_cwd, 'rev-parse', 'HEAD', timeout=15)
            base_ref = (head.stdout or '').strip() or 'HEAD'
            wt = _facade().Path(wt_path)
            if (wt / '.git').exists():
                self._git(wt_path, 'reset', '--hard', base_ref, timeout=120)
                self._git(wt_path, 'clean', '-fdx', timeout=300)
                r = self._git(wt_path, 'checkout', '-B', branch, base_ref, timeout=120)
                if r.returncode != 0:
                    self._git(base_cwd, 'worktree', 'remove', '--force', wt_path, timeout=120)
                    _facade().shutil.rmtree(wt_path, ignore_errors=True)
            if not (wt / '.git').exists():
                wt.parent.mkdir(parents=True, exist_ok=True)
                self._git(base_cwd, 'worktree', 'prune', timeout=30)
                r = self._git(base_cwd, 'worktree', 'add', '-b', branch, wt_path, base_ref, timeout=300)
                if r.returncode != 0:
                    _facade().logger.warning('持久 worktree 创建失败: %s', (r.stderr or r.stdout)[:300])
                    return None
            return (wt_path, branch)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning('持久 worktree 准备异常', exc_info=True)
            return None

    def _verify_workspace(self, cwd: str) -> tuple[bool, str]:
        """view 阶段：验证改动可编译。优先 XCMAX_CLAUDE_VERIFY_CMD；否则对改动的 .py 做语法编译。"""
        custom = str(_facade().os.environ.get('XCMAX_CLAUDE_VERIFY_CMD') or '').strip()
        if custom:
            try:
                cap = self._cli_hard_cap_seconds()
                r = _facade().subprocess.run(custom, shell=True, cwd=cwd, capture_output=True, text=True, timeout=cap if cap and cap > 0 else 1800)
                if r.returncode == 0:
                    return (True, '自定义验证命令通过')
                return (False, (r.stderr.strip() or r.stdout.strip())[:1500])
            except _facade().RECOVERABLE_ERRORS as e:
                return (False, f'验证命令异常：{str(e)[:300]}')
        changed: list[str] = []
        try:
            st = self._git(cwd, 'status', '--porcelain', '--untracked-files=all', timeout=30)
            for ln in st.stdout.splitlines():
                if not ln.strip():
                    continue
                path = ln[3:] if len(ln) > 3 else ln.strip()
                if '->' in path:
                    path = path.split('->', 1)[1]
                path = path.strip().strip('"')
                if path:
                    changed.append(path)
        except _facade().RECOVERABLE_ERRORS:
            changed = []
        py = [f for f in changed if f.endswith('.py')]
        if py:
            import py_compile
            errs: list[str] = []
            for f in py:
                p = _facade().Path(cwd) / f
                if not p.exists():
                    continue
                try:
                    py_compile.compile(str(p), doraise=True)
                except py_compile.PyCompileError as e:
                    errs.append(str(e)[:400])
            if errs:
                return (False, 'Python 语法错误：\n' + '\n'.join(errs))
            return (True, f'已对 {len(py)} 个改动的 .py 通过语法编译')
        if not changed:
            return (True, '无文件改动')
        return (True, f'改动 {len(changed)} 个文件（非 .py，未做深度编译验证；如需构建验证可设 XCMAX_CLAUDE_VERIFY_CMD）')

    def _commit_and_push(self, cwd: str, branch: str, text: str) -> tuple[bool, str]:
        """push 阶段：add + commit + push 分支到 origin。"""
        return self._git_mgr.commit_and_push(cwd, branch, text)

    def _cli_fix_prompt(self, verify_msg: str, cwd: str) -> str:
        return f'你刚才在工作区 {cwd} 的改动未通过验证。请直接修改文件修复下面的错误，改到能通过为止，不要只解释。\n\n验证错误：\n' + verify_msg[:1500]

    def _run_dev_task_loop(self, cli_path: str, text: str, base_cwd: str, context: dict[str, _facade().Any] | None=None) -> str:
        """开发任务全闭环：隔离 worktree → coding → view(验证,失败修一次) → push → 清理。"""
        persistent = self._relay_persistent_worktree_path()
        if persistent:
            with _facade()._relay_wt_lock(persistent):
                return self._run_dev_task_loop_locked(cli_path, text, base_cwd, context)
        return self._run_dev_task_loop_locked(cli_path, text, base_cwd, context)

    def _run_dev_task_loop_locked(self, cli_path: str, text: str, base_cwd: str, context: dict[str, _facade().Any] | None=None) -> str:
        branch_hint = self._safe_context_branch(context)
        prepared = self._prepare_worktree(base_cwd, text, branch_hint)
        if not prepared:
            if branch_hint:
                return f'❌ 选中的工作分支不可用：{branch_hint}\n我没有在运行中的工程根直接写入。请刷新分支列表后重新选择，或改为自动新建分支。'
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        (wt_path, branch) = prepared
        try:
            body = self._run_cli_once(cli_path, self._cli_work_prompt(text, wt_path), wt_path)
            (ok, vmsg) = self._verify_workspace(wt_path)
            try:
                max_fix = max(1, int(_facade().os.environ.get('XCMAX_DEV_LOOP_MAX_FIX') or '3'))
            except (TypeError, ValueError):
                max_fix = 3
            attempt = 0
            while not ok and attempt < max_fix:
                attempt += 1
                self._run_cli_once(cli_path, self._cli_fix_prompt(vmsg, wt_path), wt_path)
                (ok, vmsg) = self._verify_workspace(wt_path)
            (pushed, pmsg) = self._commit_and_push(wt_path, branch, text)
            status = '✅' if ok and pushed else '⚠️' if pushed else '❌'
            tail = f"\n\n— — — 闭环结果 {status} — — —\n分支：{branch}\n验证：{('通过' if ok else '未通过')}（{vmsg[:200]}）\n推送：{pmsg[:200]}"
            base = body.strip() or f'{self._p.display_tool} 已完成开发任务。'
            return base + tail
        finally:
            self._remove_worktree(base_cwd, wt_path)
