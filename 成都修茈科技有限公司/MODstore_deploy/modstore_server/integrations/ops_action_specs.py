"""Declarative command allowlist for controlled operational actions."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, Tuple

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
