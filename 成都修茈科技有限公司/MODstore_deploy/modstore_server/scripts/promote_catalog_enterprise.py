#!/usr/bin/env python3
"""将指定 catalog 商品提升为「企业级」展示（license_scope + security_level = enterprise）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

from modstore_server.catalog_quality import PUBLIC_TABULAR_PKG_IDS  # noqa: E402
from modstore_server.workflow_employee_pack import WORKFLOW_EMPLOYEE_PKG_IDS  # noqa: E402


def _load_deploy_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(MODSTORE_ROOT / ".env", override=False)
    load_dotenv(MODSTORE_ROOT / ".env.local", override=True)


def main() -> int:
    _load_deploy_env()
    parser = argparse.ArgumentParser(description="Promote catalog items to enterprise tier")
    parser.add_argument("--pkg-id", action="append", default=[], help="指定 pkg_id，可重复")
    parser.add_argument("--all-office", action="store_true", help="办公员工包 10 件（表格类）")
    parser.add_argument("--all-workflow", action="store_true", help="工作流员工 Mod 6 件")
    parser.add_argument("--dry-run", action="store_true", help="仅打印将修改的行，不写库")
    args = parser.parse_args()

    pkg_ids: list[str] = []
    if args.all_office:
        pkg_ids.extend(PUBLIC_TABULAR_PKG_IDS)
    if args.all_workflow:
        pkg_ids.extend(WORKFLOW_EMPLOYEE_PKG_IDS)
    for pid in args.pkg_id or []:
        p = str(pid or "").strip()
        if p and p not in pkg_ids:
            pkg_ids.append(p)

    if not pkg_ids:
        print("请指定 --pkg-id、--all-office 或 --all-workflow", file=sys.stderr)
        return 2

    from modstore_server.models import CatalogItem, get_session_factory

    sf = get_session_factory()
    updated = 0
    missing: list[str] = []
    with sf() as db:
        for pid in pkg_ids:
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pid).first()
            if not row:
                missing.append(pid)
                continue
            old_lic = str(getattr(row, "license_scope", "") or "")
            old_sec = str(getattr(row, "security_level", "") or "")
            if old_lic == "enterprise" and old_sec == "enterprise":
                print(f"[SKIP] {pid}: 已是企业级")
                continue
            print(
                f"[{'DRY' if args.dry_run else 'SET'}] {pid}: license_scope {old_lic!r} -> enterprise; security_level {old_sec!r} -> enterprise"
            )
            if not args.dry_run:
                row.license_scope = "enterprise"
                row.security_level = "enterprise"
                if not str(row.industry or "").strip():
                    row.industry = "企业服务"
                updated += 1
        if not args.dry_run:
            db.commit()

    if missing:
        print(f"未在 catalog 中找到: {', '.join(missing)}", file=sys.stderr)
    print(f"done: updated={updated}, missing={len(missing)}, requested={len(pkg_ids)}")
    return 0 if not missing or updated > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
