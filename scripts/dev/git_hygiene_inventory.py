#!/usr/bin/env python3
"""Build a Git hygiene inventory for the XCMAX monorepo.

The report is intentionally read-only: it classifies branches and working-tree
noise so feature-bearing branches can be preserved and merged deliberately.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


ROOT_MARKERS = (".git", "FHD", "packages")


def run_git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def repo_root(cwd: Path) -> Path:
    root = Path(run_git(["rev-parse", "--show-toplevel"], cwd).strip())
    missing = [name for name in ROOT_MARKERS if not (root / name).exists()]
    if missing:
        raise SystemExit(f"{root} does not look like XCMAX; missing {missing}")
    return root


def parse_worktrees(root: Path) -> dict[str, dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in run_git(["worktree", "list", "--porcelain"], root).splitlines():
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    if current:
        records.append(current)

    by_branch: dict[str, dict[str, str]] = {}
    for item in records:
        branch_ref = item.get("branch", "")
        if not branch_ref.startswith("refs/heads/"):
            continue
        branch = branch_ref.removeprefix("refs/heads/")
        path = item["worktree"]
        status = run_git(["status", "--porcelain"], Path(path))
        by_branch[branch] = {
            "path": path,
            "dirty": "yes" if status.strip() else "no",
            "dirty_count": str(len(status.splitlines())),
        }
    return by_branch


def worktree_dirty_details(root: Path) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for branch, item in parse_worktrees(root).items():
        status = run_git(["status", "--porcelain"], Path(item["path"]))
        if not status.strip():
            continue
        files: list[dict[str, str]] = []
        for line in status.splitlines():
            path = line[3:] if len(line) > 3 else line
            files.append(
                {
                    "status": line[:2].strip() or "?",
                    "path": path,
                    "module": module_for_path(path),
                    "runtime": "yes" if looks_like_dirty_runtime(path) else "no",
                }
            )
        details.append(
            {
                "branch": branch,
                "path": item["path"],
                "dirty_count": len(files),
                "runtime_count": sum(1 for file in files if file["runtime"] == "yes"),
                "modules": Counter(file["module"] for file in files),
                "sample": files[:12],
            }
        )
    details.sort(key=lambda item: int(item["dirty_count"]), reverse=True)
    return details


def module_for_path(path: str) -> str:
    if path.startswith("packages/retort_engine/.retort/") or path.startswith(".retort/"):
        return "runtime-retort"
    if path.startswith("packages/retort_engine/"):
        return "retort-engine"
    if path.startswith("FHD/mobile-android/"):
        return "fhd-mobile-android"
    if path.startswith("FHD/mobile-ios/"):
        return "fhd-mobile-ios"
    if path.startswith("FHD/mobile-harmony/"):
        return "fhd-mobile-harmony"
    if path.startswith("FHD/frontend/"):
        return "fhd-frontend"
    if path.startswith("FHD/app/"):
        return "fhd-backend"
    if path.startswith("FHD/"):
        return "fhd-other"
    if path.startswith("成都修茈科技有限公司/MODstore_deploy/"):
        return "modstore-deploy"
    if path.startswith("成都修茈科技有限公司/yuangon/"):
        return "yuangon"
    if path.startswith("成都修茈科技有限公司/deploy/") or path.endswith(".conf"):
        return "deploy-nginx"
    if path.startswith(".github/"):
        return "ci"
    if path.startswith("docs/") or "/docs/" in path:
        return "docs"
    return path.split("/", 1)[0] if "/" in path else "root"


def looks_like_dirty_runtime(path: str) -> bool:
    runtime_prefixes = (
        ".retort/",
        ".pytest_cache/",
        "playwright-report/",
        "packages/retort_engine/.retort/",
    )
    runtime_suffixes = (
        ".sqlite",
        ".sqlite3",
        ".db",
        ".db)",
        ".db-shm",
        ".db-wal",
        ".jsonl",
        ".log",
        ".tmp",
    )
    basename = os.path.basename(path)
    return (
        path.startswith(runtime_prefixes)
        or path.endswith(runtime_suffixes)
        or basename.startswith("debug_")
        or basename.startswith("verify_")
        or basename in {"test_results.json"}
    )


def looks_like_tracked_runtime(path: str) -> bool:
    """High-confidence tracked runtime artifacts.

    This intentionally does not flag every debug/verify script or jsonl dataset:
    many of those are useful source assets in this repo.
    """

    if path.startswith(("packages/retort_engine/.retort/", ".retort/")):
        return True
    if path.startswith((".hvigor/outputs/", ".pytest_cache/", "playwright-report/")):
        return True
    if path.endswith((".db-shm", ".db-wal", ".sqlite", ".sqlite3")):
        return True
    if path.endswith(".db") or path.endswith(".db)"):
        seed_allowlist = (
            "FHD/delivery/sunbird-seed/",
            "成都修茈科技有限公司/MODstore_deploy/modstore_server/data/",
        )
        return not path.startswith(seed_allowlist)
    if path.endswith((".jsonl", ".log")):
        return path.startswith(("packages/retort_engine/.retort/", ".retort/", ".hvigor/outputs/"))
    return False


@dataclass
class BranchRow:
    name: str
    ahead: int
    behind: int
    changed_files: int
    modules: str
    kind: str
    active: str
    dirty: str
    last_commit: str
    strategy: str


def classify_branch(name: str, ahead: int, changed: list[str], dirty: str) -> tuple[str, str]:
    modules = Counter(module_for_path(path) for path in changed)
    runtime_only = bool(changed) and all(looks_like_tracked_runtime(path) for path in changed)
    mostly_retort = bool(changed) and sum(
        count for module, count in modules.items() if module in {"retort-engine", "runtime-retort"}
    ) >= max(1, int(len(changed) * 0.75))

    if ahead == 0:
        return "already-contained", "do-not-merge"
    if dirty == "yes":
        return "active-dirty-feature", "preserve; split local edits first"
    if runtime_only:
        return "runtime-artifact-only", "do not merge; ignore or untrack artifacts"
    if name.startswith("retort/absorb") and mostly_retort:
        return "retort-feature-candidate", "intake by cherry-pick/squash after Retort review"
    if name.startswith("devfleet/codex/"):
        return "agent-feature-candidate", "inspect and cherry-pick useful commits"
    if ahead <= 5 and len(changed) <= 60:
        return "small-feature-candidate", "candidate for direct review/cherry-pick"
    return "large-feature-candidate", "needs branch-level intake, likely squash/cherry-pick"


def branch_rows(root: Path, main_ref: str, limit: int | None) -> list[BranchRow]:
    worktrees = parse_worktrees(root)
    rows: list[BranchRow] = []
    refs = run_git(
        [
            "for-each-ref",
            "refs/heads",
            "--format=%(refname:short)|%(committerdate:iso8601)|%(objectname:short)|%(subject)",
        ],
        root,
    )
    for line in refs.splitlines():
        name, _date, commit, subject = line.split("|", 3)
        counts = run_git(["rev-list", "--left-right", "--count", f"{main_ref}...{name}"], root).split()
        behind = int(counts[0])
        ahead = int(counts[1])
        changed = run_git(["diff", "--name-only", f"{main_ref}...{name}"], root).splitlines()
        modules_counter = Counter(module_for_path(path) for path in changed)
        modules = ", ".join(f"{name}:{count}" for name, count in modules_counter.most_common(4))
        wt = worktrees.get(name, {})
        active = wt.get("path", "")
        dirty = wt.get("dirty", "no")
        kind, strategy = classify_branch(name, ahead, changed, dirty)
        rows.append(
            BranchRow(
                name=name,
                ahead=ahead,
                behind=behind,
                changed_files=len(changed),
                modules=modules or "-",
                kind=kind,
                active=active,
                dirty=dirty,
                last_commit=f"{commit} {subject}",
                strategy=strategy,
            )
        )

    rows.sort(key=lambda row: (row.ahead == 0, -row.ahead, -row.changed_files, row.name))
    return rows[:limit] if limit else rows


def dirty_inventory(root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in run_git(["status", "--porcelain"], root).splitlines():
        status = line[:2].strip() or "?"
        path = line[3:] if len(line) > 3 else line
        rows.append(
            {
                "status": status,
                "path": path,
                "module": module_for_path(path),
                "runtime": "yes" if looks_like_dirty_runtime(path) else "no",
            }
        )
    return rows


def tracked_runtime_candidates(root: Path) -> list[str]:
    candidates = []
    for path in run_git(["ls-files"], root).splitlines():
        if looks_like_tracked_runtime(path):
            candidates.append(path)
    return candidates


def render_markdown(root: Path, main_ref: str, rows: list[BranchRow], dirty: list[dict[str, str]]) -> str:
    generated = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    feature_rows = [row for row in rows if row.ahead > 0]
    tracked_runtime = tracked_runtime_candidates(root)
    dirty_worktrees = worktree_dirty_details(root)
    dirty_modules = Counter(item["module"] for item in dirty)
    runtime_dirty = [item for item in dirty if item["runtime"] == "yes"]

    out: list[str] = []
    out.append("# Git Hygiene Intake Report")
    out.append("")
    out.append(f"- Generated: {generated}")
    out.append(f"- Repository: `{root}`")
    out.append(f"- Baseline: `{main_ref}`")
    out.append(f"- Branches listed: {len(rows)}")
    out.append(f"- Feature-bearing branches in this report: {len(feature_rows)}")
    out.append(f"- Active dirty branch worktrees detected: {len(dirty_worktrees)}")
    out.append(f"- Dirty files in report-generation worktree: {len(dirty)}")
    out.append(f"- Dirty files in report-generation worktree classified as runtime/test artifacts: {len(runtime_dirty)}")
    out.append(f"- High-confidence tracked runtime candidates: {len(tracked_runtime)}")
    out.append("")
    out.append("## Policy")
    out.append("")
    out.append("- Do not delete feature-bearing branches during cleanup.")
    out.append("- Do not merge long branches directly into `main`; intake by small reviewed commits.")
    out.append("- Runtime artifacts must be ignored or untracked before branch integration resumes.")
    out.append("- Dirty active worktrees must be split by module before any merge attempt.")
    out.append("")
    out.append("## Dirty Worktree Modules")
    out.append("")
    out.append("| module | files |")
    out.append("| --- | ---: |")
    for module, count in dirty_modules.most_common():
        out.append(f"| `{module}` | {count} |")
    out.append("")
    out.append("## Active Dirty Worktrees")
    out.append("")
    if dirty_worktrees:
        out.append("| branch | dirty files | runtime-like | top modules | path | sample |")
        out.append("| --- | ---: | ---: | --- | --- | --- |")
        for item in dirty_worktrees:
            modules = item["modules"]
            assert isinstance(modules, Counter)
            sample_items = item["sample"]
            assert isinstance(sample_items, list)
            top_modules = ", ".join(f"{module}:{count}" for module, count in modules.most_common(4))
            sample = "<br>".join(f"`{file['path']}`" for file in sample_items[:6])
            out.append(
                f"| `{item['branch']}` | {item['dirty_count']} | {item['runtime_count']} | "
                f"{top_modules} | `{item['path']}` | {sample} |"
            )
    else:
        out.append("- None detected.")
    out.append("")
    out.append("## High-Confidence Tracked Runtime Candidates")
    out.append("")
    if tracked_runtime:
        for path in tracked_runtime[:80]:
            out.append(f"- `{path}`")
        if len(tracked_runtime) > 80:
            out.append(f"- ... {len(tracked_runtime) - 80} more")
    else:
        out.append("- None detected.")
    out.append("")
    out.append("## Branch Intake Queue")
    out.append("")
    out.append(
        "| branch | ahead | behind | files | kind | modules | dirty | strategy | last commit |"
    )
    out.append("| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |")
    for row in rows:
        out.append(
            "| "
            + " | ".join(
                [
                    f"`{row.name}`",
                    str(row.ahead),
                    str(row.behind),
                    str(row.changed_files),
                    row.kind,
                    row.modules.replace("|", "/"),
                    row.dirty,
                    row.strategy.replace("|", "/"),
                    row.last_commit.replace("|", "/"),
                ]
            )
            + " |"
        )
    out.append("")
    out.append("## Next Actions")
    out.append("")
    out.append("1. Move tracked runtime candidates out of source control with a dedicated cleanup commit.")
    out.append("2. Split dirty active worktrees by module before branch intake.")
    out.append("3. Promote small feature candidates into an integration branch using cherry-pick or squash.")
    out.append("4. Keep large Retort absorption branches as source material until reviewed.")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-ref", default="main")
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    args = parser.parse_args()

    root = repo_root(Path.cwd())
    rows = branch_rows(root, args.main_ref, args.limit)
    dirty = dirty_inventory(root)
    markdown = render_markdown(root, args.main_ref, rows, dirty)

    if args.json_out:
        payload = {
            "main_ref": args.main_ref,
            "branches": [row.__dict__ for row in rows],
            "dirty": dirty,
            "tracked_runtime_candidates": tracked_runtime_candidates(root),
        }
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if args.markdown_out:
        args.markdown_out.write_text(markdown + "\n")
    if not args.json_out and not args.markdown_out:
        print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
