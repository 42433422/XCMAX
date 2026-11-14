"""Release-scope evidence. This does not decide the merge gate.

A missing Windows or macOS installer blocks that release scope. It does not
turn a Linux upgrade or a browser run into an installer pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

_INSTALL_PLATFORMS = frozenset({"windows", "macos"})
_PASS_BLOCKERS = frozenset({"FAIL", "BLOCKED", "NOT RUN"})


def judge_scope(row: dict) -> str:
    status = str(row.get("status") or "NOT RUN")
    kind = str(row.get("kind") or "")
    platform = str(row.get("platform") or "")
    if kind == "browser" and row.get("satisfies") == "installer":
        return "NOT APPLICABLE"
    if platform == "linux" and row.get("satisfies") in _INSTALL_PLATFORMS:
        return "NOT APPLICABLE"
    if status == "PASS":
        if kind in {"installer", "upgrade"} and not row.get("artifact_sha256"):
            return "FAIL"
        if not row.get("source_sha"):
            return "FAIL"
    return status


def rollup(rows: list[dict]) -> dict:
    judged = []
    for row in rows:
        item = dict(row)
        item["verdict"] = judge_scope(row)
        judged.append(item)
    by_platform: dict[str, str] = {}
    for item in judged:
        platform = str(item.get("platform") or "")
        verdict = item["verdict"]
        current = by_platform.get(platform)
        if current in _PASS_BLOCKERS:
            continue
        if verdict in _PASS_BLOCKERS or current is None:
            by_platform[platform] = verdict
    release_pass = bool(by_platform) and all(
        verdict == "PASS" for verdict in by_platform.values()
    )
    return {"rows": judged, "platforms": by_platform, "release_pass": release_pass}


def snapshot_discards_later_rows(snapshot: Path, upgraded: Path, table: str) -> bool:
    def count(path: Path) -> int:
        conn = sqlite3.connect(path)
        try:
            return int(conn.execute(f"select count(*) from {table}").fetchone()[0])
        finally:
            conn.close()

    return count(snapshot) < count(upgraded)


def _installer_files(root: Path, suffix: str) -> list[Path]:
    return sorted(
        path
        for path in root.rglob(f"*{suffix}")
        if path.is_file() and not path.name.endswith(".blockmap")
    )


def installer_rows(root: Path, source_sha: str) -> list[dict]:
    rows: list[dict] = []
    for platform, suffix in (("windows", ".exe"), ("macos", ".dmg")):
        matches = _installer_files(root, suffix)
        if not matches:
            rows.append(
                {
                    "platform": platform,
                    "kind": "installer",
                    "status": "NOT RUN",
                    "source_sha": source_sha,
                    "satisfies": platform,
                }
            )
            continue
        digest = hashlib.sha256(matches[0].read_bytes()).hexdigest()
        rows.append(
            {
                "platform": platform,
                "kind": "installer",
                "status": "PASS",
                "source_sha": source_sha,
                "artifact_sha256": digest,
                "satisfies": platform,
                "path": str(matches[0]),
            }
        )
    return rows


def release_gate(root: Path, source_sha: str) -> tuple[int, dict]:
    if len(source_sha) != 40 or any(char not in "0123456789abcdef" for char in source_sha):
        report = {"release_pass": False, "error": "source_sha must be 40 lowercase hex characters"}
        return 1, report
    report = rollup(installer_rows(root, source_sha))
    passed = (
        report["platforms"].get("windows") == "PASS"
        and report["platforms"].get("macos") == "PASS"
    )
    report["release_pass"] = passed
    return (0 if passed else 1), report


def _self_check() -> int:
    """BLOCKED and a missing installer stay failures for the release scope."""
    blocked = rollup(
        [
            {
                "platform": "windows",
                "kind": "installer",
                "status": "BLOCKED",
                "source_sha": "a" * 40,
                "satisfies": "windows",
            },
            {
                "platform": "macos",
                "kind": "installer",
                "status": "PASS",
                "source_sha": "a" * 40,
                "artifact_sha256": "b" * 64,
                "satisfies": "macos",
            },
        ]
    )
    missing = rollup(
        [
            {
                "platform": "windows",
                "kind": "installer",
                "status": "NOT RUN",
                "source_sha": "a" * 40,
                "satisfies": "windows",
            }
        ]
    )
    if blocked["release_pass"] or missing["platforms"].get("windows") != "NOT RUN":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--source-sha")
    args = parser.parse_args(argv)
    if args.self_check:
        return _self_check()
    if not args.artifact_dir or not args.source_sha:
        parser.error("--artifact-dir and --source-sha are required")
    code, report = release_gate(Path(args.artifact_dir), args.source_sha)
    json.dump(report, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
