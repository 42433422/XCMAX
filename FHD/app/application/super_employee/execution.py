"""Execution-domain isolation: trusted workspace, child environment, and tool scope."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from app.application.execution_scope import FACTORY_TOKEN_ENV
from app.application.workspaces import WorkspaceError

from .protocols import ExecutionContext, WorkspacePorts
from .profiles import SuperEmployeeToolProfile


class ExecutionPolicy:
    def __init__(
        self, profile: SuperEmployeeToolProfile, scope: ExecutionContext, ports: WorkspacePorts
    ) -> None:
        self._p, self._scope, self._ports = profile, scope, ports

    def cli_workspace(self, context: dict[str, Any]) -> str:
        """解析本地 CLI 的工作目录，按执行域分流（信任墙第 3 层：工作区层）。

        - 工厂域：经 Workspace 注册表解析（含 P2 的 worktree 隔离）。
        - 产品域：**绝不采信客户提供的宿主路径**（防 path-injection / 越权读盘），一律用本档
          隔离的临时区。客户请求体里的 ``workspace_root`` 对产品域完全无效。
        """
        if self._scope.grant.is_factory:
            try:
                reg = self._ports.registry()
                ws = reg.get(self._scope.grant.workspace_id)
                return str(reg.checkout(ws, task_id=str(context.get("request_id") or "task")))
            except WorkspaceError:
                return str(self._ports.registry().get(None).root)
        relay_repo = self._ports.relay_workspace(context)
        if relay_repo:
            return relay_repo
        return self.product_ephemeral_workspace()

    def relay_real_workspace(self, context: dict[str, Any]) -> str:
        ctx = context if isinstance(context, dict) else {}
        source = str(ctx.get("source") or "").strip().lower()
        is_relay = ctx.get("force_cli_direct") is True or source == "mobile_relay"
        if not is_relay:
            return ""
        return self._ports.verified_relay_root(ctx)

    def factory_workspace_root(self) -> str:
        """工厂派工请求里写给远端设备的工作区根路径（不含 worktree 隔离，远端自理）。"""
        try:
            return str(self._ports.registry().get(self._scope.grant.workspace_id).root)
        except WorkspaceError:
            return ""

    def product_ephemeral_workspace(self) -> str:
        """产品域 CLI 的隔离临时工作目录。

        放在系统临时区（而非 app data / 存储根），保证开发态与生产态都**在任何工程树之外**
        —— 规避 ``get_app_data_dir()`` 在源码运行时回落到 FHD 仓库根的已知陷阱。
        """
        base = Path(tempfile.gettempdir()) / "xcmax_product_scratch" / self._p.storage_subdir
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def apply_scope_to_cmd(self, cmd: list[str]) -> list[str]:
        """信任墙第 4 层（纵深防御）：产品域收紧 claude 的工具面。

        把 ``--permission-mode`` 降到 ``default`` 并显式禁用写/执行类工具，使被注入的产品域
        会话即便被诱导喊 git/shell，那些工具也压根没注册 → 硬失败而非软拒绝。工厂域不动；
        codex 命令构造默认已是 ``--sandbox workspace-write``，此处不改。
        """
        if not cmd:
            return cmd
        if (
            self._scope.grant.is_factory
            or self._scope.relay_cli_trusted
            or self._p.cli_binary != "claude"
        ):
            return cmd
        out: list[str] = []
        i = 0
        while i < len(cmd):
            if cmd[i] == "--permission-mode" and i + 1 < len(cmd):
                out += ["--permission-mode", "default"]
                i += 2
                continue
            out.append(cmd[i])
            i += 1
        if "--disallowedTools" not in out:
            prompt = out.pop()
            out += ["--disallowedTools", "Bash,Edit,Write,MultiEdit,NotebookEdit", prompt]
        return out

    def cli_subprocess_env(self) -> dict[str, str] | None:
        """构造 CLI 子进程环境。两件事：

        1. 差异化代理：FHD 直连自有云端 xiu-ci.com（代理会断 SSL），但 claude/codex 调
           api.anthropic.com 等需走代理（直连被 403）。仅当 XCMAX_CLI_PROXY 设了才注入。
        2. 信任墙第 2 层：**产品域**剥掉平台工厂令牌与 git 凭证，客户驱动的子进程永远拿不到
           平台机密（防被注入后偷令牌/推代码）。

        工厂域且无代理：返回 None（继承当前环境，与历史行为一致，零回归）。
        """
        proxy = str(os.environ.get("XCMAX_CLI_PROXY") or "").strip()
        product = not (self._scope.grant.is_factory or self._scope.relay_cli_trusted)
        if not proxy and (not product):
            return None
        env = os.environ.copy()
        if proxy:
            for k in (
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "http_proxy",
                "https_proxy",
                "all_proxy",
            ):
                env[k] = proxy
        if product:
            for k in list(env.keys()):
                if (
                    k == FACTORY_TOKEN_ENV
                    or k.startswith("XCMAX_FACTORY")
                    or k in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_ASKPASS", "GIT_TOKEN")
                ):
                    env.pop(k, None)
        return env
