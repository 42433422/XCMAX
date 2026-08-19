"""受控运维动作：shell_exec / ssh_exec，白名单命令 + 审计日志。"""

from __future__ import annotations

import json
import logging
import os
import shlex
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from modstore_server.integrations.ops_action_specs import (
    APPROVAL_DISPATCHER_EMPLOYEE_ID as APPROVAL_DISPATCHER_EMPLOYEE_ID,
    OPS_COMMAND_REGISTRY as OPS_COMMAND_REGISTRY,
    OPS_EMPLOYEE_IDS as OPS_EMPLOYEE_IDS,
    CommandSpec as CommandSpec,
)
from modstore_server.models import OpsActionAuditLog, get_session_factory

logger = logging.getLogger(__name__)


def _path_hits_user_data(norm: str) -> bool:
    low = norm.replace("\\", "/").lower()
    if "modstore.db" in low:
        return True
    # 路径段或子串：…/catalog_data、…/library、var/runtime（与 sync tar exclude 对齐）
    if "/catalog_data" in low or low.rstrip("/").endswith("/catalog_data"):
        return True
    if "/library/" in low or low.rstrip("/").endswith("/library"):
        return True
    if "/var/runtime" in low or "/var/vibe_coding" in low:
        return True
    return False


def _assert_shell_paths_safe(command_id: str, args: Mapping[str, Any], cwd: Optional[str]) -> None:
    """禁止 shell 命令触及用户数据目录（与 sync tar exclude 对齐）。"""
    blobs: List[str] = []
    if cwd:
        blobs.append(cwd)
    for k, v in args.items():
        if isinstance(v, str) and k not in ("message",):  # commit message free text
            blobs.append(v)
    for b in blobs:
        if _path_hits_user_data(b):
            raise ValueError(f"refused path (user-data guard): {b[:200]!r}")


_BRANCH_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/")


def _sanitize_branch(name: str) -> str:
    s = (name or "").strip()
    if not s or len(s) > 120:
        raise ValueError("invalid branch")
    if not all(c in _BRANCH_SAFE for c in s):
        raise ValueError("invalid branch characters")
    if ".." in s or s.startswith("/") or s.startswith("-"):
        raise ValueError("invalid branch")
    return s


EVENT_TYPES = frozenset(
    {
        "on_error",
        "on_quality_fail",
        "on_coverage_miss",
        "doc_change",
        "employee.task.done",
        "employee.task.assigned",
        "employee.task.failed",
        "employee.suggestion.created",
        # intake / router / deploy 主流程（yuangon process loop）
        "ops.intake.user_request",
        "ops.intake.email",
        "ops.intake.customer_ticket",
        "ops.intake.candidate_pack",
        "ops.intake.task.queued",
        "ops.change_request.submitted",
        "ops.change_request.approved",
        "ops.change_request.escalated",
        "ops.yuangon.resync.done",
        "yuangon.def.changed",
        "change_request.created",
        "change_request.applied",
        "change_request.ci_complete",
        "change_request.verify_complete",
        "change_request.result",  # 审批结果反馈（applied / rejected / failed）
        "consistency_check.completed",  # 文档一致性检测完成
        # 2026-05 扩展：覆盖 git/CI/支付/客诉/安全/日志/调度等场景
        "git.push",  # 远端推送（webhook 或本地 post-push 钩子）
        "git.pr_opened",
        "git.pr_merged",
        "ci.failed",  # CI 流水线失败（GitHub Actions / 本地 pytest）
        "ci.passed",
        "payment.anomaly",  # 支付/对账异常
        "customer.complaint",  # 客服工单升级
        "security.alert",  # 安全密钥/证书异常
        "log.anomaly",  # 日志异常聚类
        "schedule.tick",  # 调度器心跳（用于全员唤醒）
        "incident.unknown",  # incident_bus 收到未注册类型时的兜底事件
        "employee.brief_todo.created",
        "employee.brief_todo.dispatched",
        "employee.suggestion.approved",
        "employee.suggestion.rejected",
        "employee.suggestion.dispatched",
        "employee.collab.thread_created",
        "employee.collab.message_created",
        "employee.evolution.suggested",
        "employee.execution.recovery",
        # 容灾备份事件链（BK→R / DRPROBE / 按需快照）
        "backup.completed",
        "backup.failed",
        "backup.ondemand_completed",
        "backup.ondemand_failed",
        "backup.dr_guard.cleared",
        "backup.dr_guard.escalated",
    }
)


