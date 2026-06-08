#!/usr/bin/env python3
"""上传 market-login patch 到生产 MODstore 并重拍需登录页。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST = os.environ.get("XCMAX_REMOTE_HOST", "119.27.178.147")
USER = os.environ.get("XCMAX_SSH_USER", "root")
DEPLOY = os.environ.get(
    "MODSTORE_SERVER_FILE",
    "/root/modstore-git/MODstore_deploy/modstore_server/daily_digest_surface_audit.py",
)
PATCH = Path(__file__).resolve().parent / "patch_surface_audit_market_login.py"
RECAP = Path(__file__).resolve().parent / "recapture_pw_market_auth.py"


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
    sftp.put(str(PATCH), "/tmp/patch_surface_audit_market_login.py")
    sftp.put(str(RECAP), "/tmp/recapture_pw_market_auth.py")
    sftp.close()

    cmds = [
        f"python3 /tmp/patch_surface_audit_market_login.py {DEPLOY}",
        "cd /root/modstore-git/MODstore_deploy && "
        "MODSTORE_INTERNAL_API_BASE=http://127.0.0.1:9990 "
        ".venv/bin/python /tmp/recapture_pw_market_auth.py",
    ]
    for cmd in cmds:
        _, stdout, stderr = ssh.exec_command(cmd, timeout=600)
        out = stdout.read().decode()
        err = stderr.read().decode()
        if out.strip():
            print(out.strip())
        if err.strip():
            print(err.strip(), file=sys.stderr)
        if stdout.channel.recv_exit_status() != 0:
            ssh.close()
            return 1
    ssh.close()
    print("deploy ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
