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
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from security_release_gate import REQUIRED_SCANNERS, evaluate


def verify_source(directory, repository, run_id, release_sha, *, api=None, read_archive=None):
    """Bind downloaded reports to the original successful, manual scanner attempt.

    Reuse the existing release approval verifier and GitHub's archive digest;
    a report's self-declared SHA or an artifact name is not its provenance.
    """
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository or ""):
        raise ValueError("security source repository required")
    if not re.fullmatch(r"[1-9][0-9]*", run_id or ""):
        raise ValueError("security source run ID required")
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "scripts/ci"))
    from verify_modstore_release_approval import (
        _api,
        _archive,
        read_source_evidence,
        verify_run_source,
    )

    api = api or _api
    read_archive = read_archive or (lambda artifact: _archive(repository, artifact))
    route = f"/repos/{repository}/actions/runs/{run_id}"
    run = api(route)
    if (
        str(run.get("id")) != run_id
        or run.get("event") != "workflow_dispatch"
        or run.get("repository", {}).get("full_name") != repository
        or run.get("head_repository", {}).get("full_name") != repository
    ):
        raise ValueError("security source must be a manual scan in the release repository")
    proof = read_source_evidence(
        repository,
        "security_scan_run_id",
        run,
        release_sha,
        api=api,
        read_archive=read_archive,
    )
    verify_run_source(
        "security_scan_run_id",
        run,
        release_sha,
        source_evidence=proof,
        contains=lambda ancestor, descendant: (
            api(f"/repos/{repository}/compare/{ancestor}...{descendant}").get("status")
            in {"ahead", "identical"}
        ),
    )
    for filename, digest in proof["files"].items():
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != digest:
            raise ValueError("downloaded report differs from the original security artifact")
    return proof


def _scan_window(directory: Path) -> tuple[datetime, datetime]:
    """Return (earliest, latest) scanner timestamps; all must share one UTC date."""
    days = set()
    stamps = []
    for scanner in REQUIRED_SCANNERS:
        payload = json.loads((directory / f"{scanner}.json").read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(str(payload["scanned_at"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("scanner timestamp requires a timezone")
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
    parser.add_argument("--repository", help="GitHub repository of original scan artifacts")
    parser.add_argument("--current-run-id", help="Original successful manual scan run ID")
    parser.add_argument("--previous-run-id", help="Original optional extra scan run ID")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    current = evaluate(args.current_dir, release_sha=args.release_sha)
    blockers = [f"current:{item}" for item in current["blockers"]]
    if not re.fullmatch(r"[0-9a-f]{40}", args.release_sha):
        blockers.append("release_sha_invalid")
    sources = {}
    if any((args.repository, args.current_run_id, args.previous_run_id)):
        evidence = [("current", args.current_dir, args.current_run_id)]
        if args.previous_dir is not None:
            evidence.append(("previous", args.previous_dir, args.previous_run_id))
        elif args.previous_run_id:
            blockers.append("previous:source_directory_missing")
        for label, directory, run_id in evidence:
            try:
                sources[label] = verify_source(directory, args.repository, run_id, args.release_sha)
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                subprocess.SubprocessError,
            ) as exc:
                blockers.append(f"{label}:source_provenance_invalid:{type(exc).__name__}")
    try:
        _scan_window(args.current_dir)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        blockers.append(f"scan_timestamp_invalid:{type(exc).__name__}")
    mode = "single"
    previous_dir = args.previous_dir
    if previous_dir is not None and previous_dir.resolve() != args.current_dir.resolve():
        mode = "single+extra"
        # 额外证据只核对同 SHA、零发现、48 小时内；不再要求间隔或跨日。
        previous = evaluate(previous_dir, max_age_hours=48, release_sha=args.release_sha)
        blockers.extend(f"previous:{item}" for item in previous["blockers"])
        try:
            _scan_window(previous_dir)
        except (KeyError, OSError, TypeError, ValueError) as exc:
            blockers.append(f"previous:scan_timestamp_invalid:{type(exc).__name__}")
    result = {
        "schema": "security-release-scan-pair/v1",
        "mode": mode,
        "passed": not blockers,
        "release_sha": args.release_sha,
        "blockers": blockers,
        "sources": sources,
    }
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