def repo_root() -> Path:
    """仓库根（含 yuangon、nginx 配置、MODstore_deploy）。"""
    git_env = os.environ.get("MODSTORE_GIT_REPO_ROOT", "").strip()
    if git_env:
        return Path(git_env).resolve()
    env = os.environ.get("MODSTORE_REPO_ROOT", "").strip()
    if env:
        return Path(env).resolve()
    p = Path(__file__).resolve()
    # 默认：…/MODstore_deploy/modstore_server/integrations/this_file.py → parents[3]
    for depth in (3, 2, 4):
        if depth <= len(p.parents):
            cand = p.parents[depth - 1]
            if (cand / "MODstore_deploy" / "modstore_server").is_dir():
                return cand
    return p.parents[2]


def _secrets_dir() -> Path:
    return repo_root() / "_local_secrets"


def _ssh_keys_dir() -> Path:
    return _secrets_dir() / "ssh_keys"


def _resolve_path_arg(val: str) -> str:
    """相对路径相对于 repo_root。"""
    p = Path(val)
    if p.is_absolute():
        return str(p.resolve())
    return str((repo_root() / p).resolve())


def _render_argv(template: Sequence[str], args: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for part in template:
        if part.startswith("${") and part.endswith("}"):
            key = part[2:-1]
            if key not in args:
                raise ValueError(f"missing arg: {key}")
            raw = str(args[key])
            if "\n" in raw or "\r" in raw:
                raise ValueError(f"invalid arg {key}: newline")
            if len(raw) > 8192:
                raise ValueError(f"arg {key} too long")
            # 路径类占位符
            if key in (
                "path",
                "req_file",
                "dist_dir",
                "root",
                "rcfile",
                "ps1_path",
                "cwd",
            ):
                out.append(_resolve_path_arg(raw))
            else:
                out.append(raw)
        else:
            out.append(part)
    return out


def _truncate(s: str, max_bytes: int) -> str:
    b = s.encode("utf-8", errors="replace")
    if len(b) <= max_bytes:
        return s
    return b[:max_bytes].decode("utf-8", errors="replace") + "…[truncated]"


def _audit_env() -> Dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if k in ("PATH", "PYTHONPATH", "TEMP", "TMP", "SystemRoot")
    }


def _write_audit(
    *,
    user_id: int,
    employee_id: str,
    handler: str,
    command_id: str,
    args_json: str,
    host_id: str,
    exit_code: Optional[int],
    stdout_excerpt: str,
    stderr_excerpt: str,
    duration_ms: float,
    approval_required: bool,
    dry_run: bool,
    error: str,
) -> Optional[int]:
    try:
        sf = get_session_factory()
        with sf() as session:
            row = OpsActionAuditLog(
                user_id=int(user_id) if user_id else None,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=args_json[:8000],
                host_id=host_id[:64] if host_id else "",
                exit_code=exit_code,
                stdout_excerpt=stdout_excerpt[:12000],
                stderr_excerpt=stderr_excerpt[:4000],
                duration_ms=duration_ms,
                approval_required=approval_required,
                dry_run=dry_run,
                error=error[:2000],
            )
            session.add(row)
            session.flush()
            rid = int(row.id)
            session.commit()
            return rid
    except Exception as e:  # noqa: BLE001
        logger.exception("ops audit write failed: %s", e)
    return None


def _build_local_sync_argv() -> List[str]:
    """Windows: sync-modstore-to-server.ps1；Linux: 依赖 MODSTORE_SYNC_DEPLOY_BASH（sh -c 一行）。"""
    if os.name == "nt":
        ps1 = repo_root() / "MODstore_deploy" / "scripts" / "sync-modstore-to-server.ps1"
        if not ps1.is_file():
            raise FileNotFoundError(f"sync script missing: {ps1}")
        return [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ps1.resolve()),
        ]
    raw = os.environ.get("MODSTORE_SYNC_DEPLOY_BASH", "").strip()
    if not raw:
        raise FileNotFoundError(
            "non-Windows: set MODSTORE_SYNC_DEPLOY_BASH to a shell command for deploy (or run server on Windows)"
        )
    return shlex.split(raw)


