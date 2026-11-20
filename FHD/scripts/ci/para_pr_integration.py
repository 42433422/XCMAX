"""Approved, commit-bound order for XCMAX's nightly main integration."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

REPOSITORY = "42433422/XCMAX"
QUEUE_VARIABLE = "XCMAX_MAIN_MERGE_QUEUE"
SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_CLOSED = "integration_window_closed"


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
