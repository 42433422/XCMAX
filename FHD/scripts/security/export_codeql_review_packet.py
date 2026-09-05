#!/usr/bin/env python3
"""Prepare a source-bound review queue; never approve or dismiss an alert.

Input is the authenticated GitHub API export (including --paginate --slurp).
Only hashes of dismissal comments are exported: reviewers must inspect the
original alert, exact source and data flow before making their own decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


def build_packet(payload: object, root: Path, sha: str, source_digest: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("full commit SHA required")
    if not isinstance(payload, list):
        raise ValueError("expected GitHub alert list")
    rows = (
        [row for page in payload for row in page]
        if payload and all(isinstance(page, list) for page in payload)
        else payload
    )
    queue = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not {"number", "rule", "state"}.issubset(row):
            raise ValueError("incomplete GitHub alert export")
        rule = row["rule"]
        if row["state"] != "dismissed" or rule.get("security_severity_level") not in {
            "critical",
            "high",
        }:
            continue
        number = row["number"]
        if not isinstance(number, int) or number in seen:
            raise ValueError("invalid or duplicate alert ID")
        seen.add(number)
        instance = row.get("most_recent_instance") or {}
        location = instance.get("location") or {}
        filename = str(location.get("path") or "")
        safe_path = (
            bool(filename)
            and not PurePosixPath(filename).is_absolute()
            and ".." not in PurePosixPath(filename).parts
        )
        source = (
            subprocess.run(
                ["git", "show", f"{sha}:{filename}"],
                cwd=root,
                capture_output=True,
                check=False,
            )
            if safe_path
            else None
        )
        source_available = source is not None and source.returncode == 0
        comment = str(row.get("dismissed_comment") or "")
        queue.append(
            {
                "alert_id": number,
                "alert_url": row.get("html_url"),
                "rule_id": rule.get("id"),
                "severity": rule.get("security_severity_level"),
                "location": location,
                "last_analysis_sha": instance.get("commit_sha"),
                "review_source_sha": sha,
                "source_available": source_available,
                "source_blob_sha256": hashlib.sha256(source.stdout).hexdigest()
                if source_available
                else None,
                "previous_dismissal": {
                    "reason": row.get("dismissed_reason"),
                    "actor": (row.get("dismissed_by") or {}).get("login"),
                    "at": row.get("dismissed_at"),
                    "comment_sha256": hashlib.sha256(comment.encode()).hexdigest(),
                },
                "review_status": "pending_independent_review",
                "approval": None,
            }
        )
    return {
        "schema": "codeql-independent-review-queue/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_sha": sha,
        "input_sha256": source_digest,
        "does_not_grant_approval": True,
        "count": len(queue),
        "counts_by_rule": dict(sorted(Counter(item["rule_id"] for item in queue).items())),
        "alerts": sorted(queue, key=lambda item: item["alert_id"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    raw = args.input.read_bytes()
    packet = build_packet(
        json.loads(raw), args.repo_root, args.sha, hashlib.sha256(raw).hexdigest()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"count": packet["count"], "counts_by_rule": packet["counts_by_rule"], "approved": 0}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
