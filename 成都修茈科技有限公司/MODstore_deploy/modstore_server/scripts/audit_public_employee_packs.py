#!/usr/bin/env python3
"""批量检测公开市场表格类员工包：craft validate + 六维，可选修复 catalog 元数据。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

from modman.manifest_util import read_manifest  # noqa: E402
from modstore_server.catalog_quality import (  # noqa: E402
    PUBLIC_TABULAR_PKG_IDS,
    VALID_COMPLIANCE_STATUSES,
    build_employee_quality_report,
    build_quality_snapshot_payload,
    canonical_display_name,
    resolve_employee_pack_dir,
)


async def audit_one(
    pkg_id: str,
    *,
    brief: str = "",
) -> Dict[str, Any]:
    pack_dir = resolve_employee_pack_dir(pkg_id)
    if not pack_dir:
        return {
            "pkg_id": pkg_id,
            "ok": False,
            "pack_dir": None,
            "errors": [f"未找到库目录: {pkg_id}"],
            "warnings": [],
            "six_overall": None,
            "gate_passed": False,
            "report": None,
        }
    mf, _ = read_manifest(pack_dir)
    manifest = mf if isinstance(mf, dict) else {}
    use_brief = brief or str(manifest.get("description") or "")
    report = await build_employee_quality_report(
        pack_dir=pack_dir,
        brief=use_brief,
        catalog_registered=True,
    )
    six = report.get("six_dimension") if isinstance(report.get("six_dimension"), dict) else {}
    gate = report.get("gate") if isinstance(report.get("gate"), dict) else {}
    return {
        "pkg_id": pkg_id,
        "ok": bool(report.get("ok")),
        "pack_dir": str(pack_dir),
        "manifest_name": str(manifest.get("name") or ""),
        "canonical_name": canonical_display_name(pkg_id, manifest),
        "errors": list(report.get("validate_errors") or []),
        "warnings": list(report.get("validate_warnings") or []),
        "six_overall": six.get("overall_score"),
        "six_grade": six.get("overall_grade"),
        "gate_passed": bool(gate.get("passed")),
        "report": report,
    }


def _apply_fix(row: Any, result: Dict[str, Any], *, write_cache: bool) -> List[str]:
    changes: List[str] = []
    pkg_id = str(row.pkg_id or "")
    report = result.get("report")
    if not isinstance(report, dict):
        return changes

    canon = str(result.get("canonical_name") or "").strip()
    if canon and str(row.name or "").strip() != canon:
        changes.append(f"name: {row.name!r} -> {canon!r}")
        row.name = canon[:256]

    manifest_desc = ""
    pack_dir = resolve_employee_pack_dir(pkg_id)
    if pack_dir:
        mf, _ = read_manifest(pack_dir)
        if isinstance(mf, dict):
            manifest_desc = str(mf.get("description") or "").strip()

    db_desc = str(row.description or "").strip()
    if manifest_desc and (not db_desc or db_desc != manifest_desc):
        if len(manifest_desc) > 20 or not db_desc:
            changes.append("description: updated from manifest")
            row.description = manifest_desc[:2000]

    status = str(row.compliance_status or "").strip()
    if status not in VALID_COMPLIANCE_STATUSES:
        changes.append(f"compliance_status: {status!r} -> approved")
        row.compliance_status = "approved"

    if str(getattr(row, "security_level", "") or "").strip() != "enterprise":
        changes.append(f"security_level: {row.security_level!r} -> enterprise")
        row.security_level = "enterprise"
    if str(getattr(row, "license_scope", "") or "").strip() != "enterprise":
        changes.append(f"license_scope: {getattr(row, 'license_scope', '')!r} -> enterprise")
        row.license_scope = "enterprise"

    if write_cache:
        six = report.get("six_dimension")
        if isinstance(six, dict) and pack_dir:
            snap = build_quality_snapshot_payload(
                validate_errors=list(report.get("validate_errors") or []),
                validate_warnings=list(report.get("validate_warnings") or []),
                six_dimension=six,
                gate=dict(report.get("gate") or {}),
                pack_dir=pack_dir,
                pipeline_label=str(report.get("pipeline_label") or ""),
            )
            row.graph_snapshot = json.dumps(snap, ensure_ascii=False)
            changes.append("graph_snapshot: quality_report written")

    return changes


async def main_async(args: argparse.Namespace) -> int:
    from modstore_server.models import CatalogItem, get_session_factory

    pkg_ids: List[str] = []
    if args.all_public_tabular:
        pkg_ids.extend(PUBLIC_TABULAR_PKG_IDS)
    for pid in args.pkg_id or []:
        if pid.strip() and pid.strip() not in pkg_ids:
            pkg_ids.append(pid.strip())

    if not pkg_ids:
        print("No pkg_id specified. Use --all-public-tabular or --pkg-id", file=sys.stderr)
        return 2

    sf = get_session_factory()
    results: List[Dict[str, Any]] = []
    for pid in pkg_ids:
        brief = ""
        with sf() as db:
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pid).first()
            if row:
                brief = str(row.description or "")
        res = await audit_one(pid, brief=brief)
        results.append(res)

    print(
        f"\n{'pkg_id':<28} {'overall':>7} {'grade':>5} {'gate':>5} {'errs':>4} {'warns':>5}  name"
    )
    print("-" * 90)
    fail_count = 0
    for r in results:
        errs = len(r.get("errors") or [])
        warns = len(r.get("warnings") or [])
        if errs:
            fail_count += 1
        gate = "PASS" if r.get("gate_passed") else "FAIL"
        print(
            f"{r['pkg_id']:<28} "
            f"{str(r.get('six_overall') or '-'):>7} "
            f"{str(r.get('six_grade') or '-'):>5} "
            f"{gate:>5} "
            f"{errs:>4} "
            f"{warns:>5}  "
            f"{r.get('canonical_name') or ''}"
        )
        for e in (r.get("errors") or [])[:3]:
            print(f"    ERR: {e}")

    if args.fix or args.write_cache:
        with sf() as db:
            for r in results:
                row = db.query(CatalogItem).filter(CatalogItem.pkg_id == r["pkg_id"]).first()
                if not row:
                    print(f"[WARN] no catalog row for {r['pkg_id']}")
                    continue
                ch = _apply_fix(row, r, write_cache=bool(args.write_cache or args.fix))
                if ch:
                    print(f"[FIX] {r['pkg_id']}: " + "; ".join(ch))
            db.commit()
        print("catalog fixes committed.")

    print(f"\nSummary: {len(results)} packs, {fail_count} with validate errors")
    return 0 if fail_count == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit public tabular employee packs")
    parser.add_argument("--pkg-id", action="append", default=[], help="指定 pkg_id，可重复")
    parser.add_argument("--all-public-tabular", action="store_true", help="审计 8 个公开表格员工包")
    parser.add_argument("--fix", action="store_true", help="修复 catalog name/compliance 等")
    parser.add_argument("--write-cache", action="store_true", help="写入 graph_snapshot 质量缓存")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
