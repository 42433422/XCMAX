#!/usr/bin/env python3
"""Release security clearance: one zero-finding full scan of the exact release SHA.

用户 2026-10-19 01:31 CST 定的规则：安全扫描改「一次」——同一 SHA 一次零高危全量扫描即可
发布，不再要求两次扫描与 30 分钟间隔。仍保留的校验：全部扫描器报告齐全且可用、
release_sha/source_sha 与发布 SHA 完全一致、零 critical/high 与零未处置密钥、
current 报告 24 小时内、扫描器时间戳同一 UTC 日且合法。

``--previous-dir`` 变为可选：部署工作流仍按原接口传两个 run id；传同一个 run（单次扫描）
即通过；若传的是另一份扫描，它也必须对同一 SHA 零发现且在 48 小时内，但不再要求间隔。
没有任何跳过开关。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from security_release_gate import REQUIRED_SCANNERS, evaluate


def _scan_window(directory: Path) -> tuple[datetime, datetime]:
    """Return (earliest, latest) scanner timestamps; all must share one UTC date."""
    days = set()
    stamps = []
    for scanner in REQUIRED_SCANNERS:
        payload = json.loads(
            (directory / f"{scanner}.json").read_text(encoding="utf-8")
        )
        stamp = datetime.fromisoformat(
            str(payload["scanned_at"]).replace("Z", "+00:00")
        )
        stamp = stamp.astimezone(UTC)
        days.add(stamp.date())
        stamps.append(stamp)
    if len(days) != 1:
        raise ValueError("scanner timestamps do not share one UTC date")
    return min(stamps), max(stamps)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-dir", type=Path, default=None)
    parser.add_argument("--current-dir", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    current = evaluate(args.current_dir, release_sha=args.release_sha)
    blockers = [f"current:{item}" for item in current["blockers"]]
    try:
        _scan_window(args.current_dir)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        blockers.append(f"scan_timestamp_invalid:{type(exc).__name__}")
    mode = "single"
    previous_dir = args.previous_dir
    if (
        previous_dir is not None
        and previous_dir.resolve() != args.current_dir.resolve()
    ):
        mode = "single+extra"
        # 额外证据只核对同 SHA、零发现、48 小时内；不再要求间隔或跨日。
        previous = evaluate(
            previous_dir, max_age_hours=48, release_sha=args.release_sha
        )
        blockers.extend(f"previous:{item}" for item in previous["blockers"])
    result = {
        "schema": "security-release-scan-pair/v1",
        "mode": mode,
        "passed": not blockers,
        "release_sha": args.release_sha,
        "blockers": blockers,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
