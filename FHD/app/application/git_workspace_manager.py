"""Git workspace management for the super-employee service.

Extracted from ``super_employee_service.py`` to isolate git worktree lifecycle
(add / reset / commit / push / remove) and branch-name hygiene behind a single
responsibility. The service delegates here so git concerns can evolve and be
tested independently of dispatch / CLI / message-storage concerns.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import get_desktop_state_dir

logger = logging.getLogger(__name__)


class GitWorkspaceManager:
    """Manage git worktrees and branch hygiene for super-employee dev tasks.

    The actual ``git`` invocation is delegated to a caller-supplied
    ``git_call`` so the host service can keep its own ``_git`` method as the
    single mockable seam (tests monkeypatch ``svc._git``). When ``git_call``
    is None a default implementation is used.
    """

    def __init__(
        self,
        tool_name: str,
        employee_name: str,
        git_call: Callable[..., subprocess.CompletedProcess] | None = None,
    ) -> None:
        self._tool_name = tool_name
        self._employee_name = employee_name
        self._git_call = git_call

    def git(self, cwd: str, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
        if self._git_call is not None:
            return self._git_call(cwd, *args, timeout=timeout)
        env = os.environ.copy()
        env.setdefault("GIT_TERMINAL_PROMPT", "0")
        env.setdefault("GIT_ASKPASS", "true")
        return subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )

    def is_git_repo(self, cwd: str) -> bool:
        try:
            r = self.git(cwd, "rev-parse", "--is-inside-work-tree", timeout=15)
            return r.returncode == 0 and r.stdout.strip() == "true"
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            return False

    @staticmethod
    def safe_branch_name(raw: Any) -> str:
        branch = str(raw or "").strip()
        if branch.startswith("refs/heads/"):
            branch = branch.removeprefix("refs/heads/")
        if branch.startswith("refs/remotes/"):
            branch = branch.removeprefix("refs/remotes/")
        if branch.startswith("origin/"):
            branch = branch.removeprefix("origin/")
        branch = re.sub(r"[^A-Za-z0-9._/-]+", "-", branch)[:180].strip("/.")
        if not branch or branch in {"HEAD", "origin/HEAD", ".", ".."}:
            return ""
        if ".." in branch or "//" in branch or "@{" in branch or branch.endswith(".lock"):
            return ""
        return branch

    @classmethod
    def safe_context_branch(cls, context: dict[str, Any] | None) -> str:
        data = context if isinstance(context, dict) else {}
        return cls.safe_branch_name(
            data.get("branch_context") or data.get("branch") or data.get("selected_branch")
        )

    def resolve_branch_ref(self, base_cwd: str, branch: str) -> str:
        branch = self.safe_branch_name(branch)
        if not branch:
            return ""
        try:
            self.git(
                base_cwd,
                "fetch",
                "origin",
                f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                timeout=120,
            )
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            pass
        for ref in (f"origin/{branch}", branch):
            try:
                r = self.git(base_cwd, "rev-parse", "--verify", "--quiet", ref, timeout=15)
                if r.returncode == 0:
                    return ref
            except RECOVERABLE_ERRORS:  # noqa: BLE001
                continue
        return ""

    def relay_persistent_worktree_path(self) -> str:
        """持久复用 worktree 的稳定路径；空串=不启用（走每任务新建+用完即删）。

        仅在操作者配了 XCMAX_RELAY_WORKSPACE_ROOT（真仓库交付）且未显式关闭时启用。落在
        稳定桌面态目录（非 $TMPDIR，避免被 GC 当瞬态清掉；非源码树，规避 get_app_data_dir 回落陷阱）。
        """
        if not (
            os.environ.get("XCMAX_RELAY_WORKSPACE_ROOT")
            or os.environ.get("DEVFLEET_WORKSPACE_ROOT")
        ):
            return ""
        if str(os.environ.get("XCMAX_RELAY_PERSISTENT_WORKTREE") or "1").strip().lower() in {
            "0",
            "false",
            "off",
            "no",
        }:
            return ""
        return str(Path(get_desktop_state_dir()) / "relay_worktrees" / self._tool_name)

    def remove_worktree(self, base_cwd: str, wt_path: str) -> None:
        persistent = self.relay_persistent_worktree_path()
        if persistent and os.path.realpath(wt_path) == os.path.realpath(persistent):
            return  # 持久复用 worktree：保留以供下个任务复用，不删（下次 prepare 时重置为干净基线）。
        try:
            self.git(base_cwd, "worktree", "remove", "--force", wt_path, timeout=60)
        except RECOVERABLE_ERRORS:  # noqa: BLE001
            logger.warning("worktree remove 失败 %s", wt_path, exc_info=True)

    def commit_and_push(self, cwd: str, branch: str, text: str) -> tuple[bool, str]:
        """push 阶段：add + commit + push 分支到 origin。"""
        try:
            self.git(cwd, "add", "-A", timeout=120)
            st = self.git(cwd, "status", "--porcelain", timeout=30)
            if not st.stdout.strip():
                return False, "无改动可提交"
            title = (text.strip().splitlines() or ["开发任务"])[0][:60]
            msg = f"{self._employee_name}: {title}\n\n手机超级员工自动提交（coding→view→push 闭环）"
            c = self.git(cwd, "commit", "-m", msg, timeout=60)
            if c.returncode != 0:
                return False, "提交失败：" + (c.stderr.strip() or c.stdout.strip())[:300]
            p = self.git(cwd, "push", "-u", "origin", f"HEAD:{branch}", timeout=240)
            if p.returncode != 0:
                return False, "已本地提交，但 push 失败：" + (p.stderr.strip() or p.stdout.strip())[
                    :300
                ]
            return True, f"已 push 到 origin/{branch}"
        except RECOVERABLE_ERRORS as e:  # noqa: BLE001
            return False, f"git 异常：{str(e)[:300]}"


__all__ = ["GitWorkspaceManager"]
