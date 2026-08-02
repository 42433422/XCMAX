#!/usr/bin/env python3
"""Ratchet: frontend *.coverage.test.ts stub files (baseline only moves down)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = FHD_ROOT / "frontend" / "src"
BASELINE_PATH = FHD_ROOT / "metrics" / "frontend_coverage_stubs_baseline.json"


def count_stubs() -> list[str]:
    files = sorted(FRONTEND_SRC.rglob("*.coverage.test.ts"))
    return [str(p.relative_to(FHD_ROOT)).replace("\\", "/") for p in files]


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check",
        action="store_true",
        help="Fail if *.coverage.test.ts count exceeds the baseline",
    )
    group.add_argument(
        "--bump",
        action="store_true",
        help="Update baseline (only when the count decreased)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    files = count_stubs()
    count = len(files)
    baseline_data = load_baseline()
    baseline = int(baseline_data["coverage_test_files"])

    if args.verbose:
        for rel in files:
            print(rel)
        print(f"TOTAL {count}")

    print(f"frontend_coverage_stubs={count} baseline={baseline}")

    if args.check:
        if count > baseline:
            print(
                f"FAIL: +{count - baseline} new *.coverage.test.ts stub files "
                f"(baseline {baseline}); write real assertions instead",
                file=sys.stderr,
            )
            return 1
        print("OK: within baseline")
        return 0

    # --bump: ratchet only moves down
    if count >= baseline:
        print(
            f"REFUSE: count {count} >= baseline {baseline}; ratchet only moves down",
            file=sys.stderr,
        )
        return 1
    baseline_data["coverage_test_files"] = count
    baseline_data["updated"] = date.today().isoformat()
    BASELINE_PATH.write_text(
        json.dumps(baseline_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"OK: baseline bumped {baseline} -> {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
