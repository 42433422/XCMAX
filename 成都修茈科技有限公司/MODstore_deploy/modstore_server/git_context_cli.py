"""CLI：打印当前仓库 Git + 部署档位 + 主机名（供运维 shell_exec 白名单调用）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from modstore_server.deploy_context import normalized_deploy_tier, resolve_hostname


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    tier = normalized_deploy_tier()
    host = resolve_hostname()

    def run_git(args: list[str]) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if r.returncode == 0:
                return (r.stdout or "").strip()
            err = (r.stderr or "").strip()
            return f"(git exit {r.returncode}) {err[:400]}"
        except Exception as e:
            return str(e)[:400]

    sha = run_git(["rev-parse", "HEAD"])
    branch = run_git(["branch", "--show-current"])
    st = run_git(["status", "-sb"])
    print(f"DEPLOY_TIER={tier}\nHOSTNAME={host}\nGIT_SHA={sha}\nBRANCH={branch}\nSTATUS\n{st}")


if __name__ == "__main__":
    main()
