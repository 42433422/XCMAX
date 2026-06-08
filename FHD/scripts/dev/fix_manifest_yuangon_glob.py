#!/usr/bin/env python3
"""给所有员工包 manifest 补充 yuangon mirror glob，对齐 fhd-core-maintainer 模式。

运行：python FHD/scripts/dev/fix_manifest_yuangon_glob.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EMP_ROOT = REPO / "FHD" / "mods" / "_employees"


def fix_all(dry_run: bool = False) -> None:
    fixed = skipped = already_ok = 0
    for d in sorted(EMP_ROOT.iterdir()):
        if not d.is_dir():
            continue
        mf_path = d / "manifest.json"
        if not mf_path.exists():
            continue
        try:
            mf = json.loads(mf_path.read_text())
        except Exception as e:
            print(f"WARN: skip {d.name} – {e}")
            skipped += 1
            continue

        pkg_id = mf.get("id", d.name)
        v2 = mf.get("employee_config_v2", {})
        identity = v2.get("identity", {})
        area = identity.get("area", "")
        if not area:
            skipped += 1
            continue

        expected_mirror = f"yuangon/{area}/{pkg_id}/**"
        wp = v2.setdefault("workspace_policy", {})
        scope_globs: list = wp.setdefault("scope_globs", [])

        has_mirror = expected_mirror in scope_globs or any(
            "yuangon" in g and pkg_id in g for g in scope_globs
        )
        if has_mirror:
            already_ok += 1
            continue

        scope_globs.append(expected_mirror)
        if dry_run:
            print(f"[DRY-RUN] {pkg_id}: append {expected_mirror}")
            fixed += 1
            continue

        mf_path.write_text(json.dumps(mf, ensure_ascii=False, indent=2) + "\n")
        print(f"  fixed {pkg_id}: +{expected_mirror}")
        fixed += 1

    print(f"\nDone: fixed={fixed} already_ok={already_ok} skipped={skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fix_all(dry_run=args.dry_run)
