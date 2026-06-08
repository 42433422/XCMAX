#!/usr/bin/env python3
"""将 FHD/mods/_employees/xcagi-host-foundation-employee 登记到 catalog（host_foundation 合集）。"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

_REPO_SIBLING = MODSTORE_ROOT.parent
_DEFAULT_PACK = _REPO_SIBLING / "FHD" / "mods" / "_employees" / "xcagi-host-foundation-employee"
_DEFAULT_XCMAX = (
    MODSTORE_ROOT.parent.parent / "FHD" / "mods" / "_employees" / "xcagi-host-foundation-employee"
)
DEFAULT_PACK_DIR = _DEFAULT_PACK if _DEFAULT_PACK.is_dir() else _DEFAULT_XCMAX

from modstore_server.host_foundation_pack import (  # noqa: E402
    HOST_FOUNDATION_EMPLOYEE_PACK_ID,
)


def _zip_employee_pack(pack_dir: Path) -> bytes:
    if not (pack_dir / "manifest.json").is_file():
        raise FileNotFoundError(f"缺少 manifest.json: {pack_dir}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in pack_dir.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=f.relative_to(pack_dir).as_posix())
    buf.seek(0)
    return buf.getvalue()


def _read_manifest(pack_dir: Path) -> Dict[str, Any]:
    data = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
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
    parser = argparse.ArgumentParser(description="Seed host foundation employee pack into catalog")
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR, help="员工包目录")
    parser.add_argument("--set-public", action="store_true", help="catalog_items.is_public=true")
    parser.add_argument("--force", action="store_true", help="覆盖已存在记录")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    pack_dir: Path = args.pack_dir.expanduser().resolve()
    if not pack_dir.is_dir():
        print(f"pack-dir 不存在: {pack_dir}", file=sys.stderr)
        return 2

    manifest = _read_manifest(pack_dir)
    pack_id = str(manifest.get("id") or "").strip()
    if pack_id != HOST_FOUNDATION_EMPLOYEE_PACK_ID:
        print(
            f"manifest.id 须为 {HOST_FOUNDATION_EMPLOYEE_PACK_ID}，当前为 {pack_id!r}",
            file=sys.stderr,
        )
        return 2

    raw_zip = _zip_employee_pack(pack_dir)
    if args.dry_run:
        print(f"[OK] {pack_id}: xcemp {len(raw_zip)} bytes from {pack_dir}")
        return 0

    from sqlalchemy import text

    from modstore_server.catalog_store import append_package
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_asset_pipeline import mirror_catalog_file_to_market_files
    from modstore_server.models import CatalogItem, get_session_factory

    session_factory = get_session_factory()
    with session_factory() as db:
        row = db.execute(
            text("SELECT id FROM users WHERE is_admin IS TRUE ORDER BY id ASC LIMIT 1"),
        ).fetchone()
        if not row:
            row = db.execute(text("SELECT id FROM users ORDER BY id ASC LIMIT 1")).fetchone()
        if not row:
            print("No user in DB", file=sys.stderr)
            return 3
        author_id = int(row[0])

    with session_factory() as db:
        exists = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
    if exists and not args.force:
        print(f"[SKIP] {pack_id}: already in catalog (use --force)")
        return 0

    rec = {
        "id": pack_id,
        "name": str(manifest.get("name") or pack_id),
        "version": str(manifest.get("version") or "1.0.0"),
        "description": str(manifest.get("description") or "")[:2000],
        "artifact": "employee_pack",
        "material_category": "ai_employee",
        "industry": "企业服务",
        "security_level": "enterprise",
        "is_public": bool(args.set_public),
        "release_channel": "stable",
        "commerce": {"mode": "free", "price": 0},
        "license": {"type": "enterprise", "verify_url": None},
        "tags": ["宿主基础", "预装员工", "bridge"],
    }
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(raw_zip)
            tmp_path = Path(tmp.name)
        saved = append_package(rec, tmp_path)
        with session_factory() as db:
            upsert_catalog_item_from_xc_package_dict(db, saved, author_id=author_id)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
            if row:
                if args.set_public:
                    row.is_public = True
                row.industry = rec["industry"]
                row.price = 0.0
                row.artifact = "employee_pack"
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
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] {pack_id}: {exc}", file=sys.stderr)
        return 1
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
