#!/usr/bin/env python3
"""Seed ppt-full-read-employee and ppt-generate-employee into library + catalog (public)."""

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
        "pack_id": "ppt-full-read-employee",
        "brief": (
            "制作 PPT 全量读取员工包。上传 .pptx：解析大纲与每页正文写入 outputs/presentation_full.json；"
            "内嵌图片导出到 outputs/images/ 并通过 VLM（ctx.call_llm vision）生成 .vlm.json；"
            "按提示词「为这份PPT生成每页的演讲备注」生成 notes_generated 与 outputs/speaker_notes.md。"
            "使用 direct_python，handlers 仅 direct_python，禁止编造幻灯片正文。"
        ),
        "build_rule": "build_ppt_read_rule_spec",
        "convert": "render_ppt_read_convert_module",
        "runtime_kind": "ppt_full_read",
        "description": (
            "PPT全量读取员工：上传 .pptx，输出 presentation_full.json 中介；"
            "解析大纲与每页正文；图片 VLM 识图；"
            "按「为这份PPT生成每页的演讲备注」生成演讲备注。direct_python，禁止编造幻灯片正文。"
        ),
    },
    {
        "pack_id": "ppt-generate-employee",
        "brief": (
            "制作 PPT 生成员工包（Codex 级）。compose-first：无模板时从零合成多页 output.pptx；"
            "enhance：复制 template.pptx 后按 LLM 编排的 ppt_edit_plan 注入 OOXML 动画；"
            "输入 presentation_full v2 JSON / user_query / .txt，可选 template_file；"
            "输出 output.pptx 与 ppt_edit_plan.json；作业跑马灯用 homework_marquee 配方；direct_python。"
        ),
        "build_rule": "build_ppt_generate_rule_spec",
        "convert": "render_ppt_generate_convert_module",
        "runtime_kind": "ppt_generate",
        "description": (
            "PPT 生成员：LLM 编排 + OOXML 执行。支持从零 compose 多页演示、"
            "基于上传 pptx 增强（图片+动画）。输出 output.pptx，禁止纯文字冒充动效作业。"
        ),
    },
)


def _build_pack(spec: dict) -> tuple[Path, bytes, dict, dict]:
    from modstore_server import ppt_extract_runtime as px
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
        "ppt-full-read-employee": "PPT 全量读取员",
        "ppt-generate-employee": "PPT 生成员",
    }
    manifest["name"] = _names.get(spec["pack_id"]) or manifest.get("name") or spec["pack_id"]
    manifest["description"] = spec.get("description") or manifest.get("description") or brief[:400]
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
    parser.add_argument("--publish", action="store_true", help="Write to catalog_store + catalog_items")
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
            "industry": "数据处理",
            "material_category": "ai_employee",
            "workpiece_type": "document_processor",
            "security_level": "enterprise",
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "enterprise", "verify_url": None},
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
            row.material_category = saved.get("material_category") or rec.get("material_category") or "ai_employee"
            row.workpiece_type = saved.get("workpiece_type") or rec.get("workpiece_type") or "document_processor"
            row.industry = saved.get("industry") or rec["industry"]
            row.security_level = saved.get("security_level") or rec.get("security_level") or "enterprise"
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
