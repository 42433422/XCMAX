#!/usr/bin/env python3
"""将 FHD/mods 下 6 个工作流员工 Mod 登记到 catalog（material_category=ai_employee）。"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

# MODstore 与 FHD 同属公司仓时：…/成都修茈科技有限公司/{MODstore_deploy,FHD/mods}
_REPO_SIBLING = MODSTORE_ROOT.parent
_DEFAULT_UNDER_SIBLING = _REPO_SIBLING / "FHD" / "mods"
_DEFAULT_UNDER_XCMAX = MODSTORE_ROOT.parent.parent / "FHD" / "mods"
DEFAULT_FHD_MODS = (
    _DEFAULT_UNDER_SIBLING
    if (_DEFAULT_UNDER_SIBLING / "xcagi-workflow-employee-label-print").is_dir()
    else _DEFAULT_UNDER_XCMAX
)

from modstore_server.workflow_employee_pack import WORKFLOW_EMPLOYEE_PKG_IDS  # noqa: E402


def _zip_mod_dir(mod_dir: Path) -> bytes:
    mod_dir = mod_dir.resolve()
    mid = mod_dir.name
    if not (mod_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"缺少 manifest.json: {mod_dir}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in mod_dir.rglob("*"):
            if f.is_file():
                arc = f"{mid}/{f.relative_to(mod_dir).as_posix()}"
                zf.write(f, arc)
    buf.seek(0)
    return buf.getvalue()


def _read_manifest(mod_dir: Path) -> Dict[str, Any]:
    data = json.loads((mod_dir / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest 须为对象")
    return data


def _load_deploy_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(MODSTORE_ROOT / ".env", override=False)
    load_dotenv(MODSTORE_ROOT / ".env.local", override=True)


def main() -> int:
    _load_deploy_env()
    parser = argparse.ArgumentParser(description="Seed 6 workflow employee mods into catalog")
    parser.add_argument(
        "--mods-dir",
        type=Path,
        default=DEFAULT_FHD_MODS,
        help="FHD mods 根目录（默认仓库 FHD/mods）",
    )
    parser.add_argument(
        "--set-public", action="store_true", help="设置 catalog_items.is_public=true"
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同 pkg_id 记录")
    parser.add_argument("--dry-run", action="store_true", help="仅打包校验，不写 catalog")
    args = parser.parse_args()

    mods_dir: Path = args.mods_dir.expanduser().resolve()
    if not mods_dir.is_dir():
        print(f"mods-dir 不存在: {mods_dir}", file=sys.stderr)
        return 2

    from sqlalchemy import text

    from modstore_server.catalog_store import append_package
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_asset_pipeline import mirror_catalog_file_to_market_files
    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path
    from modstore_server.models import CatalogItem, get_session_factory

    session_factory = get_session_factory()
    author_id = 0
    if not args.dry_run:
        with session_factory() as db:
            row = db.execute(
                text("SELECT id FROM users WHERE is_admin IS TRUE ORDER BY id ASC LIMIT 1"),
            ).fetchone()
            if not row:
                row = db.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1")).fetchone()
            if not row:
                print("No user in DB (skip catalog upsert or migrate DB)", file=sys.stderr)
                return 3
            author_id = int(row[0])

    lib = modstore_library_path()
    ok_count = 0
    for pack_id in WORKFLOW_EMPLOYEE_PKG_IDS:
        mod_dir = mods_dir / pack_id
        if not mod_dir.is_dir():
            print(f"[ERR] {pack_id}: 目录不存在 {mod_dir}")
            continue
        try:
            manifest = _read_manifest(mod_dir)
            raw_zip = _zip_mod_dir(mod_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: build failed: {exc}")
            continue

        inner_id = str(manifest.get("id") or "").strip()
        if inner_id != pack_id:
            print(f"[ERR] {pack_id}: manifest.id={inner_id!r} 与目录名不一致")
            continue

        if not args.dry_run:
            with session_factory() as db:
                exists = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
            if exists and not args.force:
                print(f"[SKIP] {pack_id}: already in catalog (use --force)")
                continue

        if not args.dry_run:
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(raw_zip)
                zip_tmp = Path(tmp.name)
            try:
                import_zip(zip_tmp, lib, replace=True)
            finally:
                zip_tmp.unlink(missing_ok=True)

        if args.dry_run:
            print(f"[OK] {pack_id}: zip {len(raw_zip)} bytes from {mod_dir}")
            ok_count += 1
            continue

        rec = {
            "id": pack_id,
            "name": str(manifest.get("name") or pack_id),
            "version": str(manifest.get("version") or "1.0.0"),
            "description": str(manifest.get("description") or "")[:2000],
            "artifact": "mod",
            "material_category": "ai_employee",
            "industry": "企业服务",
            "security_level": "enterprise",
            "is_public": bool(args.set_public),
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "enterprise", "verify_url": None},
        }
        tmp_xcmod: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xcmod", delete=False) as tmp:
                tmp.write(raw_zip)
                tmp_xcmod = Path(tmp.name)
            saved = append_package(rec, tmp_xcmod)
            with session_factory() as db:
                upsert_catalog_item_from_xc_package_dict(db, saved, author_id=author_id)
                row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
                if row:
                    if args.set_public:
                        row.is_public = True
                    row.industry = rec["industry"]
                    row.price = 0.0
                    row.artifact = "mod"
                    row.material_category = "ai_employee"
                    row.compliance_status = "approved"
                    row.name = str(manifest.get("name") or pack_id)[:256]
                    row.security_level = "enterprise"
                    row.license_scope = "enterprise"
                    db.commit()
                    try:
                        mirror_catalog_file_to_market_files(row.stored_filename)
                    except Exception:  # noqa: BLE001
                        pass
            pub = " public" if args.set_public else ""
            print(f"[SEED] {pack_id}: v{rec['version']}{pub}")
            ok_count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: catalog: {exc}")
        finally:
            if tmp_xcmod:
                tmp_xcmod.unlink(missing_ok=True)

    print(f"done: seeded={ok_count}/{len(WORKFLOW_EMPLOYEE_PKG_IDS)}")
    return 0 if ok_count == len(WORKFLOW_EMPLOYEE_PKG_IDS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
