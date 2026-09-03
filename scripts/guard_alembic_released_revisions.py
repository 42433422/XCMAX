#!/usr/bin/env python3
"""CI guard: shipped Alembic revisions are immutable (ratchet).

Background (2026-09-03 desktop auto-update incident): a migration revision
(``2026_08_24_erp_hr_attendance``) that had already shipped to installed
desktop clients was later dropped from the tree. Every updated client failed
``alembic upgrade`` with ``Can't locate revision`` because its database
``alembic_version`` pointed at a revision the new package no longer contained.

For a product with desktop auto-update, a revision that has shipped is an
immutable contract: it may never be renamed, rewritten, or deleted. This
guard ratchets the set of known revision ids per live tree:

* ``--check`` (default, CI): every revision id in the baseline file must still
  exist in its tree. Missing id -> exit 1. Ids newly present in the tree but
  not yet in the baseline are reported as info (ship them, then record).
* ``--record``: add the tree's current revision ids to the baseline (union
  only — it can never "forget" a deleted revision, otherwise the ratchet
  would erase itself). Run after a release train ships new migrations.
* ``--record-force``: replace the baseline with exactly the current ids.
  Escape hatch for an intentional, explicit squash of the whole chain —
  pair it with a migration shim so already-installed databases keep
  resolving (see app/desktop_runtime/migrate.py repair logic).

Baseline: ``FHD/metrics/alembic_released_revisions.json`` (ratchet baselines
live alongside coverage/test-bloat baselines in FHD/metrics/).

Like ``guard_alembic_single_head.py`` this is intentionally dependency-free
(stdlib only) and parses revision ids out of version files without importing
Alembic or the app.

Run manually:  python3 scripts/guard_alembic_released_revisions.py [--record]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Keep in sync with scripts/guard_alembic_single_head.py LIVE_TREES.
LIVE_TREES = (
    "FHD/alembic/versions",
    "成都修茈科技有限公司/MODstore_deploy/alembic/versions",
)

BASELINE_PATH = REPO_ROOT / "FHD/metrics/alembic_released_revisions.json"

_REV = re.compile(
    r"^revision(?:\s*:\s*[\w\[\]| ]+)?\s*[:=]\s*['\"]([^'\"]+)['\"]", re.MULTILINE
)


def _scan_tree(tree: str) -> dict[str, str]:
    """Return {revision_id: defining file} for one live versions tree."""
    found: dict[str, str] = {}
    for path in sorted((REPO_ROOT / tree).glob("*.py")):
        for match in _REV.finditer(path.read_text(encoding="utf-8")):
            found[match.group(1).strip()] = path.name
    return found


def _load_baseline() -> dict[str, list[str]]:
    if not BASELINE_PATH.is_file():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _save_baseline(baseline: dict[str, list[str]]) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    serialized = {tree: sorted(ids) for tree, ids in sorted(baseline.items())}
    BASELINE_PATH.write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--record", action="store_true", help="union current ids into baseline")
    mode.add_argument(
        "--record-force", action="store_true", help="replace baseline with current ids"
    )
    args = parser.parse_args()

    baseline = _load_baseline()
    if args.record_force:
        baseline = {}
        for tree in LIVE_TREES:
            baseline[tree] = sorted(_scan_tree(tree))
        _save_baseline(baseline)
        print(f"baseline replaced: {BASELINE_PATH.relative_to(REPO_ROOT)}")
        return 0

    failures: list[str] = []
    for tree in LIVE_TREES:
        current = _scan_tree(tree)
        known = set(baseline.get(tree, []))
        missing = sorted(known - set(current))
        if missing:
            failures.append(
                f"{tree}: baseline revisions deleted from chain: {', '.join(missing)}"
            )
        added = sorted(set(current) - known)
        if added:
            print(
                f"info: {tree}: {len(added)} revision(s) not yet in baseline "
                f"(record after shipping): {', '.join(added)}"
            )
        if args.record and added:
            baseline[tree] = sorted(known | set(current))
            _save_baseline(baseline)
            print(f"baseline updated: {tree} -> {len(baseline[tree])} revision(s)")
            added = []

    if failures:
        for line in failures:
            print(f"FAIL {line}", file=sys.stderr)
        print(
            "Shipped alembic revisions are an immutable contract for desktop "
            "auto-update clients. Restore the deleted revision file(s); for an "
            "intentional squash use a shim revision plus --record-force.",
            file=sys.stderr,
        )
        return 1
    if not args.record:
        print("alembic released-revision ratchet: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
