# mypy: disable-error-code="attr-defined, no-any-return, valid-type"
"""Behavior mixin extracted from the public facade class."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.super_employee_service")


class __SuperEmployeeServicePart03MixinPart02Mixin:
    def _prepare_persistent_worktree(
        self, base_cwd: str, wt_path: str, branch: str
    ) -> tuple[str, str] | None:
        """复用同一个 worktree：重置为 base 干净基线 + 开新任务分支；不存在则建一次。"""
        try:
            head = self._git(base_cwd, "rev-parse", "HEAD", timeout=15)
            base_ref = (head.stdout or "").strip() or "HEAD"
            wt = _facade().Path(wt_path)
            if (wt / ".git").exists():
                self._git(wt_path, "reset", "--hard", base_ref, timeout=120)
                self._git(wt_path, "clean", "-fdx", timeout=300)
                r = self._git(wt_path, "checkout", "-B", branch, base_ref, timeout=120)
                if r.returncode != 0:
                    self._git(base_cwd, "worktree", "remove", "--force", wt_path, timeout=120)
                    _facade().shutil.rmtree(wt_path, ignore_errors=True)
            if not (wt / ".git").exists():
                wt.parent.mkdir(parents=True, exist_ok=True)
                self._git(base_cwd, "worktree", "prune", timeout=30)
                r = self._git(
                    base_cwd, "worktree", "add", "-b", branch, wt_path, base_ref, timeout=300
                )
                if r.returncode != 0:
                    _facade().logger.warning(
                        "持久 worktree 创建失败: %s", (r.stderr or r.stdout)[:300]
                    )
                    return None
            return (wt_path, branch)
        except _facade().RECOVERABLE_ERRORS:
            _facade().logger.warning("持久 worktree 准备异常", exc_info=True)
            return None

    def _verify_workspace(self, cwd: str) -> tuple[bool, str]:
        """view 阶段：验证改动可编译。优先 XCMAX_CLAUDE_VERIFY_CMD；否则对改动的 .py 做语法编译。"""
        custom = str(_facade().os.environ.get("XCMAX_CLAUDE_VERIFY_CMD") or "").strip()
        if custom:
            try:
                cap = self._cli_hard_cap_seconds()
                r = _facade().subprocess.run(
                    custom,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=cap if cap and cap > 0 else 1800,
                )
                if r.returncode == 0:
                    return (True, "自定义验证命令通过")
                return (False, (r.stderr.strip() or r.stdout.strip())[:1500])
            except _facade().RECOVERABLE_ERRORS as e:
                return (False, f"验证命令异常：{str(e)[:300]}")
        changed: list[str] = []
        try:
            st = self._git(cwd, "status", "--porcelain", "--untracked-files=all", timeout=30)
            for ln in st.stdout.splitlines():
                if not ln.strip():
                    continue
                path = ln[3:] if len(ln) > 3 else ln.strip()
                if "->" in path:
                    path = path.split("->", 1)[1]
                path = path.strip().strip('"')
                if path:
                    changed.append(path)
        except _facade().RECOVERABLE_ERRORS:
            changed = []
        py = [f for f in changed if f.endswith(".py")]
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
                return (False, "Python 语法错误：\n" + "\n".join(errs))
            return (True, f"已对 {len(py)} 个改动的 .py 通过语法编译")
        if not changed:
            return (True, "无文件改动")
        return (
            True,
            f"改动 {len(changed)} 个文件（非 .py，未做深度编译验证；如需构建验证可设 XCMAX_CLAUDE_VERIFY_CMD）",
        )

    def _commit_and_push(self, cwd: str, branch: str, text: str) -> tuple[bool, str]:
        """push 阶段：add + commit + push 分支到 origin。"""
        return self._git_mgr.commit_and_push(cwd, branch, text)

    def _cli_fix_prompt(self, verify_msg: str, cwd: str) -> str:
        return (
            f"你刚才在工作区 {cwd} 的改动未通过验证。请直接修改文件修复下面的错误，改到能通过为止，不要只解释。\n\n验证错误：\n"
            + verify_msg[:1500]
        )

    def _run_dev_task_loop(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, _facade().Any] | None = None,
    ) -> str:
        """开发任务全闭环：隔离 worktree → coding → view(验证,失败修一次) → push → 清理。"""
        persistent = self._relay_persistent_worktree_path()
        if persistent:
            with _facade()._relay_wt_lock(persistent):
                return self._run_dev_task_loop_locked(cli_path, text, base_cwd, context)
        return self._run_dev_task_loop_locked(cli_path, text, base_cwd, context)

    def _run_dev_task_loop_locked(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, _facade().Any] | None = None,
    ) -> str:
        branch_hint = self._safe_context_branch(context)
        prepared = self._prepare_worktree(base_cwd, text, branch_hint)
        if not prepared:
            if branch_hint:
                return f"❌ 选中的工作分支不可用：{branch_hint}\n我没有在运行中的工程根直接写入。请刷新分支列表后重新选择，或改为自动新建分支。"
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        wt_path, branch = prepared
        try:
            body = self._run_cli_once(cli_path, self._cli_work_prompt(text, wt_path), wt_path)
            ok, vmsg = self._verify_workspace(wt_path)
            try:
                max_fix = max(1, int(_facade().os.environ.get("XCMAX_DEV_LOOP_MAX_FIX") or "3"))
            except (TypeError, ValueError):
                max_fix = 3
            attempt = 0
            while not ok and attempt < max_fix:
                attempt += 1
                self._run_cli_once(cli_path, self._cli_fix_prompt(vmsg, wt_path), wt_path)
                ok, vmsg = self._verify_workspace(wt_path)
            pushed, pmsg = self._commit_and_push(wt_path, branch, text)
            status = "✅" if ok and pushed else "⚠️" if pushed else "❌"
            tail = f"\n\n— — — 闭环结果 {status} — — —\n分支：{branch}\n验证：{('通过' if ok else '未通过')}（{vmsg[:200]}）\n推送：{pmsg[:200]}"
            base = body.strip() or f"{self._p.display_tool} 已完成开发任务。"
            return base + tail
        finally:
            self._remove_worktree(base_cwd, wt_path)
