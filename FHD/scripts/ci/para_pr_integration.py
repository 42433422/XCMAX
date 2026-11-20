"""Approved, commit-bound order for XCMAX's nightly main integration."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

REPOSITORY = "42433422/XCMAX"
QUEUE_VARIABLE = "XCMAX_MAIN_MERGE_QUEUE"
SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_CLOSED = "integration_window_closed"


def github(path: str) -> Any:
    return json.loads(
        subprocess.check_output(["gh", "api", f"repos/{REPOSITORY}/{path}"], text=True)
    )


def yesterday_main_pulls(now: datetime, read=github) -> dict[int, dict]:
    """Enumerate yesterday's main PRs, including drafts and closed PRs."""
    yesterday = now.astimezone(SHANGHAI).date() - timedelta(days=1)
    pulls = {}
    for page in range(1, 11):
        rows = read(f"pulls?state=all&sort=created&direction=desc&per_page=100&page={page}")
        if not isinstance(rows, list):
            raise ValueError("invalid PR inventory")
        for row in rows:
            created = datetime.fromisoformat(row["created_at"]).astimezone(SHANGHAI).date()
            if created < yesterday:
                return pulls
            base = row["base"]
            if (
                created == yesterday
                and base["ref"] == "main"
                and base["repo"]["full_name"].casefold() == REPOSITORY.casefold()
            ):
                pulls[row["number"]] = row
        if len(rows) < 100:
            return pulls
    raise ValueError("yesterday PR inventory exceeded the pagination limit")


def integration_window_open(now: datetime | None = None) -> bool:
    local = datetime.now(SHANGHAI) if now is None else now.astimezone(SHANGHAI)
    return 2 <= local.hour < 5


def integration_queue(raw: str) -> dict[int, str]:
    """Read the maintainer's ordered PR numbers and exact reviewed heads."""
    entries = json.loads(raw or "[]")
    if not isinstance(entries, list):
        raise ValueError(f"{QUEUE_VARIABLE} must be an ordered JSON array")
    queue: dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"pr", "head_sha"}:
            raise ValueError(f"{QUEUE_VARIABLE} entries need pr and head_sha")
        number, sha = entry["pr"], entry["head_sha"]
        if type(number) is not int or number < 1 or number in queue:
            raise ValueError(f"{QUEUE_VARIABLE} contains an invalid or duplicate PR number")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError(f"{QUEUE_VARIABLE} requires a full reviewed head SHA")
        queue[number] = sha
    return queue


def process_integration_queue(
    queue: dict[int, str],
    get_pr: Callable[[int], dict[str, Any]],
    process: Callable[[dict[str, Any]], str],
    *,
    dry_run: bool,
) -> bool:
    """Stop at the first unready entry so successors cannot overtake it."""
    for number, head_sha in queue.items():
        if not dry_run and not integration_window_open():
            print(f"[integration] PR #{number}: {WINDOW_CLOSED}")
            break
        pr = get_pr(number)
        base = pr.get("base") or {}
        if (
            pr.get("number") != number
            or base.get("ref") != "main"
            or str((base.get("repo") or {}).get("full_name", "")).casefold()
            != REPOSITORY.casefold()
            or (pr.get("head") or {}).get("sha") != head_sha
        ):
            print(f"[integration] PR #{number}: target or reviewed head changed; queue paused")
            break
        if pr.get("merged") is True and re.fullmatch(
            r"[0-9a-f]{40}", str(pr.get("merge_commit_sha") or "")
        ):
            continue
        if pr.get("state") != "open":
            print(f"[integration] PR #{number}: closed without a merge receipt; queue paused")
            break
        result = process(pr)
        print(f"[integration] PR #{number}: {result}")
        if result == "post_merge_dispatch_failed":
            return False
        if result not in {"auto_merged", "auto_merged_dry"}:
            break
    return True


def report_yesterday() -> None:
    now = datetime.now(SHANGHAI)
    if not integration_window_open(now):
        return
    approved = integration_queue(os.environ.get(QUEUE_VARIABLE, ""))
    rows = []
    for number in sorted(yesterday_main_pulls(now)):
        pull = github(f"pulls/{number}")
        labels = {row["name"] for row in pull.get("labels", [])}
        rows.append(
            {
                "pr": number,
                "head_sha": pull["head"]["sha"],
                "state": "merged" if pull["merged"] else pull["state"],
                "mergeability": pull["mergeable_state"],
                "draft": pull["draft"],
                "hold": "hold-merge" in labels,
                "ordered_head": approved.get(number) == pull["head"]["sha"],
            }
        )
    summary = [
        "### 昨日目标为 main 的 PR",
        "",
        "| PR | 状态 | GitHub 合入状态 | 草稿 | 暂缓 | 已排定当前提交 |",
        "|---|---|---|---|---|---|",
    ]
    for row in rows:
        summary.append(
            "| #{pr} | {state} | {mergeability} | {draft} | {hold} | {ordered_head} |".format(**row)
        )
    print(json.dumps(rows))
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n".join(summary) + "\n")


if __name__ == "__main__":
    report_yesterday()
