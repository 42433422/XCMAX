#!/usr/bin/env python3
"""部署 MODstore 管理端身份码 · 方案 A（公网自签发）到 xiu-ci.com 生产。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
USER = os.environ.get("XCMAX_SSH_USER", "root")
MODSTORE_ROOT = os.environ.get(
    "MODSTORE_DEPLOY_ROOT",
    "/root/modstore-git/MODstore_deploy/modstore_server",
)

HERE = Path(__file__).resolve().parent
MODSTORE_LOCAL = HERE.parents[1] / "MODstore" / "modstore_server"
FILES = (
    "admin_digest_identity.py",
    "xcmax_admin_digest_api.py",
    "fhd_routes_registry.py",
    "digest_action_items.py",
    "action_items_api.py",
)


def main() -> int:
    password = os.environ.get("XCMAX_SSH_PASSWORD", "").strip()
    if not password:
        print("请设置 XCMAX_SSH_PASSWORD 后重试", file=sys.stderr)
        return 1
    try:
        import paramiko
    except ImportError:
        print("pip install paramiko", file=sys.stderr)
        return 1

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=password, timeout=20)
    sftp = ssh.open_sftp()
    for name in FILES:
        local = MODSTORE_LOCAL / name
        if not local.is_file():
            print(f"缺少本地文件: {local}", file=sys.stderr)
            return 1
        remote = f"{MODSTORE_ROOT.rstrip('/')}/{name}"
        sftp.put(str(local), remote)
        print(f"uploaded {name} -> {remote}")
    sftp.close()

    secret = os.environ.get("XCMAX_DIGEST_IDENTITY_SECRET", "").strip()
    env_hint = (
        f"export XCMAX_DIGEST_IDENTITY_SECRET='{secret}'"
        if secret
        else "# 请在 MODstore .env 设置 XCMAX_DIGEST_IDENTITY_SECRET（与 FHD 生产相同）"
    )
    cmds = [
        f"grep -q xcmax_admin_digest_router {MODSTORE_ROOT}/fhd_routes_registry.py || "
        f"echo 'WARN: fhd_routes_registry 未注册 xcmax_admin_digest_router'",
        "echo '--- 生产环境需确保 ---'",
        "echo '1. unset MODSTORE_DIGEST_IDENTITY_UPSTREAM_URL  # 方案 A 不用 peer'",
        f"echo '2. {env_hint}'",
        "echo '3. MODSTORE_PUBLIC_API_BASE=https://xiu-ci.com'",
        "echo '4. systemctl restart modstore  # 或你的进程管理命令'",
    ]
    for cmd in cmds:
        _, stdout, stderr = ssh.exec_command(cmd)
        out = (stdout.read() + stderr.read()).decode("utf-8", errors="replace").strip()
        if out:
            print(out)
    ssh.close()
    print("部署文件已上传；请按上方提示配置 secret 并重启 MODstore。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
