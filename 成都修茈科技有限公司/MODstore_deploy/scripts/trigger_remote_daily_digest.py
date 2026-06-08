"""One-shot: SSH to production and run run_daily_digest_email (loads server .env).

Usage (from repo root or anywhere):
  python MODstore_deploy/scripts/trigger_remote_daily_digest.py

Environment:
  DEPLOY_SSH  optional, default root@119.27.178.147
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> None:
    target = (os.environ.get("DEPLOY_SSH") or "").strip() or "root@119.27.178.147"
    deploy = "/root/modstore-git/MODstore_deploy"
    py = (
        "import logging,sys;"
        "logging.basicConfig(level=logging.INFO,stream=sys.stderr);"
        "from modstore_server.daily_digest import run_daily_digest_email;"
        "run_daily_digest_email();"
        'print("daily_digest_trigger:ok", file=sys.stderr)'
    )
    rcmd = f"cd {deploy} && set -a && . {deploy}/.env && set +a && {deploy}/.venv/bin/python -u -c {repr(py)}"
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=25", target, "bash", "-lc", rcmd],
        check=False,
    )
    raise SystemExit(r.returncode)


if __name__ == "__main__":
    main()
