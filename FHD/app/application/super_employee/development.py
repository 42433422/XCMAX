"""Coordinate isolated worktree preparation, coding, verification, publication, and cleanup."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.domain.app_pure.git_workspace_manager import GitWorkspaceManager
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .cli import CliExecutionError
from .common import _relay_wt_lock
from .profiles import SuperEmployeeToolProfile
from .protocols import DevelopmentPorts, WorktreePorts

logger = logging.getLogger(__name__)


class DevelopmentWorkflow:
    def __init__(
        self, profile: SuperEmployeeToolProfile, worktrees: WorktreePorts, coding: DevelopmentPorts
    ) -> None:
        self._p, self._worktrees, self._coding = profile, worktrees, coding

    def prepare_worktree(
        self, base_cwd: str, text: str, branch_hint: str = ""
    ) -> tuple[str, str] | None:
        """建独立 worktree；有 branch_hint 时基于现有分支写回，否则自动新建任务分支。"""
        if not self._worktrees.is_git_repo(base_cwd):
            return None
        slug = re.sub("[^a-z0-9]+", "-", text.strip().lower())[:24].strip("-") or "task"
        uniq = f"{os.getpid()}-{int.from_bytes(os.urandom(3), 'big'):x}"
        selected_branch = GitWorkspaceManager.safe_branch_name(branch_hint)
        branch = selected_branch or f"super-employee/{self._p.tool_name}/{slug}-{uniq}"
        persistent = self._worktrees.persistent_path()
        if persistent and (not selected_branch):
            return self.prepare_persistent_worktree(base_cwd, persistent, branch)
        wt_path = str(Path(tempfile.gettempdir()) / f"xcagi-wt-{self._p.tool_name}-{uniq}")
        try:
            if selected_branch:
                ref = self._worktrees.resolve_branch(base_cwd, selected_branch)
                if not ref:
                    logger.warning("选中的工作分支不存在: %s", selected_branch)
                    return None
                r = self._worktrees.git(
                    base_cwd, "worktree", "add", "--detach", wt_path, ref, timeout=180
                )
            else:
                r = self._worktrees.git(
                    base_cwd, "worktree", "add", "-b", branch, wt_path, "HEAD", timeout=180
                )
            if r.returncode != 0:
                logger.warning("worktree add 失败: %s", (r.stderr or r.stdout)[:300])
                return None
            return (wt_path, branch)
        except RECOVERABLE_ERRORS:
            logger.warning("worktree add 异常", exc_info=True)
            return None

    def prepare_persistent_worktree(
        self, base_cwd: str, wt_path: str, branch: str
    ) -> tuple[str, str] | None:
        """仅复用已确认干净的 worktree，保留尚待核对的改动及原分支。"""
        try:
            head = self._worktrees.git(base_cwd, "rev-parse", "HEAD", timeout=15)
            base_ref = (head.stdout or "").strip() or "HEAD"
            wt = Path(wt_path)
            if (wt / ".git").exists():
                state = self._worktrees.git(
                    wt_path, "status", "--porcelain", "--untracked-files=all", timeout=30
                )
                if state.returncode != 0 or state.stdout.strip():
                    failure = CliExecutionError(
                        self._p.display_tool,
                        "workspace_unavailable" if state.returncode != 0 else "workspace_dirty",
                        stage="workspace",
                        started=False,
                        stderr=state.stderr or state.stdout or "无法确认 worktree 干净状态",
                    )
                    self._preserve_workspace(failure, wt_path, "")
                    failure.receipt["requested_branch"] = branch
                    raise failure
                r = self._worktrees.git(wt_path, "checkout", "-B", branch, base_ref, timeout=120)
                if r.returncode != 0:
                    return None
            if not (wt / ".git").exists():
                wt.parent.mkdir(parents=True, exist_ok=True)
                self._worktrees.git(base_cwd, "worktree", "prune", timeout=30)
                r = self._worktrees.git(
                    base_cwd, "worktree", "add", "-b", branch, wt_path, base_ref, timeout=300
                )
                if r.returncode != 0:
                    logger.warning("持久 worktree 创建失败: %s", (r.stderr or r.stdout)[:300])
                    return None
            return (wt_path, branch)
        except CliExecutionError:
            raise
        except RECOVERABLE_ERRORS:
            logger.warning("持久 worktree 准备异常", exc_info=True)
            return None

    def verify_workspace(self, cwd: str) -> tuple[bool, str]:
        """view 阶段：验证改动可编译。优先 XCMAX_CLAUDE_VERIFY_CMD；否则对改动的 .py 做语法编译。"""
        custom = str(os.environ.get("XCMAX_CLAUDE_VERIFY_CMD") or "").strip()
        if custom:
            try:
                command = shlex.split(custom)
                if not command:
                    return (False, "自定义验证命令为空")
                cap = self._coding.hard_cap()
                r = subprocess.run(
                    command,
                    shell=False,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=cap if cap and cap > 0 else 1800,
                )
                if r.returncode == 0:
                    return (True, "自定义验证命令通过")
                return (False, (r.stderr.strip() or r.stdout.strip())[:1500])
            except RECOVERABLE_ERRORS as e:
                return (False, f"验证命令异常：{str(e)[:300]}")
        changed: list[str] = []
        try:
            st = self._worktrees.git(
                cwd, "status", "--porcelain", "--untracked-files=all", timeout=30
            )
            if st.returncode != 0:
                return False, "无法读取待验证改动：" + (st.stderr or st.stdout)[:300]
            for ln in st.stdout.splitlines():
                if not ln.strip():
                    continue
                path = ln[3:] if len(ln) > 3 else ln.strip()
                if "->" in path:
                    path = path.split("->", 1)[1]
                path = path.strip().strip('"')
                if path:
                    changed.append(path)
        except RECOVERABLE_ERRORS as exc:
            return False, f"无法读取待验证改动：{str(exc)[:300]}"
        py = [f for f in changed if f.endswith(".py")]
        if py:
            import py_compile

            errs: list[str] = []
            for f in py:
                p = Path(cwd) / f
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

    def run_dev_task_loop(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """开发任务全闭环：隔离 worktree → coding → view(验证,失败修一次) → push → 清理。"""
        persistent = self._worktrees.persistent_path()
        if persistent:
            with _relay_wt_lock(persistent):
                return self.run_dev_task_loop_locked(cli_path, text, base_cwd, context)
        return self.run_dev_task_loop_locked(cli_path, text, base_cwd, context)

    def run_dev_task_loop_locked(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        branch_hint = GitWorkspaceManager.safe_context_branch(context)
        prepared = self._coding.prepare(base_cwd, text, branch_hint)
        if not prepared:
            base_path = Path(base_cwd).resolve()
            git_marker = any((path / ".git").exists() for path in (base_path, *base_path.parents))
            if branch_hint or git_marker or self._worktrees.is_git_repo(base_cwd):
                failure = CliExecutionError(
                    self._p.display_tool,
                    "workspace_unavailable",
                    stage="workspace",
                    started=False,
                )
                failure.receipt.update({"workspace": base_cwd, "branch": branch_hint})
                raise failure
            return self._coding.run_once(
                cli_path, self._coding.work_prompt(text, base_cwd), base_cwd
            )
        wt_path, branch = prepared
        body, stage = "", "cli"
        execution_started = False
        completed = False
        try:
            body = self._coding.run_once(cli_path, self._coding.work_prompt(text, wt_path), wt_path)
            execution_started = True
            stage = "verification"
            ok, vmsg = self._coding.verify(wt_path)
            try:
                max_fix = max(1, int(os.environ.get("XCMAX_DEV_LOOP_MAX_FIX") or "3"))
            except (TypeError, ValueError):
                max_fix = 3
            attempt = 0
            while not ok and attempt < max_fix:
                attempt += 1
                stage = "cli"
                body = self._coding.run_once(
                    cli_path, self._coding.fix_prompt(vmsg, wt_path), wt_path
                )
                stage = "verification"
                ok, vmsg = self._coding.verify(wt_path)
            if not ok:
                raise CliExecutionError(
                    self._p.display_tool,
                    "verification_failed",
                    stage=stage,
                    partial_text=body,
                    stderr=vmsg,
                )
            stage = "publication"
            pushed, pmsg = self._coding.commit(wt_path, branch, text)
            if not pushed:
                raise CliExecutionError(
                    self._p.display_tool,
                    "publication_failed",
                    stage=stage,
                    partial_text=body,
                    stderr=pmsg,
                )
            completed = True
            tail = f"\n\n— — — 闭环结果 ✅ — — —\n分支：{branch}\n验证：通过（{vmsg[:200]}）\n推送：{pmsg[:200]}"
            base = body.strip() or f"{self._p.display_tool} 已完成开发任务。"
            return base + tail
        except CliExecutionError as cli_failure:
            if execution_started:
                cli_failure.receipt.update(
                    {
                        "execution_started": True,
                        "execution_state": "failed",
                        "outcome": "unknown",
                        "partial_text": cli_failure.receipt.get("partial_text") or body,
                    }
                )
            self._preserve_workspace(cli_failure, wt_path, branch)
            raise
        except RECOVERABLE_ERRORS as exc:
            failure = CliExecutionError(
                self._p.display_tool,
                f"{stage}_failed",
                stage=stage,
                partial_text=body,
                stderr=str(exc),
            )
            self._preserve_workspace(failure, wt_path, branch)
            raise failure from exc
        finally:
            if completed:
                self._coding.remove(base_cwd, wt_path)

    @staticmethod
    def _preserve_workspace(failure: CliExecutionError, wt_path: str, branch: str) -> None:
        failure.receipt.update(
            {
                "workspace": wt_path,
                "branch": branch,
                "workspace_preserved": True,
                "reconciliation_required": True,
            }
        )
