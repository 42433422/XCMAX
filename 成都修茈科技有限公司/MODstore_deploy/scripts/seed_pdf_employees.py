#!/usr/bin/env python3
"""Seed pdf-full-read-employee and pdf-generate-employee into library + catalog (public)."""

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
        "pack_id": "pdf-full-read-employee",
        "brief": (
            "制作 PDF 全量读取员工包。上传 .pdf：只读原生文字层写入 outputs/document_full.txt；"
            "内嵌图片导出到 outputs/images/{figures,photos,diagrams,icons,uncategorized}/，"
            "并通过 VLM（ctx.call_llm vision）生成 .vlm.json 描述；元数据 outputs/document_meta.json。"
            "使用 direct_python，handlers 仅 direct_python。"
        ),
        "build_rule": "build_pdf_read_rule_spec",
        "convert": "render_pdf_read_convert_module",
        "runtime_kind": "pdf_full_read",
    },
    {
        "pack_id": "pdf-generate-employee",
        "brief": (
            "制作 PDF 生成员工包。上传 .pdf → 读取原生文字/分页结构 → 输出结构化 JSON（document_parsed.json）"
            "作为中介 → 写入 outputs/generated_document.pdf；可选用 agent 润色。"
            "handlers 含 direct_python 与 agent。"
        ),
        "build_rule": "build_pdf_generate_rule_spec",
        "convert": "render_pdf_generate_convert_module",
        "runtime_kind": "pdf_generate",
    },
)


def _build_pack(spec: dict) -> tuple[Path, bytes, dict, dict]:
    from modstore_server import pdf_extract_runtime as px
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        _normalize_manifest,
        materialize_asset_employee_pack,
    )

    brief = spec["brief"]
    build_rule = getattr(px, spec["build_rule"])
    convert_fn = getattr(px, spec["convert"])
    rule_spec = build_rule(brief)
    rule_spec["pack_id"] = spec["pack_id"]
    manifest = _normalize_manifest(_fallback_manifest(brief, rule_spec), brief, rule_spec)
    manifest["id"] = spec["pack_id"]
    _names = {
        "pdf-full-read-employee": "PDF 全量读取员",
        "pdf-generate-employee": "PDF 生成员",
    }
    manifest["name"] = _names.get(spec["pack_id"]) or manifest.get("name") or spec["pack_id"]
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
            "material_category": "ai_employee",
            "workpiece_type": "document_processor",
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
            row.material_category = (
                saved.get("material_category") or rec.get("material_category") or "ai_employee"
            )
            row.workpiece_type = (
                saved.get("workpiece_type") or rec.get("workpiece_type") or "document_processor"
            )
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
