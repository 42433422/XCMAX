"""Git worktree / dev-loop mixin."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.application.git_workspace_manager import GitWorkspaceManager

from .profiles import (  # noqa: F401
    _PARA_TOKEN_CACHE,
    _PARA_TOKEN_TTL,
    _RELAY_WT_LOCKS,
    _RELAY_WT_LOCKS_GUARD,
    _SUBTASK_LABELS,
    _TASK_MARKERS,
    CLAUDE_PROFILE,
    CODEX_PROFILE,
    CURSOR_PROFILE,
    DEFAULT_PARA_API_URL,
    DISPATCHER_MESSAGE_KIND,
    PARA_TERMINAL_TASK_STATUSES,
    TASK_ID_RE,
    TRAE_PROFILE,
    SuperEmployeeToolProfile,
    _chunk_text,
    _claude_cli_command,
    _codex_cli_command,
    _coerce_list,
    _cursor_cli_command,
    _facade_attr,
    _relay_wt_lock,
    _safe_json_line,
    _trae_cli_command,
    _utc_now,
)

logger = logging.getLogger(__name__)


class SuperEmployeeDevLoopMixin:
    def _dev_loop_enabled(self) -> bool:
        raw = (
            str(
                os.environ.get(f"{self._p.env_tool_prefix}_DEV_LOOP")
                or os.environ.get("XCMAX_CLAUDE_DEV_LOOP")
                or "1"
            )
            .strip()
            .lower()
        )
        return raw not in {"0", "false", "off", "disabled"}

    def _git(self, cwd: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_ASKPASS", "true")
        return _facade_attr("subprocess", subprocess).run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    def _is_git_repo(self, cwd: str) -> bool:
        return self._git_mgr.is_git_repo(cwd)

    @staticmethod
    def _safe_branch_name(raw: Any) -> str:
        return GitWorkspaceManager.safe_branch_name(raw)

    @classmethod
    def _safe_context_branch(cls, context: dict[str, Any] | None) -> str:
        return GitWorkspaceManager.safe_context_branch(context)

    def _resolve_branch_ref(self, base_cwd: str, branch: str) -> str:
        return self._git_mgr.resolve_branch_ref(base_cwd, branch)

    def _prepare_worktree(
        self,
        base_cwd: str,
        text: str,
        branch_hint: str = "",
    ) -> tuple[str, str] | None:
        """建独立 worktree；有 branch_hint 时基于现有分支写回，否则自动新建任务分支。"""
        if not self._is_git_repo(base_cwd):
            return None
        slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower())[:24].strip("-") or "task"
        uniq = f"{os.getpid()}-{int.from_bytes(os.urandom(3), 'big'):x}"
        selected_branch = self._safe_branch_name(branch_hint)
        branch = selected_branch or f"super-employee/{self._p.tool_name}/{slug}-{uniq}"
        # 持久复用：中继真仓库模式下，自动新建分支的工单复用同一个 worktree（620M 只建一次），
        # 每任务仍开新分支真推送。选定既有分支的写回任务走每任务新建（语义更清晰）。
        persistent = self._relay_persistent_worktree_path()
        if persistent and not selected_branch:
            return self._prepare_persistent_worktree(base_cwd, persistent, branch)
        wt_path = str(Path(tempfile.gettempdir()) / f"xcagi-wt-{self._p.tool_name}-{uniq}")
        try:
            if selected_branch:
                ref = self._resolve_branch_ref(base_cwd, selected_branch)
                if not ref:
                    logger.warning("选中的工作分支不存在: %s", selected_branch)
                    return None
                r = self._git(base_cwd, "worktree", "add", "--detach", wt_path, ref, timeout=180)
            else:
                r = self._git(
                    base_cwd,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    wt_path,
                    "HEAD",
                    timeout=180,
                )
            if r.returncode != 0:
                logger.warning("worktree add 失败: %s", (r.stderr or r.stdout)[:300])
                return None
            return wt_path, branch
        except Exception:  # noqa: BLE001
            logger.warning("worktree add 异常", exc_info=True)
            return None

    def _remove_worktree(self, base_cwd: str, wt_path: str) -> None:
        self._git_mgr.remove_worktree(base_cwd, wt_path)

    def _relay_persistent_worktree_path(self) -> str:
        return self._git_mgr.relay_persistent_worktree_path()

    def _prepare_persistent_worktree(
        self, base_cwd: str, wt_path: str, branch: str
    ) -> tuple[str, str] | None:
        """复用同一个 worktree：重置为 base 干净基线 + 开新任务分支；不存在则建一次。"""
        try:
            head = self._git(base_cwd, "rev-parse", "HEAD", timeout=15)
            base_ref = (head.stdout or "").strip() or "HEAD"
            wt = Path(wt_path)
            if (wt / ".git").exists():
                # 复用：丢弃上个任务的改动、清干净未跟踪、从 base 重开任务分支。
                self._git(wt_path, "reset", "--hard", base_ref, timeout=120)
                self._git(wt_path, "clean", "-fdx", timeout=300)
                r = self._git(wt_path, "checkout", "-B", branch, base_ref, timeout=120)
                if r.returncode != 0:
                    # worktree 损坏 → 拆掉重建。
                    self._git(base_cwd, "worktree", "remove", "--force", wt_path, timeout=120)
                    shutil.rmtree(wt_path, ignore_errors=True)
            if not (wt / ".git").exists():
                wt.parent.mkdir(parents=True, exist_ok=True)
                self._git(base_cwd, "worktree", "prune", timeout=30)
                r = self._git(
                    base_cwd, "worktree", "add", "-b", branch, wt_path, base_ref, timeout=300
                )
                if r.returncode != 0:
                    logger.warning("持久 worktree 创建失败: %s", (r.stderr or r.stdout)[:300])
                    return None
            return wt_path, branch
        except Exception:  # noqa: BLE001
            logger.warning("持久 worktree 准备异常", exc_info=True)
            return None

    def _verify_workspace(self, cwd: str) -> tuple[bool, str]:
        """view 阶段：验证改动可编译。优先 XCMAX_CLAUDE_VERIFY_CMD；否则对改动的 .py 做语法编译。"""
        custom = str(os.environ.get("XCMAX_CLAUDE_VERIFY_CMD") or "").strip()
        if custom:
            try:
                cap = self._cli_hard_cap_seconds()
                r = _facade_attr("subprocess", subprocess).run(
                    custom,
                    shell=True,  # nosec B602 – operator-supplied env var, may use shell syntax
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=(cap if cap and cap > 0 else 1800),
                )
                if r.returncode == 0:
                    return True, "自定义验证命令通过"
                return False, (r.stderr.strip() or r.stdout.strip())[:1500]
            except Exception as e:  # noqa: BLE001
                return False, f"验证命令异常：{str(e)[:300]}"
        # 用 status --porcelain 枚举改动：必须含"未跟踪新文件"（claude 常新建文件，
        # 如 PressEffect.kt 就是新建；git diff HEAD 抓不到未跟踪文件会漏验证）。
        changed: list[str] = []
        try:
            st = self._git(cwd, "status", "--porcelain", "--untracked-files=all", timeout=30)
            for ln in st.stdout.splitlines():
                if not ln.strip():
                    continue
                path = ln[3:] if len(ln) > 3 else ln.strip()
                if "->" in path:  # 重命名 old -> new
                    path = path.split("->", 1)[1]
                path = path.strip().strip('"')
                if path:
                    changed.append(path)
        except Exception:  # noqa: BLE001
            changed = []
        py = [f for f in changed if f.endswith(".py")]
        if py:
            import py_compile

            errs: list[str] = []
            cwd_root = Path(cwd).resolve()
            for f in py:
                rel = Path(str(f).replace("\\", "/"))
                # 拒绝绝对路径与 .. 穿越，避免用户可控路径拼进 cwd（CodeQL path-injection）
                if rel.is_absolute() or ".." in rel.parts:
                    continue
                p = (cwd_root / rel).resolve()
                try:
                    p.relative_to(cwd_root)
                except ValueError:
                    continue
                if not p.exists():
                    continue
                try:
                    py_compile.compile(str(p), doraise=True)
                except py_compile.PyCompileError as e:
                    errs.append(str(e)[:400])
            if errs:
                return False, "Python 语法错误：\n" + "\n".join(errs)
            return True, f"已对 {len(py)} 个改动的 .py 通过语法编译"
        if not changed:
            return True, "无文件改动"
        return True, (
            f"改动 {len(changed)} 个文件（非 .py，未做深度编译验证；"
            "如需构建验证可设 XCMAX_CLAUDE_VERIFY_CMD）"
        )

    def _commit_and_push(self, cwd: str, branch: str, text: str) -> tuple[bool, str]:
        """push 阶段：add + commit + push 分支到 origin。"""
        return self._git_mgr.commit_and_push(cwd, branch, text)

    def _cli_fix_prompt(self, verify_msg: str, cwd: str) -> str:
        return (
            f"你刚才在工作区 {cwd} 的改动未通过验证。请直接修改文件修复下面的错误，"
            "改到能通过为止，不要只解释。\n\n验证错误：\n" + verify_msg[:1500]
        )

    def _run_dev_task_loop(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """开发任务全闭环：隔离 worktree → coding → view(验证,失败修一次) → push → 清理。"""
        # 持久复用模式下，同一 worktree 必须串行使用（并发任务排队），避免 git 状态相互踩踏。
        persistent = self._relay_persistent_worktree_path()
        if persistent:
            with _relay_wt_lock(persistent):
                return self._run_dev_task_loop_locked(cli_path, text, base_cwd, context)
        return self._run_dev_task_loop_locked(cli_path, text, base_cwd, context)

    def _run_dev_task_loop_locked(
        self,
        cli_path: str,
        text: str,
        base_cwd: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        branch_hint = self._safe_context_branch(context)
        prepared = self._prepare_worktree(base_cwd, text, branch_hint)
        if not prepared:
            if branch_hint:
                return (
                    f"❌ 选中的工作分支不可用：{branch_hint}\n"
                    "我没有在运行中的工程根直接写入。请刷新分支列表后重新选择，或改为自动新建分支。"
                )
            # 无法隔离（非 git 仓库 / worktree 冲突）→ 退回只改不推，保证仍可用。
            return self._run_cli_once(cli_path, self._cli_work_prompt(text, base_cwd), base_cwd)
        wt_path, branch = prepared
        try:
            body = self._run_cli_once(cli_path, self._cli_work_prompt(text, wt_path), wt_path)
            ok, vmsg = self._verify_workspace(wt_path)
            # 迭代修复：验证未过则让 CLI 再修，最多 N 轮（env 可调），而非『只修一次』即放弃，
            # 显著提升 dev-loop 通过率，少落 blocked。
            try:
                max_fix = max(1, int(os.environ.get("XCMAX_DEV_LOOP_MAX_FIX") or "3"))
            except (TypeError, ValueError):
                max_fix = 3
            attempt = 0
            while not ok and attempt < max_fix:
                attempt += 1
                self._run_cli_once(cli_path, self._cli_fix_prompt(vmsg, wt_path), wt_path)
                ok, vmsg = self._verify_workspace(wt_path)
            pushed, pmsg = self._commit_and_push(wt_path, branch, text)
            status = "✅" if (ok and pushed) else ("⚠️" if pushed else "❌")
            tail = (
                f"\n\n— — — 闭环结果 {status} — — —"
                f"\n分支：{branch}"
                f"\n验证：{'通过' if ok else '未通过'}（{vmsg[:200]}）"
                f"\n推送：{pmsg[:200]}"
            )
            base = body.strip() or f"{self._p.display_tool} 已完成开发任务。"
            return base + tail
        finally:
            self._remove_worktree(base_cwd, wt_path)
