"""SSH to production and run onboard_yuangon_employees.py with optional --pkg-ids.

Example:
  python scripts/trigger_remote_onboard_yuangon.py --pkg-ids a,b
"""

from __future__ import annotations

import argparse
import os
import subprocess
from shlex import quote as shlex_quote


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkg-ids", required=True, help="Comma-separated pkg_id list")
    ap.add_argument("--force", action="store_true", help="Pass --force to onboard script")
    args = ap.parse_args()
    target = (os.environ.get("DEPLOY_SSH") or "").strip() or "root@119.27.178.147"
    deploy = "/root/modstore-git/MODstore_deploy"
    repo = "/root/modstore-git"
    extra = " --force" if args.force else ""
    ids_q = shlex_quote(args.pkg_ids)
    inner = (
        f"cd {deploy} && set -a && . {deploy}/.env && set +a && "
        f"{deploy}/.venv/bin/python {deploy}/modstore_server/scripts/onboard_yuangon_employees.py "
        f"--repo-root {repo} --pkg-ids {ids_q}{extra}"
    )
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30", target, "bash", "-lc", inner],
        check=False,
    )
    raise SystemExit(r.returncode)


if __name__ == "__main__":
    main()
