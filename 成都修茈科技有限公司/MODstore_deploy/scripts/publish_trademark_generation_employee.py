"""将 trademark-generation-employee 发布到 catalog 并设为 AI 市场公开展示。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PKG_ID = "trademark-generation-employee"
META = {
    "name": "商标生成员",
    "description": (
        "为公司、产品、App、AI 员工和店铺生成原创商标/Logo 方向、视觉规范、"
        "生图提示词、矢量交付建议和初步近似风险自检清单；可选调用生图模型生成参考图。"
    ),
    "industry": "创意/品牌",
}


def main() -> int:
    from modstore_server.catalog_store import append_package, package_manifest_alignment_errors
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_asset_pipeline import (
        build_employee_pack_zip_for_library,
        mirror_catalog_file_to_market_files,
    )
    from modstore_server.mod_scaffold_runner import modstore_library_path
    from modstore_server.models import CatalogItem, User, get_session_factory, init_db

    init_db()
    sf = get_session_factory()
    lib = modstore_library_path()
    pack_dir = lib / PKG_ID
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        print(json.dumps({"ok": False, "error": f"missing {mf_path}"}, ensure_ascii=False))
        return 1

    raw_mf = json.loads(mf_path.read_text(encoding="utf-8"))
    zip_bytes = build_employee_pack_zip_for_library(PKG_ID, raw_mf, pack_dir=pack_dir)
    rec = {
        "id": PKG_ID,
        "name": META["name"],
        "version": str(raw_mf.get("version") or "1.0.0"),
        "description": META["description"],
        "artifact": "employee_pack",
        "industry": META["industry"],
        "release_channel": "stable",
        "commerce": {"mode": "free", "price": 0},
        "license": {"type": "personal", "verify_url": None},
    }

    with sf() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = db.query(User).order_by(User.id.asc()).first()
        if not admin:
            print(json.dumps({"ok": False, "error": "no user in db"}, ensure_ascii=False))
            return 2
        author_id = int(admin.id)

        with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)
        try:
            align_errs = package_manifest_alignment_errors(rec, tmp_path)
            if align_errs:
                print(json.dumps({"ok": False, "errors": align_errs}, ensure_ascii=False))
                return 1
            saved = append_package(rec, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        upsert_catalog_item_from_xc_package_dict(db, saved, author_id=author_id)
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == PKG_ID).first()
        if not row:
            row = CatalogItem(pkg_id=PKG_ID, author_id=author_id)
            db.add(row)
        row.version = saved.get("version") or rec["version"]
        row.name = saved.get("name") or rec["name"]
        row.description = saved.get("description") or rec["description"]
        row.price = 0.0
        row.artifact = "employee_pack"
        row.industry = saved.get("industry") or rec["industry"]
        row.stored_filename = saved.get("stored_filename") or ""
        row.sha256 = saved.get("sha256") or ""
        row.is_public = True
        row.compliance_status = "approved"
        row.material_category = "ai_employee"
        db.commit()
        mirror_catalog_file_to_market_files(row.stored_filename)
        from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

        _invalidate_market_catalog_caches()
        print(
            json.dumps(
                {
                    "ok": True,
                    "pkg_id": PKG_ID,
                    "catalog_item_id": row.id,
                    "stored_filename": saved.get("stored_filename"),
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