def _load_host(host_id: str) -> Dict[str, Any]:
    path = _secrets_dir() / "ops_hosts.json"
    if not path.is_file():
        raise FileNotFoundError("ops_hosts.json missing under _local_secrets/")
    data = json.loads(path.read_text(encoding="utf-8"))
    hosts = data.get("hosts") if isinstance(data, dict) else data
    if not isinstance(hosts, dict) or host_id not in hosts:
        raise KeyError(f"unknown host_id: {host_id}")
    h = hosts[host_id]
    if not isinstance(h, dict):
        raise ValueError("host entry must be object")
    return h


def _validate_key_path(key_path: str) -> Path:
    kp = Path(key_path).expanduser()
    if not kp.is_absolute():
        kp = (_secrets_dir() / kp).resolve()
    kp = kp.resolve()
    base = _ssh_keys_dir().resolve()
    try:
        kp.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"key_path must be under {_ssh_keys_dir()}") from exc
    if not kp.is_file():
        raise FileNotFoundError(f"ssh key not found: {kp}")
    return kp


def _run_ssh(
    host_cfg: Dict[str, Any],
    argv: List[str],
    *,
    timeout: float,
    capture_max: int,
) -> Tuple[int, str, str]:
    try:
        import paramiko  # type: ignore[import-untyped]
    except ImportError as e:
        return 127, "", f"paramiko not installed: {e}"

    hostname = str(host_cfg.get("hostname") or "").strip()
    port = int(host_cfg.get("port") or 22)
    user = str(host_cfg.get("user") or "").strip()
    key_path = str(host_cfg.get("key_path") or "").strip()
    if not hostname or not user or not key_path:
        return 2, "", "host config missing hostname/user/key_path"

    key_file = _validate_key_path(key_path)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    t0 = time.perf_counter()
    try:
        client.connect(
            hostname,
            port=port,
            username=user,
            key_filename=str(key_file),
            timeout=min(30.0, timeout),
            banner_timeout=20,
        )
        cmd = shlex.join(argv)
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out_b = stdout.read() or b""
        err_b = stderr.read() or b""
        code = stdout.channel.recv_exit_status()
        elapsed = time.perf_counter() - t0
        if elapsed > timeout:
            return (
                -1,
                _truncate(out_b.decode("utf-8", errors="replace"), capture_max),
                "timeout",
            )
        return (
            int(code),
            _truncate(out_b.decode("utf-8", errors="replace"), capture_max),
            _truncate(err_b.decode("utf-8", errors="replace"), capture_max),
        )
    finally:
        try:
            client.close()
        except Exception:
            pass


def dispatch_ops_handler(
    handler: str,
    actions_cfg: Dict[str, Any],
    reasoning: Dict[str, Any],
    task: str,
    employee_id: str,
    user_id: int,
    *,
    force_real_run: bool = False,
) -> Dict[str, Any]:
    """Execute a white-listed operation through the split dispatch implementation."""
    from modstore_server.integrations.ops_action_dispatch import (
        dispatch_ops_handler as _impl,
    )

    return _impl(
        handler,
        actions_cfg,
        reasoning,
        task,
        employee_id,
        user_id,
        force_real_run=force_real_run,
    )


def ops_path_allowed(rel_path: str) -> bool:
    """只读 repo 路径是否允许运维员工通过 agent 读取。"""
    norm = rel_path.replace("\\", "/").lstrip("./")
    root_files = {
        "nginx-xiu-ci.conf",
        "nginx-xiu-ci-root.conf",
        "nginx-default.conf",
        "xiu-ci.com_nginx.zip",
    }
    if norm in root_files or norm.startswith("_nginx_extract/"):
        return True
    if norm.startswith("coverage/"):
        return True
    if norm.startswith("playwright-report/"):
        return True
    if norm.startswith("test-results/"):
        return True
    if norm.startswith("MODstore_deploy/.pytest_cache/"):
        return True
    if norm.startswith("_local_secrets/"):
        return True
    base = Path(norm).name
    if base.startswith(".cursor_") and base.endswith("_log.txt"):
        return True
    return False
