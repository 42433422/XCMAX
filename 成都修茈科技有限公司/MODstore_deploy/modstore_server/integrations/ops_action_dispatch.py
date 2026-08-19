# ruff: noqa
"""Execution implementation for controlled operational actions."""
from __future__ import annotations
import importlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _facade():
    return importlib.import_module("modstore_server.integrations.ops_action_handlers")


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
    if force_real_run and employee_id != _facade().APPROVAL_DISPATCHER_EMPLOYEE_ID:
        force_real_run = False
    cfg_key = "shell_exec" if handler == "shell_exec" else "ssh_exec"
    cfg = actions_cfg.get(cfg_key) if isinstance(actions_cfg.get(cfg_key), dict) else {}
    command_id = str(cfg.get("command_id") or "").strip()
    if not command_id:
        return {"handler": handler, "ok": False, "error": f"missing actions.{cfg_key}.command_id"}
    spec = _facade().OPS_COMMAND_REGISTRY.get(command_id)
    if not spec:
        aid = _facade()._write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=_facade().json.dumps(cfg.get("args") or {}, ensure_ascii=False),
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
        aid = _facade()._write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=_facade().json.dumps(cfg.get("args") or {}, ensure_ascii=False),
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
    if command_id == "read-pytest-lastfailed" and "path" not in args:
        args["path"] = str(
            _facade().repo_root()
            / "MODstore_deploy"
            / ".pytest_cache"
            / "v"
            / "cache"
            / "lastfailed"
        )
    if command_id == "grep-cursor-logs" and "root" not in args:
        args["root"] = str(_facade().repo_root())
    if command_id == "tail-nginx-error-log":
        if "path" not in args:
            args["path"] = _facade().os.environ.get(
                "OPS_NGINX_ERROR_LOG", "/var/log/nginx/error.log"
            )
        if "lines" not in args:
            args["lines"] = "120"
    if command_id == "pip-audit-run" and "req_file" not in args:
        args["req_file"] = str(
            _facade().repo_root() / "MODstore_deploy" / "modstore_server" / "requirements.txt"
        )
    if command_id == "npm-build" and "cwd" in args:
        pass
    if command_id == "git-push-branch" and (not str(args.get("remote") or "").strip()):
        args["remote"] = (
            _facade().os.environ.get("MODSTORE_DEPLOY_PUSH_REMOTE", "origin").strip() or "origin"
        )
    timeout = float(cfg.get("timeout") or spec.default_timeout)
    timeout = min(timeout, 900.0)
    capture_max = int(cfg.get("capture_max_bytes") or spec.capture_max_bytes)
    if spec.requires_approval and (not force_real_run):
        msg = f"[dry-run approval_required] would run {handler} command_id={command_id} argv_template={spec.argv_template} args={args!r} task={task[:200]!r}"
        aid = _facade()._write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=_facade().json.dumps(args, ensure_ascii=False),
            host_id=str(cfg.get("host_id") or ""),
            exit_code=None,
            stdout_excerpt=_facade()._truncate(msg, capture_max),
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
            args["branch"] = _facade()._sanitize_branch(str(args.get("branch") or ""))
        if command_id == "git-commit-msg":
            args.setdefault(
                "git_name", _facade().os.environ.get("MODSTORE_GIT_AUTHOR_NAME", "MODstore Bot")
            )
            args.setdefault(
                "git_email", _facade().os.environ.get("MODSTORE_GIT_AUTHOR_EMAIL", "bot@localhost")
            )
            msg = str(args.get("message") or "").strip()
            if len(msg) > 500:
                raise ValueError("commit message too long")
            args["message"] = msg or "chore: daily orchestrator"
        if command_id in ("git-create-branch", "git-add-all", "git-commit-msg") and (
            not args.get("cwd")
        ):
            args["cwd"] = str(_facade().repo_root())
        if command_id == "http-probe-after-deploy" and (not str(args.get("url") or "").strip()):
            args["url"] = (
                _facade()
                .os.environ.get("MODSTORE_DEPLOY_HEALTH_URL", "http://127.0.0.1:9999/api/health")
                .strip()
            )
        if spec.kind == "local_sync":
            argv = _facade()._build_local_sync_argv()
        else:
            argv = _facade()._render_argv(spec.argv_template, args)
    except (ValueError, FileNotFoundError) as e:
        aid = _facade()._write_audit(
            user_id=user_id,
            employee_id=employee_id,
            handler=handler,
            command_id=command_id,
            args_json=_facade().json.dumps(args, ensure_ascii=False),
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
            shell_cwd = str(_facade().Path(_facade()._resolve_path_arg(str(args["cwd"]))))
        elif args.get("cwd"):
            shell_cwd = str(_facade().Path(_facade()._resolve_path_arg(str(args["cwd"]))))
        try:
            _facade()._assert_shell_paths_safe(command_id, args, shell_cwd)
        except ValueError as e:
            aid = _facade()._write_audit(
                user_id=user_id,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=_facade().json.dumps(args, ensure_ascii=False),
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
    t0 = _facade().time.perf_counter()
    stdout_s = stderr_s = ""
    exit_code: Optional[int] = -1
    if handler == "ssh_exec" or spec.kind == "ssh":
        hid = str(cfg.get("host_id") or "").strip()
        if not hid:
            err = "missing host_id for ssh_exec"
            _facade()._write_audit(
                user_id=user_id,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=_facade().json.dumps(args, ensure_ascii=False),
                host_id="",
                exit_code=-1,
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=round((_facade().time.perf_counter() - t0) * 1000, 3),
                approval_required=False,
                dry_run=False,
                error=err,
            )
            return {"handler": handler, "ok": False, "error": err}
        try:
            host_cfg = _facade()._load_host(hid)
        except Exception as e:
            _facade()._write_audit(
                user_id=user_id,
                employee_id=employee_id,
                handler=handler,
                command_id=command_id,
                args_json=_facade().json.dumps(args, ensure_ascii=False),
                host_id=hid,
                exit_code=-1,
                stdout_excerpt="",
                stderr_excerpt="",
                duration_ms=round((_facade().time.perf_counter() - t0) * 1000, 3),
                approval_required=False,
                dry_run=False,
                error=str(e),
            )
            return {"handler": handler, "ok": False, "error": str(e)}
        (code, stdout_s, stderr_s) = _facade()._run_ssh(
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
                env=dict(_facade().os.environ),
                cwd=str(_facade().repo_root()),
                shell=False,
            )
            exit_code = int(proc.returncode)
            stdout_s = _facade()._truncate(proc.stdout or "", capture_max)
            stderr_s = _facade()._truncate(proc.stderr or "", capture_max)
        except subprocess.TimeoutExpired:
            exit_code = -1
            stdout_s = ""
            stderr_s = "timeout"
        except FileNotFoundError as e:
            exit_code = -1
            stdout_s = ""
            stderr_s = str(e)
    else:
        if _facade().os.name == "nt":
            argv = [_facade().os.devnull if a == "/dev/null" else a for a in argv]
        cwd_run = shell_cwd
        if cwd_run is None and command_id == "npm-build" and args.get("cwd"):
            cwd_run = str(_facade().Path(_facade()._resolve_path_arg(str(args["cwd"]))))
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=_facade()._audit_env(),
                cwd=cwd_run or None,
                shell=False,
            )
            exit_code = int(proc.returncode)
            stdout_s = _facade()._truncate(proc.stdout or "", capture_max)
            stderr_s = _facade()._truncate(proc.stderr or "", capture_max)
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
    duration_ms = round((_facade().time.perf_counter() - t0) * 1000, 3)
    hid = str(cfg.get("host_id") or "")
    err_final = (stderr_s or "")[:2000] if exit_code not in (0, None) else ""
    aid = _facade()._write_audit(
        user_id=user_id,
        employee_id=employee_id,
        handler=handler,
        command_id=command_id,
        args_json=_facade().json.dumps(args, ensure_ascii=False),
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
