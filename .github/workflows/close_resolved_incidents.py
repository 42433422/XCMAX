"""Finish the one-shot close that hit a GitHub 503, and record the scheduler block."""

from __future__ import annotations

import os
import subprocess
import sys
import time

REPO = os.environ["GH_REPO"]

NOTE_2903 = """复核结论：调度器进程在每次独立探测时并不稳定健康，本单先不关。

最近四次定时探测都是同一形态（间隔约 6–8 小时）：首次 `runtime_healthy=false` 且 `runtime_jobs=false`，引擎仍在跑、注册完整、仍有待执行任务；`systemctl restart` 后的即时探测因启动宽限变成 healthy，回执因此停在「等待下一次独立探测」。下一次独立探测再次不健康，关单条件（健康且本次未重启）没有成立。

- https://github.com/42433422/XCMAX/actions/runs/41627187197
- https://github.com/42433422/XCMAX/actions/runs/41573747829
- https://github.com/42433422/XCMAX/actions/runs/41538885711
- https://github.com/42433422/XCMAX/actions/runs/41456746601

回执没有任务名。健康端点只监听 CVM 的 `127.0.0.1:9990`；公网 `https://xiu-ci.com/fhd-api/api/xcmax/scheduler/health` 返回局域网拒绝。当前执行环境没有 `FHD_PUSH_SSH_KEY`，GitHub App 也不能 `workflow_dispatch`（403）。

已提交 https://github.com/42433422/XCMAX/pull/2938 ：探测原因会带上 `job_id:state:last_status:last_error_code`。合入 main 之后的下一次 watchdog 才能把具体任务写回本单。

阻塞：要读生产 `/api/xcmax/scheduler/health` 的 `unhealthy_runtime_jobs`，需要仓库 Secrets `FHD_PUSH_HOST` 与 `FHD_PUSH_SSH_KEY`，或等 #2938 合入后的下一次定时探测。在看到任务名之前不关单。
"""


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True)


def close_2908() -> None:
    view = gh("issue", "view", "2908", "--repo", REPO, "--json", "state")
    if view.returncode == 0 and '"CLOSED"' in view.stdout:
        print("2908 already closed")
        return
    last = ""
    for attempt in range(4):
        result = gh(
            "issue",
            "close",
            "2908",
            "--repo",
            REPO,
            "--reason",
            "completed",
            "--comment",
            "补关：上一轮关单遇到 GitHub 503。失败提交不在当前 main，CI/CD `497894ac5` 已通过 https://github.com/42433422/XCMAX/actions/runs/41638626260 。",
        )
        last = (result.stderr or result.stdout or "").strip()
        print("2908 close", attempt, result.returncode, last[:240])
        if result.returncode == 0:
            return
        time.sleep(5)
    raise SystemExit(f"failed to close 2908: {last[:300]}")


def comment_2903() -> None:
    result = gh("issue", "comment", "2903", "--repo", REPO, "--body", NOTE_2903)
    print("2903 comment", result.returncode, (result.stderr or "").strip()[:240])
    if result.returncode != 0:
        raise SystemExit("failed to comment on 2903")


def main() -> int:
    close_2908()
    comment_2903()
    return 0


if __name__ == "__main__":
    sys.exit(main())
