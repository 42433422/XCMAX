"""Release-scope evidence. This does not decide the merge gate.

A missing Windows or macOS installer blocks that release scope. It does not
turn a Linux upgrade or a browser run into an installer pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

_INSTALL_PLATFORMS = frozenset({"windows", "macos"})
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_SCOPES = ("windows-installer", "macos-installer", "upgrade-rollback")


def judge_scope(row: dict) -> str:
    status = str(row.get("status") or "NOT RUN")
    kind = str(row.get("kind") or "")
    platform = str(row.get("platform") or "")
    if kind == "browser" and row.get("satisfies") == "installer":
        return "NOT APPLICABLE"
    if platform == "linux" and row.get("satisfies") in _INSTALL_PLATFORMS:
        return "NOT APPLICABLE"
    if status == "PASS":
        if not _SHA40.fullmatch(str(row.get("source_sha") or "")):
            return "FAIL"
        if kind in {"installer", "upgrade"} and not _SHA256.fullmatch(
            str(row.get("artifact_sha256") or "")
        ):
            return "FAIL"
    return status


def _combine(verdicts: list[str]) -> str:
    applicable = [item for item in verdicts if item != "NOT APPLICABLE"]
    if not applicable:
        return "NOT RUN"
    for status in ("FAIL", "BLOCKED", "NOT RUN"):
        if status in applicable:
            return status
    if all(item == "PASS" for item in applicable):
        return "PASS"
    return "NOT RUN"


def rollup(rows: list[dict], required_scopes: tuple[str, ...] = ()) -> dict:
    judged = []
    grouped: dict[str, list[str]] = {}
    for row in rows:
        item = dict(row)
        verdict = judge_scope(row)
        item["verdict"] = verdict
        judged.append(item)
        key = str(item.get("scope_id") or item.get("platform") or "")
        grouped.setdefault(key, []).append(verdict)
    scopes = {key: _combine(verdicts) for key, verdicts in grouped.items()}
    for scope in required_scopes:
        scopes.setdefault(scope, "NOT RUN")
    platforms = {
        str(item.get("platform") or ""): scopes[str(item.get("scope_id") or item.get("platform") or "")]
        for item in judged
    }
    required = required_scopes or tuple(scopes)
    release_pass = bool(required) and all(scopes.get(scope) == "PASS" for scope in required)
    return {
        "rows": judged,
        "platforms": platforms,
        "scopes": scopes,
        "release_pass": release_pass,
    }


def snapshot_discards_later_rows(
    snapshot: Path, upgraded: Path, table: str, columns: tuple[str, ...] = ("id", "name")
) -> bool:
    if not _IDENT.fullmatch(table) or any(not _IDENT.fullmatch(column) for column in columns):
        raise ValueError("unsafe sql identifier")
    selected = ", ".join(columns)

    def load(path: Path) -> set[tuple]:
        conn = sqlite3.connect(path)
        try:
            return {tuple(row) for row in conn.execute(f"select {selected} from {table}")}
        finally:
            conn.close()

    return load(snapshot) != load(upgraded)


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
                    "scope_id": f"{platform}-installer",
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
                "scope_id": f"{platform}-installer",
                "kind": "installer",
                "status": "PASS",
                "source_sha": source_sha,
                "artifact_sha256": digest,
                "satisfies": platform,
                "path": str(matches[0]),
            }
        )
    return rows


def upgrade_rollback_status(root: Path) -> str:
    snapshot = root / "upgrade-snapshot.sqlite"
    current = root / "upgrade-current.sqlite"
    if not snapshot.is_file() or not current.is_file():
        return "NOT RUN"
    if snapshot_discards_later_rows(snapshot, current, "customers", ("id", "name")):
        return "FAIL"
    return "PASS"


def release_gate(root: Path, source_sha: str) -> tuple[int, dict]:
    if len(source_sha) != 40 or any(char not in "0123456789abcdef" for char in source_sha):
        report = {"release_pass": False, "error": "source_sha must be 40 lowercase hex characters"}
        return 1, report
    report = rollup(installer_rows(root, source_sha), REQUIRED_SCOPES)
    upgrade = upgrade_rollback_status(root)
    report["upgrade_rollback"] = upgrade
    report["scopes"]["upgrade-rollback"] = upgrade
    report["release_pass"] = all(report["scopes"].get(scope) == "PASS" for scope in REQUIRED_SCOPES)
    return (0 if report["release_pass"] else 1), report


def _self_check() -> int:
    declared = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "release_scope_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    if tuple(declared["required_scopes"]) != REQUIRED_SCOPES:
        print("required scopes drifted", file=sys.stderr)
        return 1
    missing = rollup([], REQUIRED_SCOPES)
    if missing["release_pass"] or missing["scopes"]["windows-installer"] != "NOT RUN":
        print("missing installer became a pass", file=sys.stderr)
        return 1
    blocked = rollup(
        [
            {
                "scope_id": "macos-installer",
                "platform": "macos",
                "kind": "installer",
                "status": "BLOCKED",
                "source_sha": "a" * 40,
                "artifact_sha256": "b" * 64,
            },
            {
                "scope_id": "windows-installer",
                "platform": "windows",
                "kind": "installer",
                "status": "PASS",
                "source_sha": "a" * 40,
                "artifact_sha256": "b" * 64,
            },
        ],
        REQUIRED_SCOPES,
    )
    reversed_rows = rollup(list(reversed(blocked["rows"])), REQUIRED_SCOPES)
    if blocked["release_pass"] or reversed_rows["scopes"] != blocked["scopes"]:
        print("blocked scope became a pass", file=sys.stderr)
        return 1
    code, _report = release_gate(Path("."), "NOT-A-SHA")
    if code == 0:
        print("bad source sha was accepted", file=sys.stderr)
        return 1
    print("release scope evidence self-check ok")
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
