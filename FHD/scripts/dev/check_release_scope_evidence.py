"""Release-scope evidence. This does not decide the merge gate.

A missing Windows or macOS installer blocks that release scope. It does not
turn a Linux upgrade or a browser run into an installer pass.
"""

from __future__ import annotations

import sqlite3
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
