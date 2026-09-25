#!/usr/bin/env python3
"""等待 PR 合并。"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from typing import Optional


def is_pr_merged(*, pr_number: int, repo: Optional[str] = None) -> bool:
    """检查 PR 是否已合并。返回 True/False。"""
    repo = repo or os.environ.get("GITHUB_REPO", "")
    cmd = ["gh", "pr", "view", str(pr_number), "--json", "state", "--jq", ".state"]
    if repo:
        cmd.extend(["--repo", repo])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return result.stdout.strip() == "MERGED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--timeout-minutes", type=int, default=30)
    args = parser.parse_args()

    deadline = time.time() + args.timeout_minutes * 60
    while time.time() < deadline:
        if is_pr_merged(pr_number=args.pr_number):
            print(f"PR #{args.pr_number} merged")
            return 0
        time.sleep(30)
    print(f"PR #{args.pr_number} not merged within {args.timeout_minutes} minutes", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
