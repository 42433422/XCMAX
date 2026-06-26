"""将 chart-*-employee 可视化员工发布到 catalog 并设为 AI 市场公开展示。"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_deploy_env() -> None:
    """与 uvicorn 一致：优先读 MODstore_deploy/.env，避免 CLI 误写 sqlite。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / ".env.local", override=True)


_load_deploy_env()

from bootstrap_kitten_chart_employees import CHART_EMPLOYEES  # noqa: E402


def _publish_one(meta: dict) -> dict:
    from modstore_server.catalog_store import append_package, package_manifest_alignment_errors
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.employee_asset_pipeline import build_employee_pack_zip_for_library
    from modstore_server.models import CatalogItem, User, get_session_factory, init_db
    from modstore_server.mod_scaffold_runner import modstore_library_path

    pkg_id = meta["pkg_id"]
    lib = modstore_library_path()
    pack_dir = lib / pkg_id
    mf_path = pack_dir / "manifest.json"
    if not mf_path.is_file():
        return {"ok": False, "pkg_id": pkg_id, "error": f"missing {mf_path}"}

    raw_mf = json.loads(mf_path.read_text(encoding="utf-8"))
    zip_bytes = build_employee_pack_zip_for_library(pkg_id, raw_mf, pack_dir=pack_dir)
    rec = {
        "id": pkg_id,
        "name": meta["name"],
        "version": str(raw_mf.get("version") or "1.0.0"),
        "description": meta["description"],
        "artifact": "employee_pack",
        "industry": meta["industry"],
        "release_channel": "stable",
        "commerce": {"mode": "free", "price": 0},
        "license": {"type": "personal", "verify_url": None},
    }

    sf = get_session_factory()
    with sf() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = db.query(User).order_by(User.id.asc()).first()
        if not admin:
            return {"ok": False, "pkg_id": pkg_id, "error": "no user in db"}

        author_id = int(admin.id)
        with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)
        try:
            align_errs = package_manifest_alignment_errors(rec, tmp_path)
            if align_errs:
                return {"ok": False, "pkg_id": pkg_id, "errors": align_errs}
            saved = append_package(rec, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

        upsert_catalog_item_from_xc_package_dict(db, saved, author_id=author_id)
        row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pkg_id).first()
        if not row:
            row = CatalogItem(pkg_id=pkg_id, author_id=author_id)
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
        return {
            "ok": True,
            "pkg_id": pkg_id,
            "catalog_item_id": row.id,
            "stored_filename": saved.get("stored_filename"),
        }


def main() -> int:
    from modstore_server.models import init_db

    init_db()
    results = []
    for meta in CHART_EMPLOYEES:
        results.append(_publish_one(meta))
    from modstore_server.market_catalog_api import _invalidate_market_catalog_caches

    _invalidate_market_catalog_caches()
    ok = all(r.get("ok") for r in results)
    print(json.dumps({"ok": ok, "published": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
