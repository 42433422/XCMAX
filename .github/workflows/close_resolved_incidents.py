"""Retry the closes that hit GitHub 503. Removed after the job succeeds."""

from __future__ import annotations

import os
import subprocess
import sys
import time

REPO = os.environ["GH_REPO"]


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def close_numbered(number: str, comment: str) -> None:
    view = gh("issue", "view", number, "--repo", REPO, "--json", "state")
    if view.returncode == 0 and '"CLOSED"' in view.stdout:
        print(number, "already closed")
        return
    last = ""
    for attempt in range(4):
        result = gh(
            "issue",
            "close",
            number,
            "--repo",
            REPO,
            "--reason",
            "completed",
            "--comment",
            comment,
        )
        last = (result.stderr or result.stdout or "").strip()
        print(number, "close", attempt, result.returncode, last[:240])
        if result.returncode == 0:
            return
        time.sleep(5)
    raise SystemExit(f"failed to close {number}: {last[:300]}")


def main() -> int:
    close_numbered(
        "2908",
        "补关：上一轮关单遇到 GitHub 503。失败提交不在当前 main，"
        "CI/CD 497894ac5 已通过 https://github.com/42433422/XCMAX/actions/runs/41638626260 。",
    )
    close_numbered(
        "2939",
        "这次 Source Governance 失败来自关单步骤遇到的 GitHub 503，ratchet 与 sunbird 当时已成功。"
        "后续运行已通过：https://github.com/42433422/XCMAX/actions/runs/41645402238 。"
        "不是 main 上的源治理回归。关闭。",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
