#!/usr/bin/env python3
"""Seed txt-full-read-employee and txt-generate-employee into library + catalog (public)."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

MODSTORE_ROOT = Path(__file__).resolve().parents[1]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))


PACKS = (
    {
        "pack_id": "txt-full-read-employee",
        "brief": (
            "制作 TXT 全量读取员工包。上传 .txt 文件，直接读取全部纯文本内容并原样交付。"
            "使用 direct_python，输出 outputs/document_full.txt 与 document_meta.json。"
        ),
        "build_rule": "build_txt_read_rule_spec",
        "convert": "render_txt_read_convert_module",
        "runtime_kind": "txt_full_read",
    },
    {
        "pack_id": "txt-generate-employee",
        "brief": (
            "制作 TXT 生成员工包。上传 .txt → 读取全文 → 输出结构化 JSON → "
            "写入 outputs/generated_document.txt；可选用 agent 润色。"
        ),
        "build_rule": "build_txt_generate_rule_spec",
        "convert": "render_txt_generate_convert_module",
        "runtime_kind": "txt_generate",
    },
)


def _build_pack(spec: dict) -> tuple[Path, bytes, dict, dict]:
    from modstore_server import txt_extract_runtime as tx
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        _normalize_manifest,
        materialize_asset_employee_pack,
    )

    brief = spec["brief"]
    build_rule = getattr(tx, spec["build_rule"])
    convert_fn = getattr(tx, spec["convert"])
    rule_spec = build_rule(brief)
    manifest = _normalize_manifest(_fallback_manifest(brief, rule_spec), brief, rule_spec)
    manifest["id"] = spec["pack_id"]
    manifest["name"] = manifest.get("name") or spec["pack_id"]
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    emp["id"] = spec["pack_id"]
    manifest["employee"] = emp
    pack_dir, raw_zip = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest={"session_id": "seed", "user_id": 0, "assets": []},
        generated_convert_py=convert_fn(),
    )
    return pack_dir, raw_zip, manifest, rule_spec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish", action="store_true", help="Write to catalog_store + catalog_items"
    )
    parser.add_argument("--public", action="store_true", help="Set is_public=true on catalog rows")
    args = parser.parse_args()

    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path

    lib = modstore_library_path()
    for spec in PACKS:
        pack_dir, raw_zip, manifest, _ = _build_pack(spec)
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(raw_zip)
            tmp_path = Path(tmp.name)
        try:
            dest = import_zip(tmp_path, lib, replace=True)
            print(f"library: {dest}")
        finally:
            tmp_path.unlink(missing_ok=True)

        if not args.publish:
            continue

        from modstore_server.catalog_store import append_package
        from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
        from modstore_server.employee_asset_pipeline import mirror_catalog_file_to_market_files
        from modstore_server.models import CatalogItem, get_session_factory

        pid = spec["pack_id"]
        rec = {
            "id": pid,
            "name": str(manifest.get("name") or pid),
            "version": str(manifest.get("version") or "1.0.0"),
            "description": str(manifest.get("description") or spec["brief"][:400]),
            "artifact": "employee_pack",
            "industry": "通用",
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "personal", "verify_url": None},
        }
        with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as pkg_tmp:
            pkg_tmp.write(raw_zip)
            pkg_path = Path(pkg_tmp.name)
        try:
            saved = append_package(rec, pkg_path)
        finally:
            pkg_path.unlink(missing_ok=True)

        sf = get_session_factory()
        with sf() as db:
            upsert_catalog_item_from_xc_package_dict(db, saved, author_id=1)
            row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pid).first()
            if not row:
                row = CatalogItem(pkg_id=pid, author_id=1)
                db.add(row)
            row.version = saved.get("version") or rec["version"]
            row.name = saved.get("name") or rec["name"]
            row.description = saved.get("description") or rec["description"]
            row.price = 0.0
            row.artifact = "employee_pack"
            row.material_category = "ai_employee"
            row.industry = saved.get("industry") or rec["industry"]
            row.stored_filename = saved.get("stored_filename") or ""
            row.sha256 = saved.get("sha256") or ""
            if args.public:
                row.is_public = True
            db.commit()
            if row.stored_filename:
                mirror_catalog_file_to_market_files(row.stored_filename)
            print(f"catalog: {pid} is_public={row.is_public}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
