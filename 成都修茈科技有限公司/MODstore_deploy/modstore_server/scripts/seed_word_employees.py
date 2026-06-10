#!/usr/bin/env python3
"""Seed Word 全量读取 + Word 生成员工包到 catalog（与 excel seed 同流程）。"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

MODSTORE_ROOT = Path(__file__).resolve().parents[2]
if str(MODSTORE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODSTORE_ROOT))

PACKS: List[Dict[str, str]] = [
    {
        "pack_id": "word-full-read-employee",
        "name": "Word 全量读取员",
        "brief": (
            "Word全量读取员工：上传 .docx，direct_python 全量提取段落/表格/样式，"
            "输出 document_full.json，禁止 LLM 编造。"
        ),
    },
    {
        "pack_id": "word-generate-employee",
        "name": "Word 生成员",
        "brief": (
            "Word生成员工：支持 document_full.json、user_query 纯文本或 .txt；"
            "可选 template.docx；输出 generated_document.docx。"
        ),
    },
]


def _build_pack(
    pack_id: str, brief: str, *, spec: Dict[str, str]
) -> tuple[Dict[str, Any], Dict[str, Any], bytes, Path]:
    from modstore_server.employee_asset_pipeline import (
        _fallback_manifest,
        _normalize_manifest,
        materialize_asset_employee_pack,
    )
    from modstore_server.word_extract_runtime import (
        build_word_extract_rule_spec,
        render_word_fallback_convert_module,
    )
    from modstore_server.word_generate_runtime import (
        build_word_generate_rule_spec,
        is_word_generate,
        render_word_generate_convert_module,
    )

    is_generate = str(pack_id or "").endswith("-generate-employee")
    rule_spec = (
        build_word_generate_rule_spec(brief) if is_generate else build_word_extract_rule_spec(brief)
    )
    rule_spec["pack_id"] = pack_id
    asset_manifest = {
        "session_id": "seed",
        "user_id": 0,
        "root": "",
        "assets": [],
        "templates": [],
        "example_inputs": [],
        "expected_outputs": [],
        "rules": [],
    }
    manifest = _normalize_manifest(_fallback_manifest(brief, rule_spec), brief, rule_spec)
    manifest["id"] = pack_id
    display_name = str(spec.get("name") or manifest.get("name") or pack_id).strip()
    manifest["name"] = display_name
    v2 = (
        manifest.get("employee_config_v2")
        if isinstance(manifest.get("employee_config_v2"), dict)
        else {}
    )
    ident = v2.get("identity") if isinstance(v2.get("identity"), dict) else {}
    ident["id"] = pack_id
    v2["identity"] = ident
    manifest["employee_config_v2"] = v2
    emp = manifest.get("employee") if isinstance(manifest.get("employee"), dict) else {}
    emp["id"] = pack_id
    emp["label"] = display_name
    manifest["employee"] = emp

    convert_py = (
        render_word_generate_convert_module()
        if is_generate
        else render_word_fallback_convert_module()
    )
    if is_generate:
        assert is_word_generate(brief) or pack_id == "word-generate-employee"

    pack_dir, raw_zip = materialize_asset_employee_pack(
        manifest=manifest,
        rule_spec=rule_spec,
        asset_manifest=asset_manifest,
        generated_convert_py=convert_py,
    )
    return manifest, rule_spec, raw_zip, pack_dir


def _load_deploy_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(MODSTORE_ROOT / ".env", override=False)
    load_dotenv(MODSTORE_ROOT / ".env.local", override=True)


def main() -> int:
    _load_deploy_env()
    parser = argparse.ArgumentParser(description="Seed Word read/generate employee packs")
    parser.add_argument(
        "--set-public", action="store_true", help="设置 catalog_items.is_public=true"
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的同 pkg_id 记录")
    parser.add_argument("--dry-run", action="store_true", help="仅构建包，不写 catalog")
    args = parser.parse_args()

    from modstore_server.catalog_store import append_package
    from modstore_server.catalog_sync import upsert_catalog_item_from_xc_package_dict
    from modstore_server.mod_scaffold_runner import import_zip, modstore_library_path
    from modstore_server.models import CatalogItem, User, get_session_factory, init_db

    init_db()
    sf = get_session_factory()
    results: List[Dict[str, Any]] = []

    with sf() as db:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = db.query(User).order_by(User.id.asc()).first()
        if not admin:
            print(json.dumps({"ok": False, "error": "no user"}, ensure_ascii=False))
            return 2
        author_id = int(admin.id)

    lib = modstore_library_path()
    for spec in PACKS:
        pack_id = spec["pack_id"]
        brief = spec["brief"]
        manifest, rule_spec, raw_zip, pack_dir = _build_pack(pack_id, brief, spec=spec)
        if args.dry_run:
            results.append({"pack_id": pack_id, "dry_run": True, "pack_dir": str(pack_dir)})
            continue

        with sf() as db:
            existing = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
        if existing and not args.force:
            results.append({"pack_id": pack_id, "skipped": True, "id": existing.id})
            continue

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(raw_zip)
            zip_tmp = Path(tmp.name)
        try:
            import_zip(zip_tmp, lib, replace=True)
        finally:
            zip_tmp.unlink(missing_ok=True)

        (lib / pack_id / "rule_spec.json").write_text(
            json.dumps(rule_spec, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        rec = {
            "id": pack_id,
            "name": spec["name"],
            "version": str(manifest.get("version") or "1.0.0"),
            "description": brief[:500],
            "artifact": "employee_pack",
            "industry": "文档/知识",
            "is_public": bool(args.set_public),
            "release_channel": "stable",
            "commerce": {"mode": "free", "price": 0},
            "license": {"type": "personal", "verify_url": None},
        }
        with tempfile.NamedTemporaryFile(suffix=".xcemp", delete=False) as tmp:
            tmp.write(raw_zip)
            tmp_path = Path(tmp.name)
        try:
            saved = append_package(rec, tmp_path)
            with sf() as db:
                upsert_catalog_item_from_xc_package_dict(db, saved, author_id=author_id)
                row = db.query(CatalogItem).filter(CatalogItem.pkg_id == pack_id).first()
                if row and args.set_public:
                    row.is_public = True
                db.commit()
                results.append(
                    {
                        "pack_id": pack_id,
                        "catalog_id": row.id if row else None,
                        "is_public": bool(row.is_public) if row else False,
                    }
                )
        finally:
            tmp_path.unlink(missing_ok=True)

    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
