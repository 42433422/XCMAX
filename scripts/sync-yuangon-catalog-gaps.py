#!/usr/bin/env python3
"""编制 vs yuangon YAML vs MODstore catalog 缺岗报告；可选触发 onboard。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DUTY_ROSTER = ROOT / "FHD" / "config" / "duty_roster.json"
YUANGON_DIR = ROOT / "成都修茈科技有限公司" / "yuangon"
ONBOARD_SCRIPT = (
    ROOT / "成都修茈科技有限公司" / "MODstore_deploy" / "modstore_server" / "scripts" / "onboard_yuangon_employees.py"
)
OUT = ROOT / ".cache" / "xcmax" / "xcmax-catalog-gap-report.json"
_BUILD = ROOT / "scripts" / "build-xcmax-tree-data.py"


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_xcmax_tree_data", _BUILD)
    if not spec or not spec.loader:
        raise RuntimeError("cannot load build-xcmax-tree-data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def planned_ids() -> set[str]:
    doc = json.loads(DUTY_ROSTER.read_text(encoding="utf-8"))
    ids: set[str] = set()
    for block in (doc.get("areas") or {}).values():
        for eid in block.get("ids") or []:
            ids.add(str(eid))
    return ids


def yaml_ids() -> set[str]:
    found: set[str] = set()
    if not YUANGON_DIR.is_dir():
        return found
    try:
        import yaml
    except ImportError:
        return found
    for f in YUANGON_DIR.glob("**/employee.yaml"):
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("id"):
            found.add(str(data["id"]))
    return found


def catalog_ids_via_db() -> tuple[set[str] | None, str | None]:
    modstore = ROOT / "成都修茈科技有限公司" / "MODstore_deploy"
    if not modstore.is_dir():
        return None, "MODstore_deploy missing"
    if str(modstore) not in sys.path:
        sys.path.insert(0, str(modstore))
    try:
        from modstore_server.models import CatalogItem, get_session_factory
    except Exception as exc:  # noqa: BLE001
        return None, f"DB unavailable: {exc}"
    try:
        sf = get_session_factory()
        with sf() as db:
            rows = db.query(CatalogItem.pkg_id).filter(CatalogItem.artifact == "employee_pack").all()
            return {str(r[0]) for r in rows if r[0]}, None
    except Exception as exc:  # noqa: BLE001
        return None, f"catalog query failed: {exc}"


def build_report(check_catalog: bool) -> dict[str, Any]:
    planned = planned_ids()
    on_disk = yaml_ids()
    report: dict[str, Any] = {
        "version": json.loads(DUTY_ROSTER.read_text(encoding="utf-8")).get("schema_version"),
        "planned_count": len(planned),
        "yaml_count": len(on_disk),
        "yaml_missing": sorted(planned - on_disk),
        "yaml_extra": sorted(on_disk - planned),
        "yaml_aligned": planned == on_disk,
    }
    if check_catalog:
        cat, err = catalog_ids_via_db()
        report["catalog_checked"] = cat is not None
        report["catalog_error"] = err
        if cat is not None:
            report["catalog_count"] = len(cat)
            report["catalog_missing"] = sorted(on_disk - cat)
            report["catalog_extra_sample"] = sorted(cat - on_disk)[:20]
            report["catalog_aligned"] = not report["catalog_missing"]
    else:
        report["catalog_checked"] = False
        report["catalog_missing"] = None
    report["onboard_command"] = (
        f"python3 {ONBOARD_SCRIPT} --repo-root {ROOT / '成都修茈科技有限公司'} "
        "--pkg-ids " + ",".join(report.get("catalog_missing") or []) if report.get("catalog_missing") else
        f"python3 {ONBOARD_SCRIPT} --repo-root {ROOT / '成都修茈科技有限公司'}"
    )
    return report


def run_onboard(pkg_ids: list[str], dry_run: bool) -> int:
    if not ONBOARD_SCRIPT.is_file():
        print(f"onboard script missing: {ONBOARD_SCRIPT}", file=sys.stderr)
        return 2
    cmd = [
        sys.executable,
        str(ONBOARD_SCRIPT),
        "--repo-root",
        str(ROOT / "成都修茈科技有限公司"),
    ]
    if dry_run:
        cmd.append("--dry-run")
    if pkg_ids:
        cmd.extend(["--pkg-ids", ",".join(pkg_ids)])
    return subprocess.call(cmd)


def main() -> int:
    parser = argparse.ArgumentParser(description="XCMAX yuangon catalog gap report")
    parser.add_argument("--check-catalog", action="store_true", help="Query MODstore DB for catalog gaps")
    parser.add_argument("--onboard", action="store_true", help="Run onboard script for catalog_missing")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to onboard")
    parser.add_argument("-o", "--output", type=Path, default=OUT)
    args = parser.parse_args()

    report = build_report(args.check_catalog)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWrote {args.output}", file=sys.stderr)

    if args.onboard:
        missing = report.get("catalog_missing") or []
        if not args.check_catalog:
            print("--onboard requires --check-catalog", file=sys.stderr)
            return 2
        if not missing:
            print("No catalog gaps to onboard.", file=sys.stderr)
            return 0
        return run_onboard(missing, args.dry_run)

    if not report["yaml_aligned"]:
        return 1
    if report.get("catalog_checked") and report.get("catalog_missing"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
