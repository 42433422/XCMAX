#!/usr/bin/env python3
"""Resolve exact-main Mod sources and require a real release version change."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any

ROOTS = ("FHD/mods/_employees", "FHD/mods", "FHD/XCAGI/mods")


def run(root: Path, *command: str) -> str:
    return subprocess.run(
        command, cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def version(value: Any) -> tuple[int, ...]:
    value = str(value or "")
    if not re.fullmatch(
        r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*))?", value
    ):
        raise ValueError(
            "automatic releases require a three/four-part numeric stable manifest.version"
        )
    parts = tuple(map(int, value.split(".")))
    return parts + (0,) * (4 - len(parts))


def source_root(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if ".." in parts:
        return None
    for prefix in ROOTS:
        base = PurePosixPath(prefix).parts
        if parts[: len(base)] == base and len(parts) > len(base) + 1:
            mod_id = parts[len(base)]
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", mod_id):
                return f"{prefix}/{mod_id}"
    return None


def discover(root: Path, source_sha: str, mod_id: str = "") -> list[dict[str, str]]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source_sha must be an exact 40-character lowercase SHA")
    if run(root, "git", "rev-parse", "HEAD") != source_sha:
        raise ValueError("checkout HEAD does not match source_sha")
    run(root, "git", "merge-base", "--is-ancestor", source_sha, "refs/remotes/origin/main")
    parent = run(root, "git", "rev-parse", f"{source_sha}^1")
    paths = run(root, "git", "diff", "--name-only", parent, source_sha).splitlines()
    sources = {candidate for path in paths if (candidate := source_root(path))}
    if mod_id:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", mod_id):
            raise ValueError("invalid mod_id")
        sources = {
            f"{prefix}/{mod_id}"
            for prefix in ROOTS
            if (root / prefix / mod_id / "manifest.json").is_file()
        }
        if not sources:
            raise ValueError("requested mod_id has no source manifest")
    result: dict[str, dict[str, str]] = {}
    for source in sorted(sources):
        path = root / source / "manifest.json"
        if not path.is_file():
            continue  # Deleted packages cannot be published.
        manifest = json.loads(path.read_text())
        pkg_id = manifest.get("id")
        if pkg_id != Path(source).name:
            raise ValueError(f"manifest.id does not match source directory: {source}")
        current = version(manifest.get("version"))
        previous = subprocess.run(
            ["git", "show", f"{parent}:{source}/manifest.json"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        changed = any(source_root(path) == source for path in paths)
        if previous.returncode == 0 and changed:
            old = json.loads(previous.stdout)
            if current <= version(old.get("version")):
                raise ValueError(
                    f"{pkg_id}: source changed without a strictly higher manifest.version; bump the version before publication"
                )
        # Do not publish an updated mirror while the canonical host source is
        # still stale. This also avoids two packages sharing one id/version.
        canonical = next(
            f"{prefix}/{pkg_id}"
            for prefix in ROOTS
            if (root / prefix / pkg_id / "manifest.json").is_file()
        )
        if canonical != source:
            canonical_manifest = json.loads((root / canonical / "manifest.json").read_text())
            if canonical_manifest.get("version") != manifest.get("version") or (
                changed and canonical not in sources
            ):
                raise ValueError(
                    f"{pkg_id}: changed mirror and canonical source disagree; synchronize {canonical}"
                )
        rank = next(i for i, prefix in enumerate(ROOTS) if source == f"{prefix}/{pkg_id}")
        old_row = result.get(pkg_id)
        if old_row is None or rank < int(old_row["rank"]):
            result[pkg_id] = {
                "id": pkg_id,
                "source": source,
                "version": manifest["version"],
                "rank": str(rank),
            }
    return [
        {key: value for key, value in row.items() if key != "rank"}
        for _, row in sorted(result.items())
    ]


def verify_required_checks(
    protection: dict, pages: list[dict], statuses: list[list[dict]], source_sha: str
) -> None:
    required = {(name, None) for name in protection.get("contexts", [])}
    required.update((row["context"], row.get("app_id")) for row in protection.get("checks", []))
    if not required:
        raise ValueError("main has no readable required checks; refusing publication")
    checks = [
        row
        for page in pages
        for row in page.get("check_runs", [])
        if row.get("head_sha") == source_sha
    ]
    commits = [row for page in statuses for row in page]
    for name, app_id in required:
        found = [
            row
            for row in checks
            if row.get("name") == name
            and (app_id is None or (row.get("app") or {}).get("id") == app_id)
        ]
        found.sort(key=lambda row: int(row.get("id") or 0))
        states = [row for row in commits if row.get("context") == name]
        states.sort(key=lambda row: int(row.get("id") or 0))
        if found:
            good = (
                found[-1].get("status") == "completed" and found[-1].get("conclusion") == "success"
            )
        else:
            good = app_id is None and bool(states) and states[-1].get("state") == "success"
        if not good:
            raise ValueError(f"required check is not successful at source_sha: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--mod-id", default="")
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(run(Path.cwd(), "git", "rev-parse", "--show-toplevel"))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        raise ValueError("invalid repository")
    rows = discover(root, args.source_sha, args.mod_id)
    prefix = f"repos/{args.repository}"
    protection = json.loads(
        run(root, "gh", "api", f"{prefix}/branches/main/protection/required_status_checks")
    )
    deadline = time.monotonic() + min(max(args.wait_seconds, 0), 1800)
    while True:
        pages = json.loads(
            run(
                root,
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"{prefix}/commits/{args.source_sha}/check-runs?per_page=100",
            )
        )
        statuses = json.loads(
            run(
                root,
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"{prefix}/commits/{args.source_sha}/statuses?per_page=100",
            )
        )
        try:
            verify_required_checks(protection, pages, statuses, args.source_sha)
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(30, max(0, deadline - time.monotonic())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"source_sha": args.source_sha, "include": rows}, indent=2) + "\n"
    )
    print(json.dumps({"include": rows}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
