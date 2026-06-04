#!/usr/bin/env python3
"""将 FHD/mods/_employees 下已修复的 manifest + backend 重新打包进本机 MODstore catalog。"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

FHD_ROOT = Path(__file__).resolve().parents[2]
MODSTORE_ROOT = FHD_ROOT.parent / "成都修茈科技有限公司" / "MODstore_deploy"
EMP_ROOT = FHD_ROOT / "mods" / "_employees"

if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 catalog 条目")
    parser.add_argument("--pkg-ids", type=str, default="", help="逗号分隔；默认全部 employee_pack 目录")
    args = parser.parse_args()

    only: set[str] | None = None
    if args.pkg_ids.strip():
        only = {p.strip() for p in args.pkg_ids.split(",") if p.strip()}

    from modstore_server.application.catalog import get_default_catalog_application_service
    from modstore_server.application.employee import get_default_employee_application_service
    from modstore_server.employee_asset_pipeline import build_employee_pack_zip_for_library
    from modstore_server.models import CatalogItem, User, get_session_factory

    session_factory = get_session_factory()
    with session_factory() as db:
        author = db.query(User).filter(User.is_admin == True).order_by(User.id.asc()).first()  # noqa: E712
        author = author or db.query(User).order_by(User.id.asc()).first()
        if not author:
            print("No user in DB", file=sys.stderr)
            return 3
        author_id = int(author.id)

    catalog_app = get_default_catalog_application_service()
    employee_app = get_default_employee_application_service()
    ok = fail = skip = 0

    for pack_dir in sorted(p for p in EMP_ROOT.iterdir() if p.is_dir()):
        mf_path = pack_dir / "manifest.json"
        if not mf_path.is_file():
            continue
        try:
            manifest = json.loads(mf_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[ERR] {pack_dir.name}: manifest {exc}")
            fail += 1
            continue
        if manifest.get("artifact") != "employee_pack":
            continue
        pack_id = str(manifest.get("id") or pack_dir.name).strip()
        if only is not None and pack_id not in only:
            continue

        with session_factory() as db:
            exists = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if exists and not args.force:
            print(f"[SKIP] {pack_id}")
            skip += 1
            continue

        try:
            archive = build_employee_pack_zip_for_library(pack_id, manifest, pack_dir=pack_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: zip {exc}")
            fail += 1
            continue

        v2 = manifest.get("employee_config_v2") if isinstance(manifest.get("employee_config_v2"), dict) else {}
        ident = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
        record = {
            "id": pack_id,
            "name": manifest.get("name") or pack_id,
            "version": manifest.get("version") or "1.0.0",
            "description": manifest.get("description") or ident.get("description") or "",
            "artifact": "employee_pack",
            "industry": str(ident.get("area") or "yuangon").strip() or "yuangon",
            "security_level": "personal",
            "is_public": False,
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "internal", "verify_url": None},
            "probe_mod_id": "yuangon",
        }

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
                tmp.write(archive)
                tmp_path = Path(tmp.name)
            with session_factory() as db:
                saved = catalog_app.register_employee_pack(
                    db,
                    author_id=author_id,
                    mod_id="yuangon",
                    pack_id=pack_id,
                    package_record=record,
                    package_file=tmp_path,
                    price=0.0,
                )
                employee_app.register_pack(
                    author_id=author_id,
                    mod_id="yuangon",
                    pack_id=pack_id,
                    version=str(saved.get("version") or record["version"]),
                )
                db.commit()
            print(f"[SYNC] {pack_id}")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {pack_id}: catalog {exc}")
            fail += 1
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)

    market_dir = MODSTORE_ROOT / "modstore_server" / "market_files"
    files_dir = MODSTORE_ROOT / "modstore_server" / "catalog_data" / "files"
    market_dir.mkdir(parents=True, exist_ok=True)
    for xcemp in files_dir.glob("*.xcemp"):
        dst = market_dir / xcemp.name
        dst.write_bytes(xcemp.read_bytes())

    print(f"done: sync={ok} skip={skip} fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
