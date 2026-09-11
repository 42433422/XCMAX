"""Select mutation checks using Git's repository-relative paths, failing on Git errors."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

PREFIXES = (
    "FHD/app/di/",
    "FHD/app/contexts/",
    "FHD/tests/test_di/",
    "FHD/tests/test_contexts/",
)
FILES = frozenset(
    {
        "FHD/pyproject.toml",
        "FHD/scripts/dev/mutation_kill_report.py",
        "FHD/scripts/dev/mutation_isolated.py",
        "FHD/tests/test_scripts/test_mutation_isolated.py",
        "FHD/scripts/ci/mutation_scope.py",
        "FHD/tests/test_scripts/test_mutation_kill_report.py",
        "FHD/tests/test_scripts/test_mutation_scope.py",
        "FHD/.github/workflows/mutation-smoke.yml",
        ".github/workflows/fhd-mutation-smoke.yml",
    }
)


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    """A first push has no base; inspect its root commit instead of silently skipping."""
    if not head or head.startswith("-") or base.startswith("-"):
        raise ValueError("explicit commit revisions are required")
    command = ["git", "-C", str(root)]
    if not base or set(base) == {"0"}:
        command += ["ls-tree", "--name-only", "-r", "-z", head]
    else:
        command += ["diff", "--name-only", "-z", base, head, "--"]
    result = subprocess.run(command, check=True, capture_output=True)
    return [
        name.decode("utf-8", errors="surrogateescape")
        for name in result.stdout.split(b"\0")
        if name
    ]


def requires_mutation(paths: list[str]) -> bool:
    return any(name in FILES or name.startswith(PREFIXES) for name in paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event", required=True, choices=("pull_request", "push", "schedule", "workflow_dispatch")
    )
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="")
    args = parser.parse_args()
    if args.event in {"schedule", "workflow_dispatch"}:
        run = True
        reason = "full_run"
    else:
        if args.event == "pull_request" and not args.base:
            parser.error("pull requests require a base revision")
        root = Path(__file__).resolve().parents[3]
        paths = changed_paths(root, args.base, args.head)
        run = requires_mutation(paths)
        reason = "scope_changed" if run else "no_scope_changes"
    print(f"run_mutation={str(run).lower()}")
    print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
