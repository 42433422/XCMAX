"""受控运维动作：shell_exec / ssh_exec，白名单命令 + 审计日志。"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from modstore_server.models import OpsActionAuditLog, get_session_factory

logger = logging.getLogger(__name__)

# macOS / minimal CI images often lack a ``python`` shim; always use the running interpreter.
_PY_EXE = sys.executable

OPS_EMPLOYEE_IDS = frozenset(
    {
        "nginx-config-engineer",
        "deploy-release-officer",
        "push-update-context-officer",
        "security-secrets-guard",
        "log-monitor-incident",
        "daily-orchestrator",
    }
)

# 程序化审批链（邮件 token 触发）使用的员工 id，仅允许跑 push/sync/probe
APPROVAL_DISPATCHER_EMPLOYEE_ID = "approval-dispatcher"


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


@dataclass(frozen=True)
class CommandSpec:
    """白名单命令：argv 模板中用 ${key} 占位，由调用方 args 填充。"""

    argv_template: Tuple[str, ...]
    allowed_employees: frozenset[str]
    default_timeout: float = 60.0
    requires_approval: bool = False
    capture_max_bytes: int = 8192
    kind: str = "shell"  # shell | ssh | local_sync


# 嵌入的短脚本（避免 Windows 无 rg/tail）
_GREP_CURSOR_PY = (
    "import glob,os,sys; r=sys.argv[1]; os.chdir(r); "
    "lines=[]\n"
    "for f in sorted(glob.glob('.cursor_*_log.txt')):\n"
    "    try:\n"
    "        t=open(f,encoding='utf-8',errors='replace').read().splitlines()\n"
    "        for i,l in enumerate(t):\n"
    "            if any(x in l.lower() for x in ('error','fail','exception')):\n"
    "                lines.append(f'{f}:{i+1}:{l[:500]}')\n"
    "    except OSError:\n"
    "        pass\n"
    "print('\\n'.join(lines[-80:]))"
)

_TAIL_LOG_PY = (
    "from pathlib import Path; import sys\n"
    "p=Path(sys.argv[1]); n=int(sys.argv[2] or '80')\n"
    "print('MISSING' if not p.is_file() else "
    "''.join(p.read_text(encoding='utf-8',errors='replace').splitlines(True)[-n:]))"
)


# 键：command_id
OPS_COMMAND_REGISTRY: Dict[str, CommandSpec] = {
    "nginx-syntax-check": CommandSpec(
        argv_template=("nginx", "-t"),
        allowed_employees=frozenset({"nginx-config-engineer"}),
        default_timeout=30.0,
        requires_approval=False,
    ),
    "nginx-reload": CommandSpec(
        argv_template=("nginx", "-s", "reload"),
        allowed_employees=frozenset({"nginx-config-engineer"}),
        default_timeout=30.0,
        requires_approval=True,
    ),
    "http-probe": CommandSpec(
        argv_template=(
            "curl",
            "-o",
            "/dev/null",
            "-s",
            "-w",
            "%{http_code}",
            "${url}",
        ),
        allowed_employees=frozenset({"nginx-config-engineer"}),
        default_timeout=30.0,
        requires_approval=False,
    ),
    "npm-build": CommandSpec(
        argv_template=("npm", "run", "build"),
        allowed_employees=frozenset({"deploy-release-officer"}),
        default_timeout=600.0,
        requires_approval=False,
    ),
    "git-checkout-tag": CommandSpec(
        argv_template=("git", "checkout", "${tag}"),
        allowed_employees=frozenset({"deploy-release-officer"}),
        default_timeout=120.0,
        requires_approval=True,
    ),
    "git-create-branch": CommandSpec(
        argv_template=("git", "checkout", "-b", "${branch}"),
        allowed_employees=frozenset({"daily-orchestrator"}),
        default_timeout=60.0,
        requires_approval=False,
    ),
    "git-add-all": CommandSpec(
        argv_template=("git", "add", "-A"),
        allowed_employees=frozenset({"daily-orchestrator"}),
        default_timeout=120.0,
        requires_approval=False,
    ),
    "git-commit-msg": CommandSpec(
        argv_template=(
            "git",
            "-c",
            "user.name=${git_name}",
            "-c",
            "user.email=${git_email}",
            "commit",
            "-m",
            "${message}",
        ),
        allowed_employees=frozenset({"daily-orchestrator"}),
        default_timeout=120.0,
        requires_approval=False,
    ),
    "git-push-branch": CommandSpec(
        argv_template=("git", "push", "${remote}", "${branch}"),
        allowed_employees=frozenset({APPROVAL_DISPATCHER_EMPLOYEE_ID}),
        default_timeout=300.0,
        requires_approval=True,
    ),
    "local-sync-deploy": CommandSpec(
        argv_template=("true",),
        allowed_employees=frozenset({APPROVAL_DISPATCHER_EMPLOYEE_ID}),
        default_timeout=900.0,
        requires_approval=True,
        kind="local_sync",
    ),
    "http-probe-after-deploy": CommandSpec(
        argv_template=(
            "curl",
            "-o",
            "/dev/null",
            "-s",
            "-w",
            "%{http_code}",
            "${url}",
        ),
        allowed_employees=frozenset({APPROVAL_DISPATCHER_EMPLOYEE_ID}),
        default_timeout=30.0,
        requires_approval=True,
    ),
    "tcb-pages-deploy": CommandSpec(
        argv_template=("tcb", "hosting", "deploy", "${dist_dir}", "-e", "${env_id}"),
        allowed_employees=frozenset({"deploy-release-officer"}),
        default_timeout=900.0,
        requires_approval=True,
        kind="ssh",
    ),
    "pip-audit-run": CommandSpec(
        argv_template=("pip-audit", "-r", "${req_file}"),
        allowed_employees=frozenset({"security-secrets-guard"}),
        default_timeout=300.0,
        requires_approval=False,
    ),
    "cert-expiry-check": CommandSpec(
        argv_template=(
            sys.executable,
            "-m",
            "modstore_server.tls_cert_inspection",
            "${path}",
        ),
        allowed_employees=frozenset({"security-secrets-guard"}),
        default_timeout=30.0,
        requires_approval=False,
    ),
    "secrets-perm-check": CommandSpec(
        argv_template=(
            _PY_EXE,
            "-c",
            "import os,sys; p=sys.argv[1]; m=os.stat(p).st_mode; print(oct(m)[-3:])",
            "${path}",
        ),
        allowed_employees=frozenset({"security-secrets-guard"}),
        default_timeout=15.0,
        requires_approval=False,
    ),
    "read-pytest-lastfailed": CommandSpec(
        argv_template=(
            _PY_EXE,
            "-c",
            "import sys; from pathlib import Path; p=Path(sys.argv[1]); "
            "print(p.read_text(encoding='utf-8', errors='replace')[:12000] if p.exists() else 'MISSING')",
            "${path}",
        ),
        allowed_employees=frozenset({"log-monitor-incident"}),
        default_timeout=30.0,
        requires_approval=False,
    ),
    "coverage-report": CommandSpec(
        argv_template=(_PY_EXE, "-m", "coverage", "report"),
        allowed_employees=frozenset({"log-monitor-incident"}),
        default_timeout=120.0,
        requires_approval=False,
    ),
    "grep-cursor-logs": CommandSpec(
        argv_template=(
            _PY_EXE,
            "-c",
            _GREP_CURSOR_PY,
            "${root}",
        ),
        allowed_employees=frozenset({"log-monitor-incident"}),
        default_timeout=60.0,
        requires_approval=False,
    ),
    "git-repo-context": CommandSpec(
        argv_template=(_PY_EXE, "-m", "modstore_server.git_context_cli", "${root}"),
        allowed_employees=frozenset({"push-update-context-officer"}),
        default_timeout=30.0,
        requires_approval=False,
    ),
    "tail-nginx-error-log": CommandSpec(
        argv_template=(
            _PY_EXE,
            "-c",
            _TAIL_LOG_PY,
            "${path}",
            "${lines}",
        ),
        allowed_employees=frozenset({"nginx-config-engineer"}),
        default_timeout=20.0,
        requires_approval=False,
    ),
}


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
            if key in ("path", "req_file", "dist_dir", "root", "rcfile", "ps1_path", "cwd"):
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
            return -1, _truncate(out_b.decode("utf-8", errors="replace"), capture_max), "timeout"
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
    """执行 shell_exec 或 ssh_exec（白名单）。

    ``force_real_run`` 仅允许 ``approval-dispatcher`` 在邮件 token 校验后跳过 requires_approval 的 dry-run。
    """
    if force_real_run and employee_id != APPROVAL_DISPATCHER_EMPLOYEE_ID:
        force_real_run = False
    cfg_key = "shell_exec" if handler == "shell_exec" else "ssh_exec"
    cfg = actions_cfg.get(cfg_key) if isinstance(actions_cfg.get(cfg_key), dict) else {}
    command_id = str(cfg.get("command_id") or "").strip()
    if not command_id:
        return {"handler": handler, "ok": False, "error": f"missing actions.{cfg_key}.command_id"}

    spec = OPS_COMMAND_REGISTRY.get(command_id)
    if not spec:
        aid = _write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=json.dumps(cfg.get("args") or {}, ensure_ascii=False),
            host_id=str(cfg.get("host_id") or ""),
            exit_code=-1,
            stdout_excerpt="",
            stderr_excerpt="",
            duration_ms=0.0,
            approval_required=False,
            dry_run=False,
            error="unknown command_id",
        )
        return {
            "handler": handler,
            "ok": False,
            "error": f"unknown command_id: {command_id}",
            "audit_log_id": aid,
        }

    if employee_id not in spec.allowed_employees:
        aid = _write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=json.dumps(cfg.get("args") or {}, ensure_ascii=False),
            host_id=str(cfg.get("host_id") or ""),
            exit_code=-1,
            stdout_excerpt="",
            stderr_excerpt="",
            duration_ms=0.0,
            approval_required=False,
            dry_run=False,
            error="employee not allowed for command",
        )
        return {
            "handler": handler,
            "ok": False,
            "error": "command not allowed for this employee",
            "audit_log_id": aid,
        }

    raw_args = cfg.get("args") if isinstance(cfg.get("args"), dict) else {}
    args: Dict[str, Any] = dict(raw_args)
    # 内置默认路径
    if command_id == "read-pytest-lastfailed" and "path" not in args:
        args["path"] = str(
            repo_root() / "MODstore_deploy" / ".pytest_cache" / "v" / "cache" / "lastfailed"
        )
    if command_id == "grep-cursor-logs" and "root" not in args:
        args["root"] = str(repo_root())
    if command_id == "tail-nginx-error-log":
        if "path" not in args:
            args["path"] = os.environ.get("OPS_NGINX_ERROR_LOG", "/var/log/nginx/error.log")
        if "lines" not in args:
            args["lines"] = "120"
    if command_id == "pip-audit-run" and "req_file" not in args:
        args["req_file"] = str(
            repo_root() / "MODstore_deploy" / "modstore_server" / "requirements.txt"
        )
    if command_id == "npm-build" and "cwd" in args:
        # npm 需在目录下执行：用 shell=False 时 cwd 参数
        pass
    if command_id == "git-push-branch" and not str(args.get("remote") or "").strip():
        args["remote"] = os.environ.get("MODSTORE_DEPLOY_PUSH_REMOTE", "origin").strip() or "origin"

    timeout = float(cfg.get("timeout") or spec.default_timeout)
    timeout = min(timeout, 900.0)
    capture_max = int(cfg.get("capture_max_bytes") or spec.capture_max_bytes)

    if spec.requires_approval and not force_real_run:
        msg = (
            f"[dry-run approval_required] would run {handler} command_id={command_id} "
            f"argv_template={spec.argv_template} args={args!r} task={task[:200]!r}"
        )
        aid = _write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=json.dumps(args, ensure_ascii=False),
            host_id=str(cfg.get("host_id") or ""),
            exit_code=None,
            stdout_excerpt=_truncate(msg, capture_max),
            stderr_excerpt="",
            duration_ms=0.0,
            approval_required=True,
            dry_run=True,
            error="",
        )
        return {
            "handler": handler,
            "ok": True,
            "approval_required": True,
            "dry_run": True,
            "command_id": command_id,
            "message": msg,
            "audit_log_id": aid,
        }

    argv: List[str]
    try:
        if command_id in ("git-create-branch", "git-push-branch"):
            args["branch"] = _sanitize_branch(str(args.get("branch") or ""))
        if command_id == "git-commit-msg":
            args.setdefault("git_name", os.environ.get("MODSTORE_GIT_AUTHOR_NAME", "MODstore Bot"))
            args.setdefault(
                "git_email", os.environ.get("MODSTORE_GIT_AUTHOR_EMAIL", "bot@localhost")
            )
            msg = str(args.get("message") or "").strip()
            if len(msg) > 500:
                raise ValueError("commit message too long")
            args["message"] = msg or "chore: daily orchestrator"
        if command_id in ("git-create-branch", "git-add-all", "git-commit-msg") and not args.get(
            "cwd"
        ):
            args["cwd"] = str(repo_root())
        if command_id == "http-probe-after-deploy" and not str(args.get("url") or "").strip():
            args["url"] = os.environ.get(
                "MODSTORE_DEPLOY_HEALTH_URL", "http://127.0.0.1:9999/api/health"
            ).strip()
        if spec.kind == "local_sync":
            argv = _build_local_sync_argv()
        else:
            argv = _render_argv(spec.argv_template, args)
    except (ValueError, FileNotFoundError) as e:
        aid = _write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=json.dumps(args, ensure_ascii=False),
            host_id=str(cfg.get("host_id") or ""),
            exit_code=-1,
            stdout_excerpt="",
            stderr_excerpt="",
            duration_ms=0.0,
            approval_required=False,
            dry_run=False,
            error=str(e),
        )
        return {"handler": handler, "ok": False, "error": str(e), "audit_log_id": aid}

    shell_cwd: Optional[str] = None
    if handler == "shell_exec" and spec.kind == "shell":
        if command_id == "npm-build" and args.get("cwd"):
            shell_cwd = str(Path(_resolve_path_arg(str(args["cwd"]))))
        elif args.get("cwd"):
            shell_cwd = str(Path(_resolve_path_arg(str(args["cwd"]))))
        try:
            _assert_shell_paths_safe(command_id, args, shell_cwd)
        except ValueError as e:
            aid = _write_audit(
                user_id=user_id,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=json.dumps(args, ensure_ascii=False),
                host_id=str(cfg.get("host_id") or ""),
                exit_code=-1,
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=0.0,
                approval_required=False,
                dry_run=False,
                error=str(e),
            )
            return {"handler": handler, "ok": False, "error": str(e), "audit_log_id": aid}

    t0 = time.perf_counter()
    stdout_s = stderr_s = ""
    exit_code: Optional[int] = -1

    if handler == "ssh_exec" or spec.kind == "ssh":
        hid = str(cfg.get("host_id") or "").strip()
        if not hid:
            err = "missing host_id for ssh_exec"
            _write_audit(
                user_id=user_id,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=json.dumps(args, ensure_ascii=False),
                host_id="",
                exit_code=-1,
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                approval_required=False,
                dry_run=False,
                error=err,
            )
            return {"handler": handler, "ok": False, "error": err}
        try:
            host_cfg = _load_host(hid)
        except Exception as e:  # noqa: BLE001
            _write_audit(
                user_id=user_id,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=json.dumps(args, ensure_ascii=False),
                host_id=hid,
                exit_code=-1,
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=round((time.perf_counter() - t0) * 1000, 3),
                approval_required=False,
                dry_run=False,
                error=str(e),
            )
            return {"handler": handler, "ok": False, "error": str(e)}
        code, stdout_s, stderr_s = _run_ssh(
            host_cfg, argv, timeout=timeout, capture_max=capture_max
        )
        exit_code = code
    elif spec.kind == "local_sync":
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=dict(os.environ),
                cwd=str(repo_root()),
                shell=False,
            )
            exit_code = int(proc.returncode)
            stdout_s = _truncate(proc.stdout or "", capture_max)
            stderr_s = _truncate(proc.stderr or "", capture_max)
        except subprocess.TimeoutExpired:
            exit_code = -1
            stdout_s = ""
            stderr_s = "timeout"
        except FileNotFoundError as e:
            exit_code = -1
            stdout_s = ""
            stderr_s = str(e)
    else:
        if os.name == "nt":
            argv = [os.devnull if a == "/dev/null" else a for a in argv]
        cwd_run = shell_cwd
        if cwd_run is None and command_id == "npm-build" and args.get("cwd"):
            cwd_run = str(Path(_resolve_path_arg(str(args["cwd"]))))
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_audit_env(),
                cwd=cwd_run or None,
                shell=False,
            )
            exit_code = int(proc.returncode)
            stdout_s = _truncate(proc.stdout or "", capture_max)
            stderr_s = _truncate(proc.stderr or "", capture_max)
        except subprocess.TimeoutExpired:
            exit_code = -1
            stdout_s = ""
            stderr_s = "timeout"
        except FileNotFoundError as e:
            exit_code = -1
            stdout_s = ""
            stderr_s = str(e)

    if command_id == "http-probe-after-deploy" and exit_code == 0:
        expect = str(args.get("expected_code") or "200").strip()
        got = (stdout_s or "").strip()
        if got != expect:
            exit_code = 1
            stderr_s = ((stderr_s or "") + f"\nexpected HTTP {expect}, got {got!r}").strip()

    duration_ms = round((time.perf_counter() - t0) * 1000, 3)
    hid = str(cfg.get("host_id") or "")
    err_final = (stderr_s or "")[:2000] if exit_code not in (0, None) else ""
    aid = _write_audit(
        user_id=user_id,
        employee_id=employee_id,
        handler=handler,
        command_id=command_id,
        args_json=json.dumps(args, ensure_ascii=False),
        host_id=hid,
        exit_code=exit_code,
        stdout_excerpt=stdout_s,
        stderr_excerpt=stderr_s,
        duration_ms=duration_ms,
        approval_required=False,
        dry_run=False,
        error=err_final,
    )
    ok = exit_code == 0
    return {
        "handler": handler,
        "ok": ok,
        "command_id": command_id,
        "exit_code": exit_code,
        "stdout": stdout_s,
        "stderr": stderr_s,
        "duration_ms": duration_ms,
        "audit_log_id": aid,
    }


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
