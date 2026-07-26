#!/usr/bin/env python3
"""Cross-stack source governance ratchet.

The repository has legitimate historical oversized files. This gate grandfathers
their current size, but rejects:

* a new production source file above its stack soft cap;
* positive line growth in an already oversized file;
* positive route growth in an already oversized FastAPI router;
* growth in exact-copy debt outside declared generated/derived trees;
* any tracked file that is also ignored by Git.

Only Python's standard library is required, so the check can run before project
dependencies are installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT_DEFAULT = Path(__file__).resolve().parents[2]
BASELINE_REL = Path("config/source_governance_baseline.json")

ROUTE_PATTERN = re.compile(
    r"@(?:router|app)\.(?:get|post|put|delete|patch|websocket)\b",
    re.MULTILINE,
)
SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".vue", ".js", ".jsx", ".dart"}
MIRROR_SOURCE_EXTENSIONS = SOURCE_EXTENSIONS | {".css"}
TEST_DIRS = {"test", "tests", "__tests__", "test-fixtures", "fixtures"}
GENERATED_DIRS = {
    ".dart_tool",
    ".nuxt",
    ".output",
    ".vite",
    "build",
    "coverage",
    "dist",
    "generated",
    "htmlcov",
    "node_modules",
    "vendor",
}
TEST_NAME_MARKERS = (".test.", ".spec.", "_test.")
GENERATED_NAME_MARKERS = (".generated.", ".freezed.", ".g.dart")

# These are materialized build/export trees, not independent editing sources.
DUPLICATE_EXCLUDED_PREFIXES = (
    "FHD/XCAGI/mods/",
    "FHD/mods-admin-runtime/",
    "FHD/templates/",
)

# These retired recovery/runtime trees are not editing sources. Keep the
# generated workbench executions and transcript recovery snapshots outside Git.
# FHD/static may retain non-source binary assets, but not a second JS/CSS tree.
FORBIDDEN_SOURCE_MIRROR_PREFIXES = (
    "FHD/static/",
    "FHD/_recovered-",
    "FHD/_restored-from-transcript-",
    "成都修茈科技有限公司/MODstore_deploy/modstore_server/workbench_script_runs/",
)
FORBIDDEN_SOURCE_MIRROR_PATHS = ("FHD/scripts/dev/online_update_daemon.py",)


@dataclass(frozen=True)
class StackRule:
    name: str
    prefixes: tuple[str, ...]
    caps: dict[str, int]


STACK_RULES = (
    StackRule("fhd_backend", ("FHD/app/",), {".py": 800}),
    StackRule(
        "modstore_backend",
        ("成都修茈科技有限公司/MODstore_deploy/modstore_server/",),
        {".py": 800},
    ),
    StackRule(
        "fhd_vue",
        (
            "FHD/frontend/src/",
            "FHD/admin-console/src/",
            "FHD/sunbird-console/src/",
            "FHD/mods/",
        ),
        {".vue": 500, ".ts": 600, ".tsx": 600, ".js": 600, ".jsx": 600, ".py": 800},
    ),
    StackRule(
        "modstore_vue",
        ("成都修茈科技有限公司/MODstore_deploy/market/src/",),
        {".vue": 500, ".ts": 600, ".tsx": 600, ".js": 600, ".jsx": 600},
    ),
    StackRule(
        "electron",
        (
            "FHD/desktop/",
            "成都修茈科技有限公司/MODstore_deploy/desktop-shell/",
        ),
        {".ts": 600, ".tsx": 600, ".js": 600, ".jsx": 600},
    ),
    StackRule(
        "flutter",
        ("FHD/mobile-flutter-poc/lib/",),
        {".dart": 500},
    ),
)


def _git_paths(repo_root: Path, *args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args, "-z"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def _tracked_paths(repo_root: Path) -> list[str]:
    return _git_paths(repo_root, "ls-files")


def _ignored_tracked_paths(repo_root: Path) -> list[str]:
    return [
        rel
        for rel in _git_paths(repo_root, "ls-files", "-ci", "--exclude-standard")
        if (repo_root / rel).is_file()
    ]


def _is_excluded_source(rel: str) -> bool:
    parts = Path(rel).parts
    name = parts[-1].lower()
    lowered_parts = {part.lower() for part in parts[:-1]}
    if lowered_parts & (TEST_DIRS | GENERATED_DIRS):
        return True
    if any(marker in name for marker in GENERATED_NAME_MARKERS):
        return True
    return name.startswith("test_") or any(
        marker in name for marker in TEST_NAME_MARKERS
    )


def _stack_rule(rel: str) -> tuple[StackRule, int] | None:
    suffix = Path(rel).suffix.lower()
    if _is_excluded_source(rel):
        return None
    for rule in STACK_RULES:
        if suffix in rule.caps and any(
            rel.startswith(prefix) for prefix in rule.prefixes
        ):
            return rule, rule.caps[suffix]
    return None


def _read_source(path: Path) -> tuple[bytes, str, int] | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    text = raw.decode("utf-8", errors="replace")
    return raw, text, len(text.splitlines())


def _measure_sizes(
    repo_root: Path, tracked: list[str]
) -> tuple[list[dict], list[dict]]:
    oversized: list[dict] = []
    oversized_routes: list[dict] = []
    for rel in tracked:
        match = _stack_rule(rel)
        if match is None:
            continue
        rule, cap = match
        source = _read_source(repo_root / rel)
        if source is None:
            continue
        _, text, lines = source
        if lines > cap:
            oversized.append(
                {"file": rel, "stack": rule.name, "lines": lines, "soft_cap": cap}
            )
        if Path(rel).suffix.lower() == ".py":
            routes = len(ROUTE_PATTERN.findall(text))
            if routes > 20:
                oversized_routes.append(
                    {"file": rel, "stack": rule.name, "routes": routes, "soft_cap": 20}
                )
    oversized.sort(key=lambda item: (-item["lines"], item["file"]))
    oversized_routes.sort(key=lambda item: (-item["routes"], item["file"]))
    return oversized, oversized_routes


def _duplicate_candidates(repo_root: Path, tracked: list[str]) -> list[dict]:
    candidates: list[dict] = []
    for rel in tracked:
        if Path(rel).suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        if _is_excluded_source(rel):
            continue
        if any(rel.startswith(prefix) for prefix in DUPLICATE_EXCLUDED_PREFIXES):
            continue
        source = _read_source(repo_root / rel)
        if source is None:
            continue
        raw, _, lines = source
        if len(raw) < 500 and lines < 10:
            continue
        candidates.append(
            {
                "file": rel,
                "bytes": len(raw),
                "lines": lines,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return candidates


def _measure_duplicates(repo_root: Path, tracked: list[str]) -> tuple[dict, list[dict]]:
    by_hash: dict[str, list[dict]] = {}
    for item in _duplicate_candidates(repo_root, tracked):
        by_hash.setdefault(item["sha256"], []).append(item)

    groups: list[dict] = []
    for digest, items in by_hash.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda item: item["file"])
        copies = len(items) - 1
        groups.append(
            {
                "sha256": digest,
                "files": [item["file"] for item in items],
                "lines_each": items[0]["lines"],
                "bytes_each": items[0]["bytes"],
                "redundant_files": copies,
                "redundant_lines": copies * items[0]["lines"],
                "redundant_bytes": copies * items[0]["bytes"],
            }
        )
    groups.sort(key=lambda item: (-item["redundant_lines"], item["files"]))
    metrics = {
        "groups": len(groups),
        "redundant_files": sum(item["redundant_files"] for item in groups),
        "redundant_lines": sum(item["redundant_lines"] for item in groups),
        "redundant_bytes": sum(item["redundant_bytes"] for item in groups),
    }
    return metrics, groups


def _forbidden_source_mirrors(repo_root: Path, tracked: list[str]) -> list[str]:
    return sorted(
        rel
        for rel in tracked
        if (repo_root / rel).is_file()
        and Path(rel).suffix.lower() in MIRROR_SOURCE_EXTENSIONS
        and (
            rel in FORBIDDEN_SOURCE_MIRROR_PATHS
            or any(
                rel.startswith(prefix) for prefix in FORBIDDEN_SOURCE_MIRROR_PREFIXES
            )
        )
    )


def measure(repo_root: Path) -> dict:
    tracked = _tracked_paths(repo_root)
    oversized, oversized_routes = _measure_sizes(repo_root, tracked)
    duplicate_metrics, duplicate_groups = _measure_duplicates(repo_root, tracked)
    return {
        "oversized_files": oversized,
        "oversized_routers": oversized_routes,
        "duplicate_metrics": duplicate_metrics,
        "duplicate_groups": duplicate_groups,
        "forbidden_source_mirrors": _forbidden_source_mirrors(repo_root, tracked),
        "ignored_tracked_files": sorted(_ignored_tracked_paths(repo_root)),
    }


def load_baseline(repo_root: Path) -> dict | None:
    path = repo_root / BASELINE_REL
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def baseline_payload(current: dict) -> dict:
    return {
        "_note": (
            "Cross-stack source debt ratchet. Existing oversized files and exact-copy "
            "debt may only shrink; generated/derived roots are excluded."
        ),
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).date().isoformat(),
        "oversized_files": {
            item["file"]: {
                "stack": item["stack"],
                "lines": item["lines"],
                "soft_cap": item["soft_cap"],
            }
            for item in current["oversized_files"]
        },
        "oversized_routers": {
            item["file"]: {
                "stack": item["stack"],
                "routes": item["routes"],
                "soft_cap": item["soft_cap"],
            }
            for item in current["oversized_routers"]
        },
        "duplicate_metrics": current["duplicate_metrics"],
        "duplicate_excluded_prefixes": list(DUPLICATE_EXCLUDED_PREFIXES),
    }


def evaluate(current: dict, baseline: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    progress: list[str] = []
    file_limits = baseline.get("oversized_files", {})
    route_limits = baseline.get("oversized_routers", {})

    for item in current["oversized_files"]:
        old = file_limits.get(item["file"])
        if old is None:
            errors.append(
                f"new oversized {item['stack']} file: {item['file']} "
                f"({item['lines']} > {item['soft_cap']} lines)"
            )
        elif item["lines"] > old["lines"]:
            errors.append(
                f"oversized file grew: {item['file']} "
                f"({old['lines']} -> {item['lines']} lines)"
            )

    for item in current["oversized_routers"]:
        old = route_limits.get(item["file"])
        if old is None:
            errors.append(
                f"new oversized router: {item['file']} "
                f"({item['routes']} > {item['soft_cap']} routes)"
            )
        elif item["routes"] > old["routes"]:
            errors.append(
                f"oversized router grew: {item['file']} "
                f"({old['routes']} -> {item['routes']} routes)"
            )

    old_duplicates = baseline.get("duplicate_metrics", {})
    current_duplicates = current["duplicate_metrics"]
    for metric in ("groups", "redundant_files", "redundant_lines", "redundant_bytes"):
        old_value = int(old_duplicates.get(metric, 0))
        new_value = int(current_duplicates[metric])
        if new_value > old_value:
            errors.append(f"exact-copy debt grew: {metric} {old_value} -> {new_value}")
        elif new_value < old_value:
            progress.append(
                f"exact-copy debt reduced: {metric} {old_value} -> {new_value}"
            )

    if current["ignored_tracked_files"]:
        errors.append(
            "tracked files are also ignored by Git:\n"
            + "\n".join(
                f"    - {item}" for item in current["ignored_tracked_files"][:20]
            )
        )

    if current.get("forbidden_source_mirrors", []):
        errors.append(
            "retired source mirror contains tracked source files:\n"
            + "\n".join(
                f"    - {item}" for item in current["forbidden_source_mirrors"][:20]
            )
        )

    current_file_names = {item["file"] for item in current["oversized_files"]}
    removed_file_debt = sorted(set(file_limits) - current_file_names)
    if removed_file_debt:
        progress.append(
            f"oversized-file debt reduced by {len(removed_file_debt)} file(s)"
        )
    return errors, progress


def _summary(current: dict) -> dict:
    return {
        "oversized_files": len(current["oversized_files"]),
        "oversized_routers": len(current["oversized_routers"]),
        "duplicate_metrics": current["duplicate_metrics"],
        "forbidden_source_mirrors": len(current.get("forbidden_source_mirrors", [])),
        "ignored_tracked_files": len(current["ignored_tracked_files"]),
    }


def _print_top(current: dict, count: int) -> None:
    print(f"Top {count} oversized production files:")
    for item in current["oversized_files"][:count]:
        print(
            f"  {item['lines']:>6} lines  [{item['stack']}]  {item['file']} "
            f"(cap {item['soft_cap']})"
        )
    print(f"Top {count} exact-copy groups (derived trees excluded):")
    for item in current["duplicate_groups"][:count]:
        print(f"  {item['redundant_lines']:>6} redundant lines")
        for rel in item["files"]:
            print(f"         - {rel}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT_DEFAULT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--top", type=int, default=0, metavar="N")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()

    try:
        current = measure(repo_root)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"[source-governance] ERROR: measurement failed: {exc}", file=sys.stderr)
        return 2

    baseline = load_baseline(repo_root)
    if args.update_baseline:
        if baseline is not None and not args.force:
            errors, _ = evaluate(current, baseline)
            if errors:
                print(
                    "[source-governance] refusing to raise debt baseline; "
                    "fix violations or use --force",
                    file=sys.stderr,
                )
                return 2
        path = repo_root / BASELINE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(baseline_payload(current), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[source-governance] baseline written: {path.relative_to(repo_root)}")
        return 0

    if baseline is None:
        print(
            f"[source-governance] ERROR: missing baseline {BASELINE_REL}",
            file=sys.stderr,
        )
        return 2

    errors, progress = evaluate(current, baseline)
    payload = {
        "current": _summary(current),
        "errors": errors,
        "progress": progress,
        "ok": not errors,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"[source-governance] {json.dumps(_summary(current), ensure_ascii=False)}"
        )
        for item in progress:
            print(f"[source-governance] PROGRESS: {item}")
        if args.top > 0:
            _print_top(current, args.top)
        if errors:
            print(f"[source-governance] {len(errors)} VIOLATION(S)", file=sys.stderr)
            for item in errors:
                print(f"  - {item}", file=sys.stderr)
        else:
            print("[source-governance] OK — source debt did not grow")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
